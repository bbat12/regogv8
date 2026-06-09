#!/usr/bin/env python3
"""
REGOG — Real Estate Go/No-Go Scanner
CLI entry point with subcommands: scan, leads, report, config.
"""

import argparse
import sys
import logging
import json
from datetime import datetime
from pathlib import Path

# Add parent dir to path for module imports when running as script
sys.path.insert(0, str(Path(__file__).parent))

from config import DB_PATH, SCAN_DEFAULTS
from ui.terminal import (
    console,
    print_banner,
    render_leads_table,
    render_stats_panel,
    render_session_summary,
    render_error,
    render_info,
    render_success,
    confirm_action,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("regog")


def main():
    parser = argparse.ArgumentParser(
        prog="regog",
        description="REGOG — Real Estate Go/No-Go Scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  regog scan residential --location "Phoenix, AZ" --price-max 500000
  regog scan land --location "Texas" --acres-min 5
  regog scan commercial --location "Chicago, IL" --type multifamily
  regog leads --tier HOT --limit 20
  regog report --session-id abc123
  regog config --show
  regog init
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ─── init ──────────────────────────────────────────────────────────────
    subparsers.add_parser("init", help="Initialize the database")

    # ─── scan ──────────────────────────────────────────────────────────────
    scan_parser = subparsers.add_parser("scan", help="Run a property scan")
    scan_parser.add_argument("scan_type", choices=["residential", "land", "commercial"], help="Type of property to scan")
    scan_parser.add_argument("--location", required=True, help='City, "City, State", or ZIP code')
    scan_parser.add_argument("--zip", help="ZIP code(s), comma-separated")
    scan_parser.add_argument("--price-min", type=int, help="Minimum listing price")
    scan_parser.add_argument("--price-max", type=int, help="Maximum listing price")
    scan_parser.add_argument("--radius", type=int, help="Search radius in miles")
    scan_parser.add_argument("--beds-min", type=int, help="Minimum bedrooms (residential)")
    scan_parser.add_argument("--sqft-min", type=int, help="Minimum square footage")
    scan_parser.add_argument("--acres-min", type=float, help="Minimum acres (land)")
    scan_parser.add_argument("--acres-max", type=float, help="Maximum acres (land)")
    scan_parser.add_argument("--type", dest="commercial_type", help="Commercial subtype: multifamily, hotel, industrial, office, retail")
    scan_parser.add_argument("--dom-max", type=int, help="Maximum days on market")
    scan_parser.add_argument("--score-min", type=float, help="Minimum score to show")
    scan_parser.add_argument("--tier", choices=["HOT", "WARM", "NEUTRAL", "RISKY", "SKIP"], help="Filter by lead tier")
    scan_parser.add_argument("--fresh", type=int, help="Only listings added in last N days")
    scan_parser.add_argument("--skip-flood", action="store_true", help="Skip FEMA flood zone lookup (faster scans)")
    scan_parser.add_argument("--use-zillow", action="store_true", help="Also scrape Zillow as a secondary listing source")
    scan_parser.add_argument("--zillow-pages", type=int, default=2, help="Zillow search result pages to scrape (default 2, ~40 listings/page)")
    scan_parser.add_argument("--past-days", type=int, default=SCAN_DEFAULTS["past_days"], help=f"Look back period (default {SCAN_DEFAULTS['past_days']})")
    scan_parser.add_argument("--limit", type=int, default=50, help="Max results (default 50)")
    scan_parser.add_argument("--use-redfin", action="store_true", help="Also scrape Redfin via browser as a secondary listing source")
    scan_parser.add_argument("--use-craigslist", action="store_true", help="Also scrape Craigslist for FSBO/motivated seller listings")

    # ─── leads ─────────────────────────────────────────────────────────────
    leads_parser = subparsers.add_parser("leads", help="Show leads")
    leads_parser.add_argument("--tier", choices=["HOT", "WARM", "NEUTRAL", "RISKY", "SKIP"], help="Filter by tier")
    leads_parser.add_argument("--limit", type=int, default=20, help="Max results (default 20)")
    leads_parser.add_argument("--score-min", type=float, help="Minimum score")
    leads_parser.add_argument("--location", help="City or ZIP filter")

    # ─── report ────────────────────────────────────────────────────────────
    report_parser = subparsers.add_parser("report", help="Generate HTML report")
    report_parser.add_argument("--session-id", help="Scan session ID (default: latest)")
    report_parser.add_argument("--output", default="regog_report.html", help="Output file path")
    report_parser.add_argument("--limit", type=int, default=100, help="Max properties in report")

    # ─── config ────────────────────────────────────────────────────────────
    config_parser = subparsers.add_parser("config", help="View or set configuration")
    config_parser.add_argument("--show", action="store_true", help="Show current config")
    config_parser.add_argument("--set", metavar="KEY=VALUE", help="Set a config value (e.g., comp_radius_miles=5)")

    # ─── schedule ──────────────────────────────────────────────────────────
    schedule_parser = subparsers.add_parser("schedule", help="Schedule recurring scans")
    schedule_parser.add_argument("--location", required=True, help="Location to scan")
    schedule_parser.add_argument("--type", dest="scan_type", default="residential", choices=["residential", "land", "commercial"], help="Scan type")
    schedule_parser.add_argument("--interval", type=int, default=24, help="Hours between scans (default 24)")

    args = parser.parse_args()

    if not args.command:
        print_banner()
        parser.print_help()
        return

    # Route commands
    if args.command == "init":
        cmd_init()
    elif args.command == "scan":
        cmd_scan(args)
    elif args.command == "leads":
        cmd_leads(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "config":
        cmd_config(args)
    elif args.command == "schedule":
        cmd_schedule(args)
    else:
        parser.print_help()


# ─── Command Implementations ──────────────────────────────────────────────


def cmd_init():
    """Initialize the database."""
    from db.database import init_db
    try:
        init_db()
        render_success(f"Database initialized at {DB_PATH}")
    except Exception as e:
        render_error(f"Failed to initialize database: {e}")
        sys.exit(1)


def cmd_scan(args):
    """Run a property scan."""
    from db.database import get_connection, create_scan_session, complete_scan_session, upsert_property
    from scrapers.homeharvest_scraper import fetch_listings, normalize_listing
    from scrapers.redfin_scraper import fetch_sold_comps
    from enrichment.brain import classify_property
    from enrichment.comp_engine import calculate_comps
    from enrichment.enricher import enrich_property
    from enrichment.listing_filter import filter_listing
    from scoring.residential_score import score_residential
    from scoring.land_score import score_land
    from scoring.commercial_score import score_commercial
    from ui.terminal import render_leads_table

    print_banner()
    render_info(f"Starting {args.scan_type} scan of '{args.location}'...")

    search_params = {
        "location": args.location,
        "scan_type": args.scan_type,
        "price_min": args.price_min,
        "price_max": args.price_max,
        "zip": args.zip,
        "radius": args.radius,
    }

    # DB setup
    conn = get_connection()
    session_id = create_scan_session(conn, args.scan_type, search_params)

    try:
        # 0. Fetch sold comps first (used for price deviation scoring)
        render_info("Fetching sold comps for location...")
        sold_comps = fetch_sold_comps(
            location=args.location,
            scan_type=args.scan_type,
            past_days=180,
            limit=200,
        )
        render_success(f"Loaded {len(sold_comps)} sold comps for comparison")

        # 1. Fetch listings
        render_info("Fetching listings from Realtor.com...")

        # Property type mapping for HomeHarvest API
        # HomeHarvest accepts: single_family, multi_family, condos, townhomes, condo_townhome_rowhome_coop,
        #                      duplex_triplex, farm, land, mobile, apartment
        property_types = {
            "residential": ["single_family", "mobile"],  # Single family + mobile homes
            "land": ["land"],                              # Vacant land only
            "commercial": ["multi_family", "apartment", "condos", "townhomes", "duplex_triplex", "farm"],  # Everything else except mobile
        }.get(args.scan_type)

        raw_listings = fetch_listings(
            location=args.location,
            listing_type="for_sale",
            past_days=args.past_days,
            property_type=property_types,
        )

        if not raw_listings:
            render_info("No listings found. Try a different location or broader search criteria.")
            complete_scan_session(conn, session_id, 0, 0)
            conn.close()
            return

        render_success(f"Found {len(raw_listings)} raw listings from Realtor.com")

        # 1b. Optionally fetch additional listings from secondary sources
        secondary_sources = []

        if args.use_zillow:
            render_info("Fetching listings from Zillow (stealth browser)...")
            try:
                from scrapers.zillow_stealth import fetch_zillow_listings
                zillow_listings = fetch_zillow_listings(
                    location=args.location,
                    listing_type="for_sale",
                    max_pages=args.zillow_pages,
                )
                if zillow_listings:
                    render_success(f"Found {len(zillow_listings)} listings from Zillow")
                    secondary_sources.append(zillow_listings)
            except Exception as e:
                logger.warning(f"Zillow scrape failed: {e}")
                render_info("Zillow scraping skipped due to error")

        if args.use_redfin:
            render_info("Fetching listings from Redfin (browser)...")
            try:
                from scrapers.redfin_playwright import scrape_redfin_listings
                redfin_listings = scrape_redfin_listings(
                    location=args.location,
                    price_max=args.price_max,
                    scan_type=args.scan_type,
                    limit=50,
                )
                if redfin_listings:
                    render_success(f"Found {len(redfin_listings)} listings from Redfin")
                    secondary_sources.append(redfin_listings)
                else:
                    render_info("No Redfin listings returned")
            except Exception as e:
                logger.warning(f"Redfin scrape failed: {e}")
                render_info("Redfin scraping skipped due to error")

        if args.use_craigslist:
            render_info("Fetching listings from Craigslist...")
            try:
                from scrapers.craigslist_scraper import scrape_craigslist_housing
                cl_listings = scrape_craigslist_housing(
                    location=args.location,
                    price_max=args.price_max,
                    scan_type=args.scan_type,
                    limit=50,
                )
                if cl_listings:
                    render_success(f"Found {len(cl_listings)} listings from Craigslist")
                    secondary_sources.append(cl_listings)
                else:
                    render_info("No Craigslist listings returned")
            except Exception as e:
                logger.warning(f"Craigslist scrape failed: {e}")
                render_info("Craigslist scraping skipped due to error")            # Deduplicate all sources
        if secondary_sources:
            from utils.dedup import merge_and_deduplicate
            raw_listings = merge_and_deduplicate(raw_listings, secondary_sources[0])

        if not raw_listings:
            render_info("No listings found from any source. Try a different location or broader search criteria.")
            complete_scan_session(conn, session_id, 0, 0)
            conn.close()
            return

        # 2. Normalize, classify, score each property
        processed = 0
        hot_count = 0

        for raw in raw_listings:
            try:
                # Normalize (skip for Zillow listings which are already normalized)
                if raw.get("source") == "zillow":
                    prop = raw
                    prop["scan_session_id"] = session_id
                else:
                    prop = normalize_listing(raw, source="realtor", scan_session_id=session_id, scan_type=args.scan_type)

                # Brain classification (keyword-based)
                brain = classify_property(
                    address=prop.get("address", ""),
                    scan_type=args.scan_type,
                    list_price=prop.get("list_price"),
                    sqft=prop.get("sqft"),
                    year_built=prop.get("year_built"),
                    days_on_market=prop.get("days_on_market"),
                    description=prop.get("listing_description"),
                )
                prop["brain_classification"] = brain["classification"]
                prop["brain_red_flags"] = brain["red_flags"]  # list — DB layer serializes to JSON
                prop["brain_green_flags"] = brain["green_flags"]  # list — DB layer serializes to JSON
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
                        continue
                    prop["filter_reason"] = filter_result["reason"]
                    prop["filter_type"] = filter_result["filter_type"]

                # Phase 3: Enrich with assessor data and optional FEMA flood zone
                prop = enrich_property(prop, skip_flood=args.skip_flood)

                # Calculate comps against sold data for this property
                comp_result = calculate_comps(prop, sold_comps, scan_type=args.scan_type)
                prop.update(comp_result)

                # Score
                if args.scan_type == "residential":
                    score_result = score_residential(prop)
                elif args.scan_type == "land":
                    score_result = score_land(prop)
                else:
                    score_result = score_commercial(prop)

                prop["score_total"] = score_result["total"]
                prop["score_price_deviation"] = score_result["scores"].get("price_deviation", 0)
                prop["score_dom_signal"] = score_result["scores"].get("dom_signal", 0)
                prop["score_assessor_gap"] = score_result["scores"].get("assessor_gap", 0)
                prop["score_condition"] = score_result["scores"].get("condition", 0)
                prop["score_flood_penalty"] = score_result["scores"].get("flood_penalty", 0)
                prop["lead_tier"] = score_result["tier"]
                prop["data_confidence"] = score_result.get("data_confidence", "HIGH")

                # Upsert to DB
                upsert_property(conn, prop)

                if prop.get("lead_tier") == "HOT":
                    hot_count += 1
                processed += 1

            except Exception as e:
                logger.warning(f"Error processing listing: {e}")
                continue

        # Complete session
        complete_scan_session(conn, session_id, processed, hot_count)
        conn.commit()

        # Show results
        session_props = get_session_properties_sorted(conn, session_id)
        render_session_summary(session_id, args.scan_type, args.location, processed, hot_count)

        if session_props:
            table = render_leads_table(session_props, title=f"Results: {args.location}")
            console.print(table)
        else:
            render_info("No properties scored. Try adjusting search parameters.")

    except KeyboardInterrupt:
        render_info("\nScan interrupted by user")
        complete_scan_session(conn, session_id, 0, 0)
        conn.commit()
    except Exception as e:
        render_error(f"Scan failed: {e}")
        logger.exception("Scan error")
        complete_scan_session(conn, session_id, 0, 0)
        conn.commit()
    finally:
        conn.close()


def get_session_properties_sorted(conn, session_id):
    """Get properties for a session, sorted by score descending."""
    from db.database import get_session_properties
    return get_session_properties(conn, session_id)


def cmd_leads(args):
    """Show leads from the database."""
    from db.database import get_connection, search_properties, get_leads_by_tier

    conn = get_connection()

    try:
        if args.tier:
            props = get_leads_by_tier(conn, args.tier, limit=args.limit)
        else:
            props = search_properties(
                conn,
                tier=args.tier,
                score_min=args.score_min,
                limit=args.limit,
            )

        if not props:
            render_info("No leads found. Run a scan first with 'regog scan'")
            return

        table = render_leads_table(props, title=f"Leads ({len(props)})")
        console.print(table)
        render_info(f"Showing {len(props)} properties")

    finally:
        conn.close()


def cmd_report(args):
    """Generate an HTML report."""
    from db.database import get_connection, get_session_properties
    from ui.report_generator import generate_report
    import json

    conn = get_connection()

    try:
        # Find session
        if args.session_id:
            session_id = args.session_id
        else:
            # Get latest session
            row = conn.execute(
                "SELECT id, scan_type, search_params FROM scan_sessions ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                render_error("No scan sessions found. Run a scan first.")
                return
            session_id = row["id"]
            render_info(f"Using latest session: {session_id}")

        # Get session info
        session_row = conn.execute(
            "SELECT * FROM scan_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not session_row:
            render_error(f"Session '{session_id}' not found")
            return

        # Get properties
        props = get_session_properties(conn, session_id)
        if not props:
            render_info("No properties found for this session")
            return

        # Limit
        if args.limit and len(props) > args.limit:
            props = props[:args.limit]

        session_info = dict(session_row)
        try:
            session_info["search_params"] = json.loads(session_info.get("search_params") or "{}")
        except (json.JSONDecodeError, TypeError):
            session_info["search_params"] = {}

        output_path = generate_report(props, session_info, output_path=args.output)
        render_success(f"Report generated: {output_path}")

    finally:
        conn.close()


def cmd_config(args):
    """View or set configuration."""
    if args.show:
        import config as cfg
        print_banner()
        console.print("[bold white]Current Configuration[/bold white]")
        console.print(f"[dim]DB_PATH:[/dim] {cfg.DB_PATH}")
        console.print(f"[dim]Residential Weights:[/dim] {cfg.RESIDENTIAL_WEIGHTS}")
        console.print(f"[dim]Land Weights:[/dim] {cfg.LAND_WEIGHTS}")
        console.print(f"[dim]Commercial Weights:[/dim] {cfg.COMMERCIAL_WEIGHTS}")
        console.print(f"[dim]Tier Thresholds:[/dim] {cfg.TIER_THRESHOLDS}")
        console.print(f"[dim]Comp Defaults:[/dim] {cfg.COMP_DEFAULTS}")
        console.print(f"[dim]Rate Limits:[/dim] {cfg.RATE_LIMITS}")
    elif args.set:
        from utils.config_store import set_config, list_config, load_config
        # Parse KEY=VALUE
        if "=" not in args.set:
            render_error("Use KEY=VALUE format, e.g. --set comp_radius_miles=5")
            return
        key, val_str = args.set.split("=", 1)
        key = key.strip()
        val_str = val_str.strip()
        # Try to parse as int, float, bool, or keep as string
        try:
            if val_str.lower() in ("true", "false"):
                val = val_str.lower() == "true"
            elif "." in val_str:
                val = float(val_str)
            else:
                val = int(val_str)
        except ValueError:
            val = val_str
        set_config(key, val)
        render_success(f"Config set: {key} = {val!r}")
        # Show updated config
        config_list = list_config()
        if config_list:
            console.print("[bold white]Active config overrides:[/bold white]")
            for k, v in config_list.items():
                console.print(f"  [dim]{k}:[/dim] {v!r}")
    else:
        console.print("Use [bold]--show[/bold] to view config or [bold]--set KEY=VALUE[/bold] to set a value")


def cmd_schedule(args):
    """Schedule recurring scans."""
    from scheduler.scan_scheduler import create_scheduler, schedule_scan

    render_info(f"Scheduling {args.scan_type} scan of '{args.location}' every {args.interval}h...")

    scheduler = create_scheduler()
    if not scheduler:
        render_error("APScheduler not installed. Install with: pip install apscheduler")
        return

    # Define the scan function
    def run_scheduled_scan(location: str, scan_type: str):
        """Run a scan (called by scheduler)."""
        from db.database import get_connection, create_scan_session, complete_scan_session
        from scrapers.homeharvest_scraper import fetch_listings, normalize_listing
        from scrapers.redfin_scraper import fetch_sold_comps
        from enrichment.brain import classify_property
        from enrichment.comp_engine import calculate_comps
        from enrichment.enricher import enrich_property
        from scoring.residential_score import score_residential
        from scoring.land_score import score_land
        from scoring.commercial_score import score_commercial
        import json

        conn = get_connection()
        session_id = create_scan_session(conn, scan_type, {"location": location, "scheduled": True})

        try:
            # Fetch sold comps for comparison scoring
            scheduled_sold_comps = fetch_sold_comps(
                location=location,
                scan_type=scan_type,
                past_days=180,
                limit=200,
            )
            logger.info(f"Loaded {len(scheduled_sold_comps)} sold comps for scheduled scan")

            property_types = {
                "residential": ["single_family", "mobile"],
                "commercial": ["multi_family", "apartment", "condos", "townhomes", "duplex_triplex", "farm"],
            }.get(scan_type) if scan_type != "land" else ["land"]
            raw = fetch_listings(location=location, listing_type="for_sale", property_type=property_types)
            processed = 0
            hot = 0
            for r in raw:
                prop = normalize_listing(r, source="realtor", scan_session_id=session_id, scan_type=scan_type)
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
                prop["brain_red_flags"] = brain["red_flags"]  # list — DB layer serializes
                prop["brain_green_flags"] = brain["green_flags"]  # list — DB layer serializes
                prop["brain_seller_motivation"] = brain["seller_motivation"]

                # Listing filter: catch auctions, bait prices, burned/demolished
                from enrichment.listing_filter import filter_listing
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
                        continue
                    prop["filter_reason"] = filter_result["reason"]
                    prop["filter_type"] = filter_result["filter_type"]

                # Phase 3: Enrich with assessor data (skip flood for speed in scheduled scans)
                prop = enrich_property(prop, skip_flood=True)

                comps = calculate_comps(prop, scheduled_sold_comps, scan_type=scan_type)
                prop.update(comps)

                if scan_type == "residential":
                    score_result = score_residential(prop)
                elif scan_type == "land":
                    score_result = score_land(prop)
                else:
                    score_result = score_commercial(prop)
                prop["score_total"] = score_result["total"]
                prop["lead_tier"] = score_result["tier"]
                prop["data_confidence"] = score_result.get("data_confidence", "HIGH")

                from db.database import upsert_property
                upsert_property(conn, prop)

                if prop.get("lead_tier") == "HOT":
                    hot += 1
                processed += 1

            complete_scan_session(conn, session_id, processed, hot)
            conn.commit()
            logger.info(f"Scheduled scan complete: {processed} properties, {hot} HOT leads")

        except Exception as e:
            logger.error(f"Scheduled scan error: {e}")
            complete_scan_session(conn, session_id, 0, 0)
            conn.commit()
        finally:
            conn.close()

    schedule_scan(
        scheduler,
        run_scheduled_scan,
        location=args.location,
        scan_type=args.scan_type,
        interval_hours=args.interval,
    )

    scheduler.start()
    render_success(f"Scheduled: {args.scan_type} scan of '{args.location}' every {args.interval}h")
    render_info("Scheduler running in background. Press Ctrl+C to stop.")

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        render_info("\nScheduler stopped")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
