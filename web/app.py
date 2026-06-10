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

# ── Top 20 US Metro Areas (for nationwide lava scans) ──────────────────
TOP_20_METROS: list[str] = [
    "New York, NY",
    "Los Angeles, CA",
    "Chicago, IL",
    "Dallas, TX",
    "Houston, TX",
    "Miami, FL",
    "Atlanta, GA",
    "Phoenix, AZ",
    "Philadelphia, PA",
    "San Antonio, TX",
    "San Diego, CA",
    "Orlando, FL",
    "Seattle, WA",
    "Denver, CO",
    "Tampa, FL",
    "Portland, OR",
    "Charlotte, NC",
    "Nashville, TN",
    "Las Vegas, NV",
    "Austin, TX",
]

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
    lava_mode = data.get("lava_mode", False)
    lava_min_profit = data.get("lava_min_profit", 200)
    lava_scope = data.get("lava_scope", "city")  # "city" or "nationwide"
    lava_state = data.get("lava_state", "")

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
        "lava_mode": lava_mode,
        "lava_min_profit": lava_min_profit,
        "lava_scope": lava_scope,
        "lava_state": lava_state,
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
        "lava_mode": lava_mode,
        "lava_min_profit": lava_min_profit,
        "lava_scope": lava_scope,
        "lava_state": lava_state,
    }

    # Start scan in background thread
    thread = threading.Thread(
        target=_run_scan_background,
        args=(session_id, location, scan_type, price_min, price_max, skip_flood, use_zillow, q,
              lava_mode, lava_min_profit, lava_scope, lava_state),
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


# ── Lava Search: Nationwide Multi-City Scan ────────────────────────────


def _run_nationwide_lava_scan(
    session_id: str,
    scan_type: str,
    price_min: int | None,
    price_max: int | None,
    skip_flood: bool,
    use_zillow: bool,
    progress_q: queue.Queue,
    lava_min_profit: int = 300,
    lava_state: str = "",
):
    """
    Lava Search nationwide mode: cycle through the top 20 US metro areas
    (optionally filtered to a single state) running the full scan pipeline
    per city. Only lava-quality deals (profit_ratio >= threshold) are
    streamed to the SSE queue.
    """
    from db.database import get_connection, complete_scan_session
    from scrapers.homeharvest_scraper import fetch_listings, normalize_listing
    from scrapers.redfin_scraper import fetch_sold_comps
    from enrichment.brain import classify_property
    from enrichment.comp_engine import calculate_comps
    from enrichment.enricher import enrich_property
    from enrichment.listing_filter import filter_listing
    from scoring.residential_score import score_residential
    from scoring.land_score import score_land
    from scoring.commercial_score import score_commercial
    from config import get_comp_pool_size

    conn = get_connection()
    total_processed = 0
    total_hot = 0
    total_filtered = 0
    cities_completed = 0

    def _update_status(status_dict: dict):
        with _scan_status_lock:
            _scan_status[session_id] = status_dict

    # ── Filter metros by selected state (if any) ────────────────────
    if lava_state:
        _metros = [c for c in TOP_20_METROS if c.endswith(f", {lava_state}")]
        if not _metros:
            logger.warning(f"No metros found for state '{lava_state}', falling back to all")
            _metros = TOP_20_METROS
    else:
        _metros = TOP_20_METROS

    status = _scan_status.get(session_id, {})
    status["status"] = "scanning"
    status["lava_scope"] = "nationwide"
    status["lava_state"] = lava_state if lava_state else "all"
    status["total_cities"] = len(_metros)
    status["cities_completed"] = 0
    status["properties_found"] = 0
    status["hot_leads"] = 0
    _update_status(status)

    for city_idx, city in enumerate(_metros):
        if _cancel_events.get(session_id, threading.Event()).is_set():
            logger.info(f"Nationwide lava scan cancelled after {city_idx} cities")
            break

        status["current_city"] = city
        status["cities_completed"] = city_idx
        status["status"] = f"Scanning {city} ({city_idx + 1}/{len(TOP_20_METROS)})"
        _update_status(status)

        logger.info(f"Nationwide lava: scanning {city} ({city_idx + 1}/{len(TOP_20_METROS)})")

        try:
            property_types = {
                "residential": ["single_family", "mobile"],
                "land": ["land"],
                "commercial": ["multi_family", "apartment", "condos", "townhomes", "duplex_triplex", "farm"],
            }.get(scan_type)

            raw_listings = fetch_listings(
                location=city,
                listing_type="for_sale",
                past_days=90,
                property_type=property_types,
            )

            if not raw_listings:
                logger.info(f"Nationwide lava: no listings in {city}, skipping")
                continue

            listing_count = len(raw_listings)
            comp_limit = get_comp_pool_size(listing_count)

            sold_comps = fetch_sold_comps(
                location=city,
                scan_type=scan_type,
                past_days=180,
                limit=comp_limit,
            )

            if not sold_comps:
                logger.info(f"Nationwide lava: no sold comps in {city}, skipping")
                continue

            # Process each property in this city
            for raw in raw_listings:
                try:
                    if _cancel_events.get(session_id, threading.Event()).is_set():
                        break

                    if raw.get("source") == "zillow":
                        prop = raw
                        prop["scan_session_id"] = session_id
                    else:
                        prop = normalize_listing(raw, source="realtor", scan_session_id=session_id, scan_type=scan_type)

                    list_price = prop.get("list_price") or 0
                    if price_min and list_price < price_min:
                        continue
                    if price_max and list_price > price_max:
                        continue

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

                    filter_result = filter_listing(
                        description=prop.get("listing_description"),
                        list_price=prop.get("list_price"),
                        sqft=prop.get("sqft"),
                        style=prop.get("style"),
                        brain_classification=prop.get("brain_classification"),
                    )
                    if filter_result and filter_result["action"] == "skip":
                        total_filtered += 1
                        continue
                    if filter_result:
                        prop["filter_reason"] = filter_result["reason"]
                        prop["filter_type"] = filter_result["filter_type"]

                    prop = enrich_property(prop, skip_flood=skip_flood)
                    comp_result = calculate_comps(prop, sold_comps, scan_type=scan_type)
                    prop.update(comp_result)

                    if scan_type == "residential":
                        score_result = score_residential(prop)
                    elif scan_type == "land":
                        score_result = score_land(prop)
                    else:
                        score_result = score_commercial(prop)

                    prop["score_total"] = score_result["total"]
                    prop["lead_tier"] = score_result["tier"]

                    # ── Lava filter ──────────────────────────────────
                    comp_median = prop.get("comp_median_price") or 0
                    lava_list_price = prop.get("list_price") or 0
                    if comp_median > 0 and lava_list_price > 0:
                        profit_ratio = comp_median / lava_list_price
                        min_ratio = lava_min_profit / 100.0
                        prop["lava_profit_pct"] = round((profit_ratio - 1.0) * 100, 1)
                        prop["lava_profit_ratio"] = round(profit_ratio, 2)
                        if profit_ratio < min_ratio:
                            continue
                    else:
                        continue  # No comp data — skip

                    prop["lava_city"] = city
                    prop["scan_type"] = scan_type

                    from db.database import upsert_property
                    upsert_property(conn, prop)
                    progress_q.put(dict(prop))

                    if prop["lead_tier"] == "HOT":
                        total_hot += 1
                    total_processed += 1

                except Exception as e:
                    logger.debug(f"Nationwide lava: skip listing: {e}")
                    continue

            cities_completed = city_idx + 1
            status["cities_completed"] = cities_completed
            status["properties_found"] = total_processed
            status["hot_leads"] = total_hot
            _update_status(status)

        except Exception as e:
            logger.warning(f"Nationwide lava: error scanning {city}: {e}")
            continue

    # Complete the session
    complete_scan_session(conn, session_id, total_processed, total_hot)
    conn.commit()

    status["status"] = "completed"
    status["properties_found"] = total_processed
    status["hot_leads"] = total_hot
    status["cities_completed"] = cities_completed
    status["total_cities"] = len(TOP_20_METROS)
    status["lava_total_cities"] = cities_completed
    status["completed_at"] = datetime.utcnow().isoformat()
    _update_status(status)
    progress_q.put(None)
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
    lava_mode: bool = False,
    lava_min_profit: int = 300,
    lava_scope: str = "city",
    lava_state: str = "",
):
    """Run the scan pipeline in a background thread, pushing results to the queue."""
    # ── Lava mode: nationwide = cycle through top 20 metros ─────────
    if lava_mode and lava_scope == "nationwide":
        _run_nationwide_lava_scan(session_id, scan_type, price_min, price_max,
                                   skip_flood, use_zillow, progress_q,
                                   lava_min_profit, lava_state)
        return

    # Lava mode state scope handled by location resolver mapping to anchor city
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
    from config import SOLD_COMPS_BASE, SOLD_COMPS_PER_LISTING, SOLD_COMPS_MAX, get_comp_pool_size

    # ── Resolve loose location terms ────────────────────────────────
    from utils.location_resolver import resolve_with_details as _resolve_loc
    loc_info = _resolve_loc(location)
    search_location = loc_info["resolved"]
    if loc_info["changed"]:
        logger.info(f"Location resolved: '{loc_info['original']}' → '{loc_info['resolved']}' "
                     f"(method: {loc_info['method']})")

    conn = get_connection()

    # ── Persist the resolved location into the DB session ────────────
    if loc_info["changed"]:
        try:
            import json as _json
            existing = conn.execute(
                "SELECT search_params FROM scan_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if existing:
                params = _json.loads(existing["search_params"] or "{}")
                params["search_location"] = loc_info["resolved"]
                params["location_resolution_method"] = loc_info["method"]
                conn.execute(
                    "UPDATE scan_sessions SET search_params = ? WHERE id = ?",
                    (_json.dumps(params), session_id),
                )
                conn.commit()
        except Exception as _exc:
            logger.warning(f"Failed to persist resolved location: {_exc}")
    processed = 0
    hot_count = 0
    filtered_out = 0

    try:
        def _update_status(status_dict: dict):
            """Thread-safe update of scan status."""
            with _scan_status_lock:
                _scan_status[session_id] = status_dict

        status = _scan_status.get(session_id, {})
        # Store resolved location in status for UI display
        if loc_info["changed"]:
            status["original_location"] = loc_info["original"]
            status["resolved_location"] = loc_info["resolved"]

        # Phase 1: Fetch listings first to gauge volume for dynamic comp pool sizing
        property_types = {
            "residential": ["single_family", "mobile"],
            "land": ["land"],
            "commercial": ["multi_family", "apartment", "condos", "townhomes", "duplex_triplex", "farm"],
        }.get(scan_type)

        raw_listings = fetch_listings(
            location=search_location,
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
        # Calculate dynamic comp pool size based on actual listing volume
        listing_count = len(raw_listings)
        comp_limit = get_comp_pool_size(listing_count)

        # Fetch sold comps with dynamic pool size
        status["status"] = "fetching_comps"
        status["listings_found"] = listing_count
        status["comp_limit"] = comp_limit
        _update_status(status)

        sold_comps = fetch_sold_comps(
            location=search_location,
            scan_type=scan_type,
            past_days=180,
            limit=comp_limit,
        )

        status["status"] = "scanning"
        status["comps_found"] = len(sold_comps)
        _update_status(status)

        if use_zillow:
            try:
                from scrapers.zillow_stealth import fetch_zillow_listings
                zillow_listings = fetch_zillow_listings(
                    location=search_location,
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

                # ── Lava Search filter ──────────────────────────────
                lava_passed = True
                if lava_mode:
                    comp_median = prop.get("comp_median_price") or 0
                    list_price = prop.get("list_price") or 0
                    if comp_median > 0 and list_price > 0:
                        profit_ratio = comp_median / list_price
                        min_ratio = lava_min_profit / 100.0
                        prop["lava_profit_pct"] = round((profit_ratio - 1.0) * 100, 1)
                        prop["lava_profit_ratio"] = round(profit_ratio, 2)
                        if profit_ratio < min_ratio:
                            lava_passed = False
                            logger.info(f"Lava filter: {prop.get('address','?')} "
                                         f"ratio={profit_ratio:.2f}x < {min_ratio:.2f}x (min), skipping")
                    else:
                        # No comp data — can't evaluate lava, skip
                        lava_passed = False
                        logger.info(f"Lava filter: {prop.get('address','?')} no comp data, skipping")

                # Add score completeness data
                from scoring.utils import get_score_completeness
                prop["completeness"] = get_score_completeness(prop)

                # ── Lava filter check: skip if not lava-quality ──────
                if not lava_passed:
                    filtered_out += 1
                    continue

                # Save transient fields before DB upsert
                cap_rate_data = prop.pop("cap_rate_data", None)
                completeness_data = prop.pop("completeness", None)
                comp_acreage_matched = prop.pop("comp_acreage_matched", None)

                # Upsert to DB
                upsert_property(conn, prop)

                # Restore transient fields for SSE stream
                if cap_rate_data:
                    prop["cap_rate_data"] = cap_rate_data
                if completeness_data:
                    prop["completeness"] = completeness_data
                if comp_acreage_matched is not None:
                    prop["comp_acreage_matched"] = comp_acreage_matched

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
