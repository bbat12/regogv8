#!/usr/bin/env python3
"""
REGOG Web App — Flask backend that wraps the existing scan pipeline.
Serves the single-page dark UI and provides streaming scan results.
"""

import sys
import os
import json
import logging
import threading
import queue
import time
from pathlib import Path
from datetime import datetime

# Ensure REGOG modules are importable (both project root and regog/ package)
sys.path.insert(0, str(Path(__file__).parent.parent / "regog"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, jsonify, request, Response, send_from_directory, stream_with_context
from flask_cors import CORS

# ─── App Setup ─────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app)

# In-memory state
_scan_progress: dict[str, queue.Queue] = {}  # session_id -> Queue of property dicts
_scan_status: dict[str, dict] = {}            # session_id -> status metadata
_scan_status_lock: threading.Lock = threading.Lock()  # protects _scan_status
_cancel_events: dict[str, threading.Event] = {}        # session_id -> Event, set when cancel requested
_saved_properties: set[str] = set()            # set of listing_ids

# Ensure we capture all logging (including stderr for debugging thread errors)
logging.basicConfig(level=logging.DEBUG, force=True,
                    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("regog-web")
logger.setLevel(logging.DEBUG)

# ─── API Endpoints ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the main SPA HTML."""
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/config")
def get_config():
    """Return current REGOG configuration."""
    import config as cfg
    return jsonify({
        "weights": {
            "residential": cfg.RESIDENTIAL_WEIGHTS,
            "land": cfg.LAND_WEIGHTS,
            "commercial": cfg.COMMERCIAL_WEIGHTS,
        },
        "tier_thresholds": cfg.TIER_THRESHOLDS,
        "comp_defaults": cfg.COMP_DEFAULTS,
        "rate_limits": cfg.RATE_LIMITS,
    })


@app.route("/api/stats")
def get_stats():
    """Return database stats."""
    from db.database import get_connection, get_stats
    conn = get_connection()
    try:
        stats = get_stats(conn)
        return jsonify(stats)
    finally:
        conn.close()


@app.route("/api/scans")
def list_scans():
    """Return recent scan sessions."""
    from db.database import get_connection
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, started_at, completed_at, scan_type, search_params, "
            "properties_found, hot_leads_found "
            "FROM scan_sessions ORDER BY started_at DESC LIMIT 20"
        ).fetchall()
        scans = []
        for row in rows:
            d = dict(row)
            try:
                d["search_params"] = json.loads(d.get("search_params") or "{}")
            except (json.JSONDecodeError, TypeError):
                d["search_params"] = {}
            scans.append(d)
        return jsonify(scans)
    finally:
        conn.close()


@app.route("/api/scan/<session_id>/results")
def get_scan_results(session_id):
    """Return paginated results for a completed scan."""
    from db.database import get_connection, get_session_properties
    conn = get_connection()
    try:
        props = get_session_properties(conn, session_id)

        # Pagination
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 50, type=int)
        tier = request.args.get("tier")

        if tier:
            props = [p for p in props if p.get("lead_tier") == tier]

        total = len(props)
        start = (page - 1) * per_page
        end = start + per_page
        page_props = props[start:end]

        return jsonify({
            "properties": _serialize_props(page_props),
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page if per_page else 1,
        })
    finally:
        conn.close()


@app.route("/api/scan/<session_id>/status")
def get_scan_status(session_id):
    """Return current scan status (for polling after SSE closes)."""
    status = _scan_status.get(session_id, {"status": "unknown"})
    return jsonify(status)


@app.route("/api/scan/<session_id>/cancel", methods=["POST"])
def cancel_scan(session_id):
    """Cancel a running scan."""
    if session_id in _cancel_events:
        _cancel_events[session_id].set()
        status = _scan_status.get(session_id, {})
        status["status"] = "cancelling"
        with _scan_status_lock:
            _scan_status[session_id] = status
        return jsonify({"status": "cancelling", "session_id": session_id})
    else:
        # Already completed or doesn't exist
        status = _scan_status.get(session_id, {"status": "unknown"})
        return jsonify({"status": status.get("status", "unknown")})


@app.route("/api/scan/<session_id>/stream")
def stream_scan(session_id):
    """SSE endpoint that streams properties as they're scored."""
    def generate():
        q = _scan_progress.get(session_id)
        if not q:
            yield "event: error\ndata: Scan session not found\n\n"
            return

        # Send initial connected event
        yield f"event: connected\ndata: {json.dumps({'session_id': session_id})}\n\n"

        while True:
            try:
                prop = q.get(timeout=30)
                if prop is None:
                    # Signal that scan is complete
                    status = _scan_status.get(session_id, {})
                    yield f"event: complete\ndata: {json.dumps(status)}\n\n"
                    break

                yield f"event: property\ndata: {json.dumps(_serialize_prop(prop))}\n\n"

            except queue.Empty:
                # Send keepalive
                yield "event: keepalive\ndata: {}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/scan", methods=["POST"])
def start_scan():
    """Start a new scan in a background thread. Returns session_id."""
    data = request.get_json() or {}
    location = data.get("location", "").strip()
    scan_type = data.get("scan_type", "residential")
    price_min = data.get("price_min")
    price_max = data.get("price_max")
    skip_flood = data.get("skip_flood", True)
    use_zillow = data.get("use_zillow", False)

    if not location:
        return jsonify({"error": "Location is required"}), 400

    # Create the scan session in DB
    from db.database import get_connection, create_scan_session

    conn = get_connection()
    search_params = {
        "location": location,
        "scan_type": scan_type,
        "price_min": price_min,
        "price_max": price_max,
    }
    session_id = create_scan_session(conn, scan_type, search_params)
    conn.close()

    # Set up progress queue, cancel event, and status
    q: queue.Queue = queue.Queue()
    _scan_progress[session_id] = q
    _cancel_events[session_id] = threading.Event()
    _scan_status[session_id] = {
        "status": "running",
        "session_id": session_id,
        "progress": 0,
        "total": 0,
        "hot_count": 0,
        "started_at": datetime.utcnow().isoformat(),
    }

    # Start scan in background thread
    thread = threading.Thread(
        target=_run_scan_background,
        args=(session_id, location, scan_type, price_min, price_max, skip_flood, use_zillow, q),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "session_id": session_id,
        "status": "started",
        "stream_url": f"/api/scan/{session_id}/stream",
    })


@app.route("/api/saved", methods=["GET"])
def list_saved():
    """Return all saved properties."""
    from db.database import get_connection
    conn = get_connection()
    try:
        if not _saved_properties:
            return jsonify({"properties": []})

        placeholders = ",".join("?" for _ in _saved_properties)
        rows = conn.execute(
            f"SELECT * FROM properties WHERE listing_id IN ({placeholders}) "
            f"ORDER BY score_total DESC LIMIT 100",
            list(_saved_properties),
        ).fetchall()

        from db.database import _deserialize_row
        props = [_deserialize_row(row) for row in rows]
        return jsonify({"properties": _serialize_props(props)})
    finally:
        conn.close()


@app.route("/api/saved/<listing_id>", methods=["POST"])
def toggle_save(listing_id):
    """Toggle saved status for a property."""
    data = request.get_json() or {}
    saved = data.get("saved", False)

    if saved:
        _saved_properties.add(listing_id)
    else:
        _saved_properties.discard(listing_id)

    return jsonify({"listing_id": listing_id, "saved": listing_id in _saved_properties})


@app.route("/api/saved/<listing_id>/status")
def get_saved_status(listing_id):
    """Check if a property is saved."""
    return jsonify({"listing_id": listing_id, "saved": listing_id in _saved_properties})


@app.route("/api/property/<listing_id>")
def get_property_detail(listing_id):
    """Return full detail for a single property."""
    from db.database import get_connection, _deserialize_row
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM properties WHERE listing_id = ?", (listing_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Property not found"}), 404
        return jsonify(_serialize_prop(_deserialize_row(row)))
    finally:
        conn.close()


# ─── Background Scan Runner ───────────────────────────────────────────────

def _run_scan_background(
    session_id: str,
    location: str,
    scan_type: str,
    price_min: int | None,
    price_max: int | None,
    skip_flood: bool,
    use_zillow: bool,
    progress_q: queue.Queue,
):
    """Run the scan pipeline in a background thread, pushing results to the queue."""
    from db.database import get_connection, complete_scan_session, upsert_property, _deserialize_row
    from scrapers.homeharvest_scraper import fetch_listings, normalize_listing
    from scrapers.redfin_scraper import fetch_sold_comps
    from enrichment.brain import classify_property
    from enrichment.comp_engine import calculate_comps
    from enrichment.enricher import enrich_property
    from enrichment.listing_filter import filter_listing
    from scoring.residential_score import score_residential
    from scoring.land_score import score_land
    from scoring.commercial_score import score_commercial

    conn = get_connection()
    processed = 0
    hot_count = 0
    filtered_out = 0

    try:
        def _update_status(status_dict: dict):
            """Thread-safe update of scan status."""
            with _scan_status_lock:
                _scan_status[session_id] = status_dict

        # Update status
        status = _scan_status.get(session_id, {})
        status["status"] = "fetching_comps"
        _update_status(status)

        # Fetch sold comps
        sold_comps = fetch_sold_comps(
            location=location,
            scan_type=scan_type,
            past_days=180,
            limit=200,
        )

        status["status"] = "scanning"
        status["comps_found"] = len(sold_comps)
        _update_status(status)

        # Fetch listings
        # HomeHarvest accepts: single_family, multi_family, condos, townhomes, condo_townhome_rowhome_coop,
        #                      duplex_triplex, farm, land, mobile, apartment
        property_types = {
            "residential": ["single_family", "mobile"],  # Single family + mobile homes
            "land": ["land"],                              # Vacant land only
            "commercial": ["multi_family", "apartment", "condos", "townhomes", "duplex_triplex", "farm"],  # Everything else except mobile
        }.get(scan_type)

        raw_listings = fetch_listings(
            location=location,
            listing_type="for_sale",
            past_days=90,
            property_type=property_types,
        )

        if not raw_listings:
            progress_q.put(None)
            complete_scan_session(conn, session_id, 0, 0)
            status["status"] = "completed"
            status["properties_found"] = 0
            status["hot_leads"] = 0
            _update_status(status)
            conn.close()
            return

        # Optionally fetch Zillow listings
        if use_zillow:
            try:
                from scrapers.zillow_stealth import fetch_zillow_listings
                zillow_listings = fetch_zillow_listings(
                    location=location,
                    listing_type="for_sale",
                    max_pages=2,
                )
                existing_keys = {
                    (r.get("address", ""), r.get("list_price"))
                    for r in raw_listings
                }
                for z in zillow_listings:
                    key = (z.get("address", ""), z.get("list_price"))
                    if key not in existing_keys:
                        raw_listings.append(z)
                        existing_keys.add(key)
            except Exception:
                pass

        total = len(raw_listings)
        status["total"] = total
        _update_status(status)

        # Check for cancel request before processing
        if _cancel_events.get(session_id, threading.Event()).is_set():
            logger.info(f"Scan {session_id} cancelled by user before processing")
            progress_q.put(None)
            conn.close()
            return

        # Process each property
        for i, raw in enumerate(raw_listings):
            try:
                # Normalize
                if raw.get("source") == "zillow":
                    prop = raw
                    prop["scan_session_id"] = session_id
                else:
                    prop = normalize_listing(raw, source="realtor", scan_session_id=session_id, scan_type=scan_type)

                # Price filter
                list_price = prop.get("list_price") or 0
                if price_min and list_price < price_min:
                    continue
                if price_max and list_price > price_max:
                    continue

                # Brain classification
                brain = classify_property(
                    address=prop.get("address", ""),
                    scan_type=scan_type,
                    list_price=prop.get("list_price"),
                    sqft=prop.get("sqft"),
                    year_built=prop.get("year_built"),
                    days_on_market=prop.get("days_on_market"),
                    description=prop.get("listing_description"),
                )
                prop["brain_classification"] = brain["classification"]
                prop["brain_red_flags"] = brain["red_flags"]
                prop["brain_green_flags"] = brain["green_flags"]
                prop["brain_seller_motivation"] = brain["seller_motivation"]

                # Listing filter: catch auctions, bait prices, burned/demolished
                filter_result = filter_listing(
                    description=prop.get("listing_description"),
                    list_price=prop.get("list_price"),
                    sqft=prop.get("sqft"),
                    style=prop.get("style"),
                    brain_classification=prop.get("brain_classification"),
                )
                if filter_result:
                    if filter_result["action"] == "skip":
                        logger.info(f"Filtered out: {filter_result['reason']} — {prop.get('address', '?')}")
                        filtered_out += 1
                        continue
                    # 'flag' level: keep but tag it
                    prop["filter_reason"] = filter_result["reason"]
                    prop["filter_type"] = filter_result["filter_type"]

                # Enrich
                prop = enrich_property(prop, skip_flood=skip_flood)

                # Comps
                comp_result = calculate_comps(prop, sold_comps, scan_type=scan_type)
                prop.update(comp_result)

                # Score
                if scan_type == "residential":
                    score_result = score_residential(prop)
                elif scan_type == "land":
                    score_result = score_land(prop)
                else:
                    score_result = score_commercial(prop)

                prop["score_total"] = score_result["total"]
                # Map score components — different scan types use different keys
                if scan_type == "land":
                    prop["score_price_deviation"] = score_result["scores"].get("price_deviation",
                        score_result["scores"].get("price_per_acre_deviation", 0))
                    prop["score_dom_signal"] = score_result["scores"].get("dom_signal", 0)
                    prop["score_assessor_gap"] = score_result["scores"].get("assessor_gap",
                        score_result["scores"].get("zoning_bonus", 0))
                    prop["score_condition"] = score_result["scores"].get("condition",
                        score_result["scores"].get("acreage_premium", 0))
                else:
                    prop["score_price_deviation"] = score_result["scores"].get("price_deviation", 0)
                    prop["score_dom_signal"] = score_result["scores"].get("dom_signal", 0)
                    prop["score_assessor_gap"] = score_result["scores"].get("assessor_gap", 0)
                    prop["score_condition"] = score_result["scores"].get("condition", 0)
                prop["score_flood_penalty"] = score_result["scores"].get("flood_penalty", 0)
                prop["lead_tier"] = score_result["tier"]
                prop["data_confidence"] = score_result.get("data_confidence", "HIGH")

                # Upsert to DB
                upsert_property(conn, prop)

                # Push to SSE stream
                progress_q.put(dict(prop))

                if prop["lead_tier"] == "HOT":
                    hot_count += 1
                processed += 1

                # Check for cancel request
                if _cancel_events.get(session_id, threading.Event()).is_set():
                    logger.info(f"Scan {session_id} cancelled by user after {processed} properties")
                    status["status"] = "cancelled"
                    status["progress"] = processed
                    status["properties_found"] = processed
                    status["hot_leads"] = hot_count
                    status["filtered_out"] = filtered_out
                    _update_status(status)
                    complete_scan_session(conn, session_id, processed, hot_count)
                    conn.commit()
                    progress_q.put(None)
                    conn.close()
                    return

                # Update status every 10 properties
                if i % 10 == 0:
                    status["progress"] = i
                    status["hot_count"] = hot_count
                    _update_status(status)

            except Exception as e:
                import traceback
                logger.error(f"Error processing listing {i}: {e}")
                logger.error(traceback.format_exc())
                continue

        # Complete session
        complete_scan_session(conn, session_id, processed, hot_count)
        conn.commit()

        status["status"] = "completed"
        status["progress"] = processed
        status["total"] = total
        status["hot_count"] = hot_count
        status["properties_found"] = processed
        status["hot_leads"] = hot_count
        status["filtered_out"] = filtered_out
        status["completed_at"] = datetime.utcnow().isoformat()
        _update_status(status)

        # Signal completion
        progress_q.put(None)

    except Exception as e:
        logger.exception("Scan error")
        status["status"] = "error"
        status["error"] = str(e)
        _update_status(status)
        progress_q.put(None)
        complete_scan_session(conn, session_id, processed, hot_count)
        conn.commit()
    finally:
        _cancel_events.pop(session_id, None)
        conn.close()


# ─── Serialization helpers ────────────────────────────────────────────────

def _serialize_prop(prop: dict) -> dict:
    """Serialize a property dict for JSON response."""
    serialized = {}
    for k, v in prop.items():
        if isinstance(v, (int, float, str, bool)) or v is None:
            serialized[k] = v
        elif isinstance(v, (list, dict)):
            # Already JSON-serializable — pass through as-is for jsonify
            serialized[k] = v
        else:
            serialized[k] = str(v)
    return serialized


def _serialize_props(props: list[dict]) -> list[dict]:
    """Serialize a list of property dicts."""
    return [_serialize_prop(p) for p in props]


# ─── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"╔══════════════════════════════════════╗")
    print(f"║   REGOG Web App                      ║")
    print(f"║   Running on http://localhost:{port}  ║")
    print(f"╚══════════════════════════════════════╝")
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
