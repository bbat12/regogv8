# REGOG V5 — Complete Rebuild Guide

> **Purpose:** Real Estate Go/No-Go Scanner. Scrapes Realtor.com (via HomeHarvest) for active + sold listings, classifies properties via keyword matching, finds comparable sales via 2D expansion search (radius + time), scores each property 0-100 across 5-6 signals, and serves results via a dark-themed Flask web app with streaming SSE updates.
>
> **A new CLI agent with ZERO knowledge of this project should be able to rebuild REGOG from this document alone.**

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Setup & Installation](#2-setup--installation)
3. [Configuration (config.py)](#3-configuration-configpy)
4. [Database (db/)](#4-database-db)
5. [Entry Points & Import Setup](#5-entry-points--import-setup)
6. [Scan Pipeline](#6-scan-pipeline)
7. [HomeHarvest Scraper](#7-homeharvest-scraper)
8. [Redfin Scraper (Sold Comps)](#8-redfin-scraper-sold-comps)
9. [Zillow Stealth Scraper](#9-zillow-stealth-scraper)
10. [Craigslist Scraper](#10-craigslist-scraper)
11. [Redfin Playwright Scraper](#11-redfin-playwright-scraper)
12. [FEMA Flood Zone Scraper](#12-fema-flood-zone-scraper)
13. [Brain Classifier](#13-brain-classifier)
14. [Listing Filter](#14-listing-filter)
15. [Comp Engine (2D Expansion)](#15-comp-engine-2d-expansion)
16. [Enricher](#16-enricher)
17. [Scoring Modules](#17-scoring-modules)
18. [Scoring Utilities](#18-scoring-utilities)
19. [Property Type Detection](#19-property-type-detection)
20. [Market Density](#20-market-density)
21. [Web App Backend (web/app.py)](#21-web-app-backend-webapppy)
22. [Web Frontend (web/static/index.html)](#22-web-frontend-webstaticindexhtml)
23. [CLI (main.py)](#23-cli-mainpy)
24. [Scheduler](#24-scheduler)
25. [Rate Limiter](#25-rate-limiter)
26. [Tests](#26-tests)
27. [Known Issues & Edge Cases](#27-known-issues--edge-cases)
28. [Quick Start (From Scratch)](#28-quick-start-from-scratch)
29. [Architecture Diagram](#29-architecture-diagram)

---

## 1. Project Structure

```
REGOG_V5_REBUILD.md          <-- This file
serve_report.py              <-- Entry point: runs Flask web app on port 8080
regog.db                     <-- SQLite database (auto-created in project root)
regog_config.json            <-- Persistent config overrides (auto-created next to DB)
regog_report.html            <-- Generated HTML report output
regog/
  __init__.py                <-- Empty (marks package)
  requirements.txt           <-- Python dependencies
  config.py                  <-- ALL thresholds, weights, settings in one file
  main.py                    <-- CLI entry point (argparse, subcommands)

  db/
    __init__.py              <-- Empty
    schema.sql               <-- Full CREATE TABLE statements
    database.py              <-- SQLite connection, init, migrations, CRUD

  scrapers/
    __init__.py              <-- Empty
    homeharvest_scraper.py   <-- Fetches active listings via HomeHarvest library
    redfin_scraper.py        <-- Fetches SOLD comps via HomeHarvest (listing_type="sold")
    zillow_stealth.py        <-- Playwright-based Zillow scraper with anti-bot stealth
    redfin_playwright.py     <-- Playwright-based Redfin browser scraper (supplemental)
    craigslist_scraper.py    <-- HTTPX + BeautifulSoup Craigslist FSBO scraper
    fema_scraper.py          <-- FEMA flood zone lookup by lat/lon (free ArcGIS API)
    assessor_scraper.py      <-- Assessor/valuation enrichment + county registry
    permit_scraper.py        <-- Permit risk signals from listing description + county portals

  enrichment/
    __init__.py              <-- Empty
    brain.py                 <-- Keyword-based property classifier (no LLM)
    comp_engine.py           <-- Comparable sales engine (2D expansion: radius × time)
    enricher.py              <-- Orchestrates enrichments (FEMA, assessor, permits)
    listing_filter.py        <-- Filters out auction bait, burned, demolition
    geocoder.py              <-- DEAD CODE — Nominatim geocoder, never called

  scoring/
    __init__.py              <-- Empty
    utils.py                 <-- Shared: tier assignment, comp fallback, confidence cap, variance penalty
    residential_score.py     <-- 0-100 scoring for single-family homes
    land_score.py            <-- 0-100 scoring for vacant land
    commercial_score.py      <-- 0-100 scoring for commercial properties

  scheduler/
    __init__.py              <-- Empty
    scan_scheduler.py        <-- APScheduler wrapper for recurring scans

  ui/
    __init__.py              <-- Empty
    terminal.py              <-- Rich console output (tables, panels)
    report_generator.py      <-- Jinja2 HTML report generator
    templates/
      report.html.j2         <-- HTML report template

  utils/
    __init__.py              <-- Empty
    property_type.py         <-- Maps styles to residential/land/commercial categories
    density.py               <-- ZIP-based urban/suburban/rural classification
    rate_limiter.py          <-- Rate limiting for scrapers (per-source, jitter, backoff)
    config_store.py          <-- Persistent config overrides (JSON file)
    dedup.py                 <-- Cross-source address-normalized deduplication

web/
  __init__.py                <-- Just a comment: "# REGOG Web App"
  app.py                     <-- Flask app with REST API + SSE streaming + background scan thread
  static/
    index.html               <-- Single-page dark theme UI (all CSS + JS inline)

tests/
  __init__.py                <-- Empty
  conftest.py                <-- Shared pytest fixtures (5 fixtures)
  test_residential_score.py  <-- 88+ tests covering all scoring components
  test_land_score.py         <-- Land scoring tests
  test_utils.py              <-- Tier assignment + flag parsing tests
  test_permit_scraper.py     <-- Permit signal tests

README.md                    <-- Project README (minimal)
```

---

## 2. Setup & Installation

```bash
# Python 3.11+ required
cd /workspaces/REgog
pip install -r regog/requirements.txt

# Install Playwright for optional Zillow/Redfin browser scraping
playwright install chromium

# Run database init (creates regog.db with schema + migrations)
python3 -c "from db.database import init_db; init_db()"

# Start the web app
python3 serve_report.py
# Opens on http://localhost:8080

# Or use CLI:
python3 regog/main.py scan residential --location "Dallas, TX" --price-max 400000
python3 regog/main.py leads --tier HOT
```

### requirements.txt

```
homeharvest>=0.8.0
beautifulsoup4>=4.12.0
httpx>=0.25.0
lxml>=4.9.0
aiosqlite>=0.19.0
sqlite-utils>=3.36
rich>=13.0.0
geopy>=2.3.0
apscheduler>=3.10.0
jinja2>=3.1.0
playwright>=1.40.0
# playwright-stealth>=1.0.6  # Optional — Zillow scraper degrades gracefully without it
```

---

## 3. Configuration (config.py)

All tunable parameters live in ONE file: `regog/config.py`.

### Database

```python
from pathlib import Path
DB_PATH = str(Path(__file__).parent.parent / "regog.db")  # ABSOLUTE path — critical!
```

### Scoring Weights

```python
RESIDENTIAL_WEIGHTS = {
    "price_deviation": 0.40,   # How far below median comp price
    "dom_signal": 0.15,        # Days on market anomaly
    "assessor_gap": 0.20,      # Listed vs assessed value gap
    "condition": 0.15,         # Brain classification
    "flood_penalty": 0.10,     # FEMA zone deduction
}

LAND_WEIGHTS = {
    "price_per_acre_deviation": 0.40,
    "zoning_bonus": 0.20,
    "road_access_bonus": 0.10,
    "utilities_bonus": 0.10,
    "acreage_premium": 0.10,
    "flood_penalty": 0.10,
}

COMMERCIAL_WEIGHTS = {
    "price_deviation": 0.35,
    "assessor_gap": 0.25,
    "cap_rate_estimate": 0.20,
    "condition": 0.10,
    "flood_penalty": 0.10,
}
```

### Lead Tiers

```python
TIER_THRESHOLDS = {"HOT": 70, "WARM": 50, "NEUTRAL": 35, "RISKY": 20, "SKIP": 0}
```

### Comp Engine

```python
MIN_COMPS_REQUIRED = 5  # Minimum comps before accepting — expanded search tries harder to find 5+
COMP_LOOKBACK_TIERS = [180, 270, 365, 540, 730]  # 2 years max lookback
COMP_STALENESS_PENALTY = 0.15  # Applied when lookback > 365d
COMP_CONFIDENCE_HIGH = 0.80
COMP_CONFIDENCE_MEDIUM = 0.50
COMP_CONFIDENCE_LOW = 0.00
```

### Comp Radii (miles, 3 tiers per density per category)

```python
COMP_RADII = {
    "residential": {
        "urban":    [0.25, 0.50, 0.75],
        "suburban": [0.50, 1.00, 1.50],
        "rural":    [2.00, 5.00, 10.0],
    },
    "land": {
        "urban":    [0.50, 1.00, 2.00],
        "suburban": [1.00, 3.00, 5.00],
        "rural":    [5.00, 10.0, 20.0],
    },
    "commercial": {
        "urban":    [0.50, 1.00, 1.50],
        "suburban": [1.00, 2.00, 3.00],
        "rural":    [3.00, 7.00, 15.0],
    },
}
```

### Comp Defaults

```python
COMP_DEFAULTS = {
    "radius_miles": 3,
    "min_comps_required": 3,
    "max_radius_miles": 10,
    "similar_sqft_pct": 0.30,    # ±30% sqft for residential
    "similar_acres_pct": 0.50,   # ±50% acres for land
    "similar_beds_range": 1,     # ±1 bedroom for comp matching
    "similar_baths_range": 1,    # ±1 bathroom for comp matching
    "sold_months": 12,
}
```

### Scoring Maps

```python
FLOOD_SCORES = {"X": 10, "AE": 3, "A": 4, "VE": 0, None: 8}
CONDITION_SCORES = {"standard": 15, "luxury": 12, "vacant": 10,
                    "distressed": 7, "teardown": 4, "fire_damage": 3}
PERMIT_SCORES = {"low": 3, "unknown": 0, "medium": -2, "high": -5}
DOM_SCORE_BRACKETS = [(30, 15), (90, 10), (180, 5), (365, 2), (float("inf"), 0)]
HIGH_RISE_MIN_STORIES = 5  # CONDOs with >=5 stories reclassified as commercial
```

### Brain Classifier Keywords

See `CLASSIFICATION_KEYWORDS` dict in config.py:
- `distressed`: "as-is", "needs work", "fixer-upper", "deferred maintenance" etc.
- `teardown`: "teardown", "land value", "demolish", "knockdown" etc.
- `fire_damage`: "fire damage", "smoke damage", "burnt", "structure fire" etc.
- `vacant`: "vacant", "abandoned", "boarded up", "vacant lot" etc.
- `luxury`: "luxury", "high-end", "estate", "waterfront", "gourmet kitchen" etc.

Also: `SELLER_MOTIVATION_KEYWORDS` (high/medium), `RED_FLAG_KEYWORDS` (15 items), `GREEN_FLAG_KEYWORDS` (15 items).

### Rate Limits

```python
RATE_LIMITS = {
    "realtor":     {"delay_min": 2,  "delay_max": 5,  "max_per_hour": 200},
    "redfin":      {"delay_min": 1,  "delay_max": 3,  "max_per_hour": 300},
    "zillow":      {"delay_min": 4,  "delay_max": 9,  "max_per_hour": 60},
    "assessor":    {"delay_min": 3,  "delay_max": 8,  "max_per_hour": 100},
    "craigslist":  {"delay_min": 3,  "delay_max": 7,  "max_per_hour": 80},
}
```

### Scan Defaults

```python
SCAN_DEFAULTS = {"past_days": 180}  # Look back window for listings
```

---

## 4. Database (db/)

### schema.sql

Creates 3 tables with indexes. The `properties` table has 65+ columns.

**Key columns on `properties`:**
```
listing_id TEXT PRIMARY KEY, source, scan_type, commercial_subtype,
address, city, state, zip, lat, lon,
list_price, price_per_sqft, price_per_acre, sqft, acres, beds, baths,
year_built, lot_sqft, days_on_market, listing_status, listing_description,
last_sold_price, last_sold_date,
assessed_value, estimated_value, assessed_year,
flood_zone, zoning,
permit_flags (JSON),
brain_classification, brain_red_flags (JSON), brain_green_flags (JSON),
brain_seller_motivation,
comp_median_price, comp_count, comp_radius_miles, comp_price_per_sqft_median,
comp_price_per_acre_median, comp_confidence_label, comp_lookback_used,
comp_staleness_penalty_applied, comp_listings (JSON),
comp_price_range, comp_price_stddev, comp_variance_high,
comp_category, comp_density, comp_tier_used,
stories, primary_photo, property_url, style,
score_total, score_price_deviation, score_dom_signal, score_assessor_gap,
score_condition, score_acreage_value, score_flood_penalty,
lead_tier, price_deviation_pct, data_confidence,
filter_reason, filter_type,
first_seen, last_updated, scan_session_id
```

**`scan_sessions` table:** id, started_at, completed_at, scan_type, search_params (JSON), properties_found, hot_leads_found

**`price_history_tracking` table:** id, listing_id, recorded_at, price, days_on_market

### database.py — Key Functions

- **`init_db()`**: Reads schema.sql, then calls `_run_migrations()` to add columns for new features.
- **`_run_migrations()`**: ALTER TABLE ADD COLUMN IF NOT EXISTS for each new field. Non-destructive. Current migration list covers 20+ columns (estimated_value, county, flood_zone, property_url, style, comp_confidence, data_confidence, comp_listings, comp_radius_used, comp_tier_used, comp_category, comp_density, comp_lookback_used, comp_confidence_label, comp_staleness_penalty_applied, stories, primary_photo, comp_price_range, comp_price_stddev, comp_variance_high, filter_reason, filter_type).
- **`_serialize_value(key, value)`**: Lists/dicts → JSON strings for DB.
- **`_deserialize_row(row)`**: JSON strings → Python objects on read.
- **`create_scan_session(conn, scan_type, search_params)`**: Inserts row, returns session_id (8-char UUID).
- **`complete_scan_session(conn, session_id, props_found, hot_leads)`**: Updates completed_at + counts.
- **`upsert_property(conn, prop)`**: INSERT OR UPDATE based on listing_id. Returns True if new.
- **`get_session_properties(conn, session_id)`**: SELECT * for a session, ordered by score DESC.
- **`get_stats(conn)`**: Aggregate counts (total, hot, warm, sessions, avg_score).
- **`search_properties(conn, ...)`**: Filtered search with all optional params.
- **`get_leads_by_tier(conn, tier, limit)`**: Top properties by tier.

**JSON fields auto-serialized:** `brain_red_flags`, `brain_green_flags`, `price_history`, `permit_flags`, `comp_listings`

**Fields NOT in DB schema (popped before upsert):**
- `property_url` — WAS missing from schema, now IS in schema after migration
- `style` — WAS missing from schema, now IS in schema after migration

Both `main.py` and `web/app.py` historically popped these before calling `upsert_property()`, then restored them for streaming. With the migration adding these columns, this pop/restore pattern should still work but is no longer strictly necessary for those two fields.

---

## 5. Entry Points & Import Setup

### serve_report.py (THE entry point for the web app)

```python
#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "regog"))

from db.database import init_db
init_db()  # Run migrations to ensure schema is up-to-date

from web.app import app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
```

### Import Path Setup (CRITICAL)

Every entry point must add the project root to `sys.path` before any REGOG imports:

- **serve_report.py**: `sys.path.insert(0, os.path.dirname(__file__))` + `sys.path.insert(0, os.path.join(os.path.dirname(__file__), "regog"))`
- **regog/main.py**: `sys.path.insert(0, str(Path(__file__).parent))`
- **web/app.py**: `sys.path.insert(0, str(Path(__file__).parent.parent / "regog"))` + `sys.path.insert(0, str(Path(__file__).parent.parent))`
- **Tests**: `sys.path.insert(0, str(Path(__file__).parent.parent / "regog"))`

### Deferred Imports Pattern (CRITICAL)

Both `main.py` and `web/app.py` import heavy modules **inside functions**, not at module level:

```python
def cmd_scan(args):
    from db.database import get_connection, create_scan_session  # Inside function!
    from scrapers.homeharvest_scraper import fetch_listings
    # ... rest of function
```

**Why:** Because `sys.path` is modified at module level before any function is called. If imports were at the top of the file, they'd execute before `sys.path` is ready, causing `ModuleNotFoundError`.

### All `__init__.py` files must exist

Every subdirectory (`scrapers/`, `db/`, `enrichment/`, `scoring/`, `ui/`, `utils/`, `scheduler/`, `tests/`, `web/`) needs an empty `__init__.py` to be importable as a Python package.

---

## 6. Scan Pipeline

Both the CLI (`main.py`) and the web app (`web/app.py`) follow the same pipeline.

### Pipeline Steps (in order):

```
1. Fetch SOLD comps ────────── redfin_scraper.fetch_sold_comps(location, listing_type="sold")
   (up to 200, once per scan)

2. Fetch ACTIVE listings ───── homeharvest_scraper.fetch_listings(location, listing_type="for_sale")

3. (Optional) Zillow ───────── zillow_stealth.fetch_zillow_listings()  [--use-zillow]
   (Optional) Redfin browser ── redfin_playwright.scrape_redfin_listings()  [--use-redfin]
   (Optional) Craigslist ────── craigslist_scraper.scrape_craigslist_housing()  [--use-craigslist]

4. Deduplicate (if secondary sources used): utils.dedup.merge_and_deduplicate()

5. For each listing:
   a. Normalize ──────────── homeharvest_scraper.normalize_listing(raw_dict → property schema)
   b. Price filter ───────── Skip if outside price_min/price_max
   c. Brain classify ─────── enrichment.brain.classify_property(description → classification)
   d. Listing filter ─────── enrichment.listing_filter.filter_listing(skip/flag auctions, bait, burned)
   e. Enrich ─────────────── enrichment.enricher.enrich_property(FEMA, assessor, permits)
   f. Calculate comps ────── enrichment.comp_engine.calculate_comps(active vs sold, 2D expansion)
   g. Score ──────────────── scoring/*.score_*(property → scores dict + total + tier)
   h. Upsert to DB ────────── database.upsert_property()
   i. Push to SSE stream ──── (web app only) queue → SSE → frontend

6. Complete session ───────── database.complete_scan_session()
```

### Property Type Mapping (for HomeHarvest API)

```python
property_types = {
    "residential": ["single_family", "mobile"],  # Single family + mobile homes
    "land":        ["land"],                     # Vacant land only
    "commercial":  ["multi_family", "apartment", "condos", "townhomes", "duplex_triplex", "farm"],
}.get(scan_type)
```

---

## 7. HomeHarvest Scraper (regog/scrapers/homeharvest_scraper.py)

Uses the `homeharvest` library which scrapes Realtor.com (free, no API key).

### fetch_listings()

```python
fetch_listings(location, listing_type="for_sale", past_days=90, property_type=None)
```

- Calls `homeharvest.scrape_property()` which returns a pandas DataFrame
- Converts to list of dicts via `df.to_dict(orient="records")`
- Returns `[]` if `homeharvest` not installed (graceful fallback)

### normalize_listing(raw, source, scan_session_id, scan_type) → dict

The most critical normalization function. Maps HomeHarvest's varied column names to REGOG's schema.

**The `g(*keys)` helper:** Tries multiple possible column names and returns the first non-None value.

```python
def g(*keys):
    for k in keys:
        v = raw.get(k)
        if v is not None:
            return v
    return None
```

**Key field mappings (each tries multiple key names in order):**

| REGOG Field | HomeHarvest Keys Tried (in order) |
|------------|----------------------------------|
| `listing_id` | `property_id`, `listing_id`, `mls_id`, `id` → fallback: `{source}_{hash(address+price)}` |
| `style` | `style`, `property_type`, `home_type` — **CRITICAL for comp matching** |
| `address` | `full_street_line`, `street`, `address`, `full_address`, `formatted_address` |
| `city` | `city`, `municipality` |
| `state` | `state`, `province` |
| `zip` | `zip`, `zip_code`, `postal_code` |
| `list_price` | `list_price`, `price`, `current_price`, `sold_price` |
| `price_per_sqft` | `price_per_sqft`, `ppsf`, `price_sqft` (or computed from price/sqft) |
| `sqft` | `sqft`, `square_feet`, `sq_ft`, `living_area`, `building_area` |
| `beds` | `beds`, `bedrooms`, `baths_full`, `bathrooms_full` |
| `baths` | `full_baths`, `baths`, `bathrooms`, `bathrooms_total` |
| `days_on_market` | `days_on_market`, `dom`, `days_on_mls`, `listing_age` |
| `property_url` | `property_url`, `rdc_web_url`, `href`, `url` |
| `last_sold_price` | `last_sold_price`, `sold_price` |
| `estimated_value` | `estimated_value`, `value`, `zestimate`, `avm_value` |
| `assessed_value` | `assessed_value`, `tax_assessment`, `assessed_valuation` |
| `listing_description` | `description`, `listing_description`, `text`, `remarks`, `public_remarks` |
| `primary_photo` | `primary_photo`, `photo`, `image_url`, `thumbnail_url` |
| `stories` | `stories`, `num_stories`, `floors`, `total_stories` |
| `county` | `county`, `parish` |

**Acres field — extensive fallback chain:**
```python
acres_val = g("acres", "acreage", "lot_size_acres", "lot_acres",
              "total_acres", "parcel_acres", "land_area",
              "land_acres", "area_acres", "gross_acres", "net_acres", "lot_area_acres")
```

**Acres fallback:** If acres is still None, derive from `lot_sqft` / 43560.

**Sqft fallback for land:** If no sqft but has acres, sqft = acres * 43560.

**Lot sqft extensive fallback:**
```python
lot_sqft_val = g("lot_sqft", "lot_size_sqft", "lot_area", "land_sqft", "parcel_sqft",
                  "lot_size", "lot_area_sqft", "land_area_sqft", "lot_square_feet")
```

**Price per acre:** Computed from price/acres if not directly available.

**Helper functions (defined INSIDE normalize_listing, BEFORE use):**
- `num(v)`: Cast to int
- `flt(v)`: Cast to float

### fetch_sold_comps() — STALE

This file has a STALE `fetch_sold_comps(lat, lon, radius_miles, scan_type)` that always returns `[]`. Do NOT use it — the real sold comps function is in `redfin_scraper.py`.

---

## 8. Redfin Scraper / Sold Comps (regog/scrapers/redfin_scraper.py)

Actually uses HomeHarvest under the hood with `listing_type="sold"`. Named "redfin" for historical reasons.

### fetch_sold_comps(location, scan_type, past_days=180, limit=200) → list[dict]

- Fetches sold properties for the entire location (city-level) via HomeHarvest
- Returns up to `limit` sold comps (max 200)
- Each normalized via `normalize_sold_listing()` — NOT `normalize_listing()`
- Gracefully returns `[]` if HomeHarvest not installed

### normalize_sold_listing(raw, scan_type) → dict | None

**Explicitly handles sold-specific column names** — this is a CRITICAL difference from the for-sale normalizer:

| REGOG Field | Sold Column Names Tried |
|------------|------------------------|
| `list_price` | `sold_price`, `last_sold_price`, `close_price`, `sale_price`, `price`, `list_price` |
| `last_sold_date` | `last_sold_date`, `sold_date`, `close_date`, `closing_date` |
| `listing_status` | Force-set to `"sold"` |

- Returns `None` if no `sold_price` (critical field)
- Same acres/sqft derivation logic as the for-sale normalizer
- Handles `property_url` for sold listings too

### fetch_sold_comps_near_coords() — NOT IMPLEMENTED

Returns empty list since HomeHarvest doesn't support coordinate-based queries. City-level fetch is used instead. **This function is defined twice in the file** (both return `[]`).

---

## 9. Zillow Stealth Scraper (regog/scrapers/zillow_stealth.py)

Playwright-based Zillow scraper with anti-bot measures. Optional — activated with `--use-zillow`.

### Anti-bot stack:
1. **`playwright-stealth`** patches browser fingerprint vectors (used if available)
2. **Viewport randomization** — 5 viewport sizes (1280×720 to 1920×1080)
3. **User agent rotation** — 5 modern Chrome/Firefox UAs
4. **Locale/timezone randomization** — en-US, en, en-GB; fixed to America/New_York
5. **Human-like scrolling** — scrolls 300-800px with random pauses (0.5-2s), sometimes scrolls back up
6. **`--disable-blink-features=AutomationControlled`** removes `navigator.webdriver=true`

### Data extraction (3 methods, in order):
1. **Next.js/Apollo JSON** — Extracts embedded JSON from Zillow's page state
2. **DOM parsing fallback** — Queries for `[data-test="property-card"]`
3. Returns deduplicated listings (~40 per page, max_pages configurable)

### fetch_zillow_listings(location, listing_type="for_sale", max_pages=2, headless=True)

**Unique import pattern for rate limiter:**
```python
from utils.rate_limiter import rate_limit as _shared_rate_limit, report_success as _report_success, report_error as _report_error
```
This aliasing pattern is unique to `zillow_stealth.py` and not used in any other scraper.

---

## 10. Craigslist Scraper (regog/scrapers/craigslist_scraper.py)

HTTPX + BeautifulSoup scraper for FSBO/motivated seller listings. No API key needed. Activated with `--use-craigslist`.

### scrape_craigslist_housing(location, price_max, scan_type, limit)

- Maps city name to Craigslist subdomain via `CL_CITY_MAP` (20+ cities)
- Scrapes `reo` (real estate by owner), `rea` (land), or `reb` (commercial) categories
- Parses title, price, beds/baths/sqft from CL post listings
- Returns 0 results if city not in map
- **Rate limited** via shared rate limiter (3-7s delay, 80/hour)

---

## 11. Redfin Playwright Scraper (regog/scrapers/redfin_playwright.py)

Playwright-based Redfin browser scraper. Optional — activated with `--use-redfin`.

### scrape_redfin_listings(location, price_max, scan_type, limit)

Two extraction methods:
1. **Embedded JSON** — Extracts `homeData` from React server props
2. **DOM fallback** — Parses `[data-rf-test-id="abp-homecard"]` elements

Returns 0 if Playwright not installed.

---

## 12. FEMA Flood Zone Scraper (regog/scrapers/fema_scraper.py)

Queries the FEMA National Flood Hazard Layer (NFHL) ArcGIS REST API — **free, no API key required**.

```python
FEMA_ENDPOINT = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
```

### get_flood_zone(lat, lon) → str | None

- Cached in memory by (lat, lon) rounded to 3 decimal places (~100m resolution)
- Rate limited to 1 request/second minimum
- Retry up to 2 times with 2s delay on failure
- 15-second timeout per request
- Returns zone code: `X` (low), `AE`/`A` (high), `VE` (coastal extreme), or `None`

### skip_flood=True behavior

When `skip_flood=True` (web app default):
- `enrich_property(prop, skip_flood=True)` immediately sets `prop["flood_zone"] = None`
- No FEMA API call is made
- Scoring uses `FLOOD_SCORES.get(None, 8)` → 8 pts (slight penalty)
- CLI scans default to NOT skipping (FEMA runs) unless `--skip-flood`

---

## 13. Brain Classifier (regog/enrichment/brain.py)

Keyword-based (no LLM). Scans `listing_description` for signal keywords.

### classify_property(address, scan_type, list_price, sqft, year_built, days_on_market, description) → dict

Returns dict with:
- `classification`: Priority order — fire_damage > teardown > distressed > vacant > luxury > standard > land_only
- `confidence`: Float 0-1, increments by 0.2-0.3 per matched keyword
- `red_flags`: List of matched `RED_FLAG_KEYWORDS` (15 keywords: foundation issues, mold, termites, etc.)
- `green_flags`: List of matched `GREEN_FLAG_KEYWORDS` (15 keywords: renovated, move-in ready, etc.)
- `seller_motivation`: high/medium/low from `SELLER_MOTIVATION_KEYWORDS`
- `motivation_signals`: List of matched keyword phrases
- `estimated_condition`: Maps classification to condition string
- `is_luxury`: Boolean flag
- `notes`: Human-readable summary

### Special case: Land override

If `scan_type == "land"`, classification is forced to `"land_only"` regardless of description.

---

## 14. Listing Filter (regog/enrichment/listing_filter.py)

Filters out junk listings before scoring. Runs AFTER brain classification.

### Filter Chain (order matters — first match wins):

1. **`check_auction`** → `skip` action
   - Keywords: "foreclosure auction", "opening bid", "online auction", "sheriff sale", etc.
   - Also triggers if price < $5K + description mentions auction

2. **`check_bait_price`** → `skip` action
   - Price < $1,000 → always bait
   - Price < $10,000 + residential style + no sqft → bait
   - Keywords: "call for price", "for investment only", "coming soon listing"

3. **`check_burned`** → `flag` action (kept but tagged)
   - Keywords: "burnt", "burned down", "fire damaged", "gutted by fire", "structure fire"
   - Also triggers on brain_classification == "fire_damage"

4. **`check_demolition`** → `flag` action
   - Keywords: "must demolish", "condemned", "uninhabitable", "structural damage"
   - Also triggers on brain_classification == "teardown"

5. **`check_land_masquerade`** → `flag` action
   - Catches SINGLE_FAMILY listings that are actually lots/land
   - Keywords: "buildable lot", "land only", "vacant lot", "raw land"

### Filter output:

```python
{"action": "skip" | "flag", "reason": "...", "filter_type": "auction"|"bait"|"burned"|"demolition"|"land_masquerade"}
```

---

## 15. Comp Engine (regog/enrichment/comp_engine.py)

The core comparable sales engine. Uses **two-dimensional expansion search**: first tries all radius tiers, then expands the lookback window.

### Key Functions:

#### haversine_miles(lat1, lon1, lat2, lon2) → float
Great-circle distance calculation using the Haversine formula. R = 3958.8 miles.

#### get_comp_radii(prop) → [r1, r2, r3]
Looks up density (urban/suburban/rural) + category (residential/land/commercial) → returns 3-tier radius list from `COMP_RADII` in config.

#### _filter_by_style(properties, target_style, scan_type) → list[dict]
**Most important filter — apples-to-apples comparison.**
```python
style_map = {
    "SINGLE_FAMILY": ["SINGLE_FAMILY", "MANUFACTURED", "MOBILE"],
    "MANUFACTURED":  ["MANUFACTURED", "SINGLE_FAMILY"],
    "MOBILE":        ["MOBILE", "SINGLE_FAMILY"],
    "CONDOS":        ["CONDOS"],
    "TOWNHOMES":     ["TOWNHOMES"],
    "MULTI_FAMILY":  ["MULTI_FAMILY", "APARTMENT"],
    "APARTMENT":     ["APARTMENT", "MULTI_FAMILY"],
    "DUPLEX":        ["DUPLEX", "MULTI_FAMILY"],
    "TRIPLEX":       ["TRIPLEX", "MULTI_FAMILY"],
    "QUADPLEX":      ["QUADPLEX", "MULTI_FAMILY"],
    "LAND":          ["LAND"],
    "FARM":          ["FARM", "LAND"],
}
```

#### _filter_by_distance(properties, center_lat, center_lon, radius_miles) → list[dict]
Haversine distance filter. Only includes properties with valid lat/lon.

#### _filter_by_lookback(properties, max_days) → list[dict]
Filters by `last_sold_date` vs today. Properties without dates are included conservatively.

#### find_comps_with_expansion(style_filtered, target_lat, target_lon, radii) → (comps, radius, tier, lookback, staleness)

**THE CRITICAL FUNCTION — 2D Expansion Search**

Expansion order (outer loop = time windows, inner loop = radius tiers):

```
180d/r1 → 180d/r2 → 180d/r3 → 180d/r3×2 → 180d/r3×4 → ... (up to 100mi)
270d/r1 → 270d/r2 → 270d/r3 → 270d/r3×2 → ...
365d/r1 → ...
540d/r1 → ...
730d/r1 → ... (2 years max lookback)
```

- Requires `MIN_COMPS_REQUIRED` (5) comps before accepting
- If 5+ comps found at any radius/lookback combination, returns immediately
- If all combinations exhausted, falls back to 730d / 100mi
- `tier_used`: 1 (r1), 2 (r2), 3 (r3), 5+ (expanded multipliers), 99 (fallback)
- Returns `staleness: bool` indicating lookback > 365d

#### calculate_comps(property_dict, sold_properties, scan_type) → comp_result dict

1. Get density, category, radii from ZIP + style
2. Style-filter sold properties (Step 1)
3. Run 2D expansion search (Step 2)
4. Apply similarity filters if 5+ comps (Step 3):
   - **Sqft filter**: ±30% for residential/commercial (`similar_sqft_pct`)
   - **Bed/bath filter**: ±1 for residential (`similar_beds_range`, `similar_baths_range`)
   - **Acres filter**: ±50% for land (`similar_acres_pct`)
5. Calculate medians (price, $/sqft, $/acre)
6. Calculate `price_deviation_pct = ((target - median) / median) * 100`
7. Calculate variance metrics: `comp_price_range`, `comp_price_stddev`, `comp_variance_high`
8. Calculate confidence via `calculate_comp_confidence()`
9. Build `top_comps` list (top 10 nearest-price comps with address, price, sqft, acres, beds, baths, photo, URL, distance, sold_date)

#### calculate_comp_confidence(comp_count, tier_used, lookback_used) → (confidence_float, label)

Starts at 1.0, subtracts:
- 1 comp: -0.40, 2 comps: -0.35
- tier 2: -0.10, tier 3: -0.20, tier 4+: -0.25
- lookback > 365d: -0.15, > 180d: -0.05

Results: ≥ 0.80 → HIGH, ≥ 0.50 → MEDIUM, < 0.50 → LOW

#### Return dict fields:

```python
{
    "comp_median_price": int,
    "comp_count": int,
    "comp_radius_miles": float,
    "comp_price_per_sqft_median": float,
    "comp_price_per_acre_median": float,
    "price_deviation_pct": float,  # NEGATIVE = below median = GOOD DEAL
    "comp_confidence": float,       # 0.0-1.0
    "comp_confidence_label": str,   # 'HIGH'|'MEDIUM'|'LOW'
    "comp_lookback_used": int,
    "comp_staleness_penalty_applied": bool,
    "comp_price_range": float,
    "comp_price_stddev": float,
    "comp_variance_high": bool,     # True when range/median > 50%
    "comp_listings": list,          # Top 10 comps with full details
    "comp_radius_used": float,
    "comp_tier_used": int,
    "comp_category": str,           # 'residential'|'land'|'commercial'
    "comp_density": str,            # 'urban'|'suburban'|'rural'
}
```

---

## 16. Enricher (regog/enrichment/enricher.py)

### enrich_property(property_dict, skip_flood=False) → dict

1. **Assessor data**: Calls `assessor_scraper.enrich_with_assessor_data()` (extracts assessed_value, estimated_value, county)
2. **FEMA flood zone**: Calls `fema_scraper.get_flood_zone(lat, lon)` — skip if `skip_flood=True`
3. **Permit signals**: Calls `permit_scraper.fetch_permits(address, zip, county, description)` — keyword-based permit risk

### Assessor Scraper (regog/scrapers/assessor_scraper.py)

- Extracts `estimated_value` and `assessed_value` already provided by HomeHarvest
- If `assessed_value` is None but `estimated_value` exists, uses estimated as proxy
- County name resolution via built-in registry of ~60 major US cities → county mappings
- In-memory cache for county lookups

### Permit Scraper (regog/scrapers/permit_scraper.py)

**Two-tier approach:**
1. **Keyword inference** from listing description:
   - `UNPERMITTED_SIGNALS`: "unpermitted", "no permit", "illegal addition" etc.
   - `CODE_VIOLATION_SIGNALS`: "code violation", "red tag", "condemned" etc.
   - `RENOVATION_PERMIT_SIGNALS`: "permit", "permitted", "building permit" etc.
2. **County portal scraping** (best-effort V1): Registry of 4 counties with Accela/custom portals

Returns `{"permit_risk": "low"|"medium"|"high"|"unknown", "unpermitted_additions": bool, ...}`

---

## 17. Scoring Modules

### Residential Score (regog/scoring/residential_score.py)

6 score components + 3 post-processing steps:

**Components:**
1. **price_deviation** (40 pts max): Below median = positive, above median = negative penalty
   - -50% deviation = 40 pts, -20% = 16 pts, +10% = -2 pts (capped at -10)
2. **dom_signal** (15 pts): Bracketed by days on market
   - 0-30d=15, 31-90d=10, 91-180d=5, 181-365d=2, 365+=0
3. **assessor_gap** (20 pts): `max(0, min(20, (gap_pct/30)*20))`. Missing = 5
4. **condition** (15 pts): From brain classification
   - standard=15, luxury=12, vacant=10, distressed=7, teardown=4, fire_damage=3
5. **flood_penalty** (0-10): X=10, AE=3, A=4, VE=0, None=8
6. **permit_risk** (-5 to +3): low=+3, unknown=0, medium=-2, high=-5

**Post-processing (from scoring/utils.py):**
7. **comp_fallback**: If comp_count=0, use estimated_value as proxy for price deviation
8. **confidence_cap**: LOW confidence caps price at 10, MEDIUM caps at 20
9. **variance_penalty**: If comps<5 and variance_high, reduce price signals by 25%

**Tier:** ≥70=HOT, ≥50=WARM, ≥35=NEUTRAL, ≥20=RISKY, <20=SKIP
**Override:** fire_damage/teardown → `DISTRESSED_` prefix

### Land Score (regog/scoring/land_score.py)

6 score components:
1. **price_per_acre_deviation** (40 pts): List $/acre vs comp median $/acre.
   **CRITICAL: If acres is NULL/0, this signal returns 0. Does NOT use total price as proxy.**
2. **zoning_bonus** (20 pts): Buildable zones=20, non-buildable=2, unknown=10
3. **road_access_bonus** (10 pts): From brain_green_flags keywords
4. **utilities_bonus** (10 pts): From brain_green_flags keywords
5. **acreage_premium** (10 pts): ≤1ac=10, ≤5ac=8, ≤10ac=6, ≤40ac=4, >40ac=2
6. **flood_penalty** (0-10): Same FLOOD_SCORES logic

**Fallback logic when acres are NULL:**
- Redistributes the 50% weight (price_per_acre 40% + acreage_premium 10%) across available signals (zoning, road, utilities, flood) proportionally
- This keeps total < 70 so no HOT leads without acreage data
- Sets `data_confidence = "LOW"`
- Sets `acres_missing = True` in result

**Fallback when acres exist but no comp_price_per_acre:**
- Uses `price_deviation_pct` (total price comparison) as fallback
- This is acceptable because we DO have acreage data, so evaluating total price relative to other total prices is valid
- Sets `data_confidence = "MEDIUM"`

### Commercial Score (regog/scoring/commercial_score.py)

5 score components:
1. **price_deviation** (35 pts)
2. **assessor_gap** (25 pts): For skyscrapers, (gap/20)*25 instead of (gap/30)*25
3. **cap_rate_estimate** (20 pts): Keyword-based from description (8 base + 2 per signal)
4. **condition** (10 pts): Scaled from CONDITION_SCORES (×10/15)
5. **flood_penalty** (0-10)

---

## 18. Scoring Utilities (regog/scoring/utils.py)

### assign_tier(score) → str
Looks up score in `TIER_THRESHOLDS` (sorted descending, highest matching).

### parse_flags(flags_value) → list
Parses brain_red_flags or brain_green_flags from JSON string or Python list.

### apply_comp_fallback(property_dict, scores) → dict
When `comp_count == 0`:
- If `estimated_value` exists: uses `((list_price - estimated) / estimated) * 100` as proxy deviation
- If no estimated_value: sets `_fb_cap_at_risky = True`
- Metadata fields use `_fb_` prefix for safe filtering when summing numeric scores

### apply_confidence_cap(property_dict, scores) → dict
- LOW confidence: caps price_deviation/price_per_acre_deviation at 10
- MEDIUM confidence: caps at 20

### apply_variance_penalty(property_dict, scores) → dict
When comps < 5 AND `comp_variance_high`, reduce price signals by 25%.

### cap_score_if_no_comps(total, scores) → (float, str | None)
When `_fb_cap_at_risky` flag is set, max possible total = 30 (RISKY tier, below NEUTRAL 35).

---

## 19. Property Type Detection (regog/utils/property_type.py)

Maps style strings to categories for comp radius selection.

```python
_RESIDENTIAL_STYLES = {"SINGLE_FAMILY", "MANUFACTURED", "MOBILE"}
_LAND_STYLES = {"LAND", "LOT", "LOTS_LAND", "FARM", "RANCH", "ACREAGE", "VACANT"}
_COMMERCIAL_STYLES = {"CONDOS", "CONDO", "TOWNHOMES", "TOWNHOUSE",
                      "MULTI_FAMILY", "APARTMENT", "DUPLEX", "TRIPLEX", "QUADPLEX",
                      "COMMERCIAL", "OFFICE", "RETAIL", "INDUSTRIAL", "WAREHOUSE",
                      "MIXED_USE", "SPECIAL_PURPOSE", "HOTEL", "MOTEL"}
```

### get_property_category(style, property_type, stories) → str

**High-rise detection**: CONDO/CONDOS with stories >= `HIGH_RISE_MIN_STORIES` (5) → reclassified as commercial.

---

## 20. Market Density (regog/utils/density.py)

ZIP-prefix-based density classification. Static lookup — no API calls.

### get_market_density(zip_code) → 'urban' | 'suburban' | 'rural'

- **Urban prefixes**: Major metro cores (100 NYC, 900 LA, 606 Chicago, 941 SF, 752 Dallas, 850 Phoenix, 331 Miami, 021 Boston, 981 Seattle, 770 Houston, 303 Atlanta, etc.)
- **Rural prefixes**: MT, WY, ID, SD, ND, NV rural areas, WV, MS delta, NM, IA, AK, HI
- **Default**: suburban

---

## 21. Web App Backend (web/app.py)

Flask app with REST API endpoints + SSE streaming.

### Endpoints:

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Serves `static/index.html` |
| `/api/config` | GET | Returns current weights, thresholds, comp defaults |
| `/api/stats` | GET | DB aggregate stats (total, hot, warm, sessions, avg_score) |
| `/api/scans` | GET | Recent 20 scan sessions |
| `/api/scan` | POST | Start a new scan → `{session_id, stream_url}` |
| `/api/scan/<id>/results` | GET | Paginated results (params: page, per_page, tier) |
| `/api/scan/<id>/status` | GET | Current scan status (for polling after SSE closes) |
| `/api/scan/<id>/cancel` | POST | Sets cancel event to stop running scan |
| `/api/scan/<id>/stream` | GET | SSE endpoint streaming properties as they're scored |
| `/api/saved` | GET | List saved properties |
| `/api/saved/<listing_id>` | POST | Toggle save/unsave property |
| `/api/saved/<listing_id>/status` | GET | Check if a property is saved |
| `/api/property/<listing_id>` | GET | Single property detail |

### SSE Streaming:

Events sent in order:
1. `event: connected\ndata: {session_id}\n\n`
2. `event: property\ndata: {json serialized property}\n\n` (one per scored property)
3. `event: complete\ndata: {status json}\n\n`
4. `event: keepalive\ndata: {}\n\n` (every 30s if no data)

### Background Scan Thread (`_run_scan_background`)

Same pipeline as CLI, with additions:
- Thread-safe status updates via `_scan_status_lock`
- SSE queue pushes each property as it's scored
- Cancel event checked every iteration + before processing starts
- `filtered_out` counter tracked in status
- Error logging with full traceback via `logger.error(traceback.format_exc())`

### Score Mapping (critical for land display in web app):

```python
if scan_type == "land":
    prop["score_price_deviation"] = scores.get("price_deviation",
        scores.get("price_per_acre_deviation", 0))
    prop["score_assessor_gap"] = scores.get("assessor_gap",
        scores.get("zoning_bonus", 0))
    prop["score_condition"] = scores.get("condition",
        scores.get("acreage_premium", 0))
```

### Flask Debug Mode

`web/app.py` runs Flask on port 5000 in debug mode when run directly. `serve_report.py` runs on port 8080 in non-debug mode with threading.

---

## 22. Web Frontend (web/static/index.html)

Single HTML file with 850+ lines of inline CSS + JS. Dark theme with REGOG styling.

### CSS Theme Variables:

```css
--bg: #0a0a0a;           --bg-surface: #111111;
--bg-card: #111118;       --accent: #ff2233;
--accent-glow: rgba(255,34,51,0.4);
--text: #e8e8f0;          --green: #44ff66;
--amber: #ffaa00;         --magenta: #ff44aa;
--border: rgba(255,255,255,0.06);
--radius: 12px;           --radius-sm: 8px;
```

### Key UI Elements:

- **Header**: REGOG logo (clickable `onclick="location.href='/'"`), Back button, History button, Saved button with count
- **Scan bar**: Location input, Type dropdown (residential/land/commercial), Min/Max price, SCAN/STOP buttons
- **Stats bar**: Total, HOT count, WARM count, Avg score, Live count (during scan)
- **State-level warning**: Warns users when scanning entire state (Texas, California, etc.) — shows confirm dialog
- **Results grid**: Property cards streamed in real-time, inserted in sort order
- **History panel**: Grouped by scan type with icons (🏠 🌲 🏢) and formatted dates
- **Saved panel**: Starred properties

### Property Card:

- Clickable → expands to show detail grid
- **Badges**: HOT (red gradient with glow), WARM (amber gradient)
- **Score**: Color-coded (green ≥ 70, amber ≥ 50, red < 50)
- **Card row**: Price, vs Median%, Listed (DOM), Beds/Baths, Stories, Sqft, Comps
- **Flags**: Brain classification, filter flags, red/green flags as colored pills
- **Score bar at bottom**
- **Comp confidence badges**: LOW COMPS (red), MED COMPS (amber), WIDE SPREAD (red)
- **Acres display for land**: Red "? acres" if missing
- **Expanded detail**: Full detail grid, comp warnings, segmented score bar (5 segments), brain output, comp listings (horizontal scroll), View Listing + Save buttons

### Key JS Functions:

| Function | Purpose |
|----------|---------|
| `startScan()` | POST to `/api/scan`, open SSE stream, poll status |
| `stopScan()` | POST to `/api/scan/<id>/cancel`, close SSE, show cancelled banner |
| `addProperty(prop)` | Creates card DOM element, inserts in sort order, updates stats |
| `toggleExpand(listingId)` | Toggles `.expanded` class on card to show detail |
| `toggleSave(listingId, btn)` | Save/unsave via API, update count |
| `filterTier(tier)` | Filter visible cards by HOT/WARM/ALL |
| `setSort(mode)` | Re-sort by price $↑/$↓, profit %↑/%↓, score ↓ |
| `reSort()` | Re-sort existing cards without re-adding |
| `getListingUrl(prop)` | Build URL: Realtor.com > Zillow search > Google Maps |
| `getListingLabel(prop)` | Label for the view button |
| `renderCompListings(prop)` | Builds clickable comp cards with thumbnail, beds, baths, sqft, acres, distance |
| `getCompUrl(comp, parentProp)` | Builds Zillow address URL (skips Realtor.com URL which hides sold prices) |
| `buildCompWarning(prop)` | Shows appropriate warning for low comps / high variance |
| `pollStatus()` | Polls `/api/scan/<id>/status` every 2s as SSE fallback |

### Segmented Score Bar (5 segments):

```html
<div class="segment" style="width:${(score_price_deviation)/100*100}%;background:var(--green);"    title="Price Deviation">
<div class="segment" style="width:${(score_assessor_gap)/100*100}%;background:#44aaff;"            title="Assessor Gap">
<div class="segment" style="width:${(score_dom_signal)/100*100}%;background:var(--amber);"         title="DOM Signal">
<div class="segment" style="width:${(score_condition)/100*100}%;background:#aa44ff;"               title="Condition">
<div class="segment" style="width:${(score_flood_penalty)/100*100}%;background:#ff4466;"           title="Flood">
```

### Comp Cards (horizontal scroll):

Each comp card shows: thumbnail image, address (truncated at 35 chars), price (green), beds/baths/sqft/acres/distance, sold/active label with date.

---

## 23. CLI (main.py)

### Commands

```bash
# Initialize database
regog init

# Scans
regog scan residential --location "Dallas, TX" --price-max 400000
regog scan land --location "Texas" --acres-min 5
regog scan commercial --location "Chicago, IL" --type multifamily

# View leads
regog leads --tier HOT --limit 20
regog leads --score-min 70

# Generate HTML report
regog report --session-id abc123
regog report  # uses latest session

# Configuration
regog config --show
regog config --set comp_radius_miles=5

# Scheduled scans
regog schedule --location "Los Angeles, CA" --interval 24
```

### Scan Arguments

| Arg | Description |
|-----|-------------|
| `scan_type` | `residential`, `land`, or `commercial` (positional) |
| `--location` | City, "City, State", or ZIP (required) |
| `--price-min/--price-max` | Price range |
| `--radius` | Search radius in miles |
| `--beds-min` | Min bedrooms (residential) |
| `--sqft-min` | Min square footage |
| `--acres-min/--acres-max` | Acreage range (land) |
| `--type` | Commercial subtype |
| `--dom-max` | Max days on market |
| `--score-min` | Min score to show |
| `--tier` | HOT/WARM/NEUTRAL/RISKY/SKIP filter |
| `--skip-flood` | Skip FEMA flood zone lookup |
| `--use-zillow` | Also scrape Zillow |
| `--zillow-pages` | Zillow pages to scrape (default 2) |
| `--past-days` | Look back period (default 180) |
| `--limit` | Max raw listings to fetch (default 50) |
| `--fresh` | Only show listings added/updated in last N days |
| `--use-redfin` | Also scrape Redfin via browser |
| `--use-craigslist` | Also scrape Craigslist for FSBO/motivated seller |

---

## 24. Scheduler (regog/scheduler/scan_scheduler.py)

Wraps APScheduler for recurring scans. Optional — requires `apscheduler` package.

```python
scheduler = create_scheduler()
schedule_scan(scheduler, scan_func, location="Dallas, TX", scan_type="residential", interval_hours=24)
scheduler.start()
```

Runs in background thread. Configurable interval (default 24h). Same pipeline as CLI/web scans with `skip_flood=True` (FEMA skipped for speed).

---

## 25. Rate Limiter (regog/utils/rate_limiter.py)

Per-source request throttling with exponential backoff.

### rate_limit(source) → None

1. Enforces minimum delay since last request
2. Enforces hourly cap (rolling 1-hour window)
3. Applies random jitter within configured range
4. Applies exponential backoff on consecutive errors: `base * 2^(errors-1)` capped at 60s

### report_success(source), report_error(source)

Reset or increment error counter for backoff calculation.

---

## 26. Tests

**88+ tests total.** Run with:

```bash
cd /workspaces/REgog
python -m pytest tests/ -v --tb=short
```

### Test Files:

- **`test_residential_score.py`**: 10+ test classes covering all 6 signals + tiers + edge cases + data types
  - `TestBaselineScore`, `TestPriceDeviation`, `TestDaysOnMarket`, `TestAssessorGap`
  - `TestCondition`, `TestFloodPenalty`, `TestPermitRisk`, `TestTierAssignment`
  - `TestEdgeCases`, `TestDataTypes`

- **`test_land_score.py`**: Tests for land scoring (zoning, acreage premium, empty dict)

- **`test_utils.py`**: `assign_tier` thresholds/boundaries, `parse_flags` (list, JSON, None, invalid)

- **`test_permit_scraper.py`**: Permit inference tests (unpermitted addition, code violations, approved plans, mixed signals, case insensitivity, etc.)

### Fixtures (conftest.py):

- `standard_residential`: Baseline property with all fields
- `hot_deal_residential`: Deep discount + large assessor gap + low permit risk
- `skip_residential`: Overpriced + flood risk + high permit risk
- `missing_data_residential`: All None values
- `distressed_residential`: Fire damage classification

---

## 27. Known Issues & Edge Cases

1. **Sold comps fetched city-wide, not by radius**: HomeHarvest doesn't support coordinate-based queries, so comps are fetched for the entire city then filtered by distance in the comp engine. Sparse areas get fewer comps.

2. **5 comps minimum with wide variance**: Even with `MIN_COMPS_REQUIRED=5`, some areas simply don't have 5 sold comps. System falls back to whatever it can find with LOW confidence + variance penalty. Confidence capping and variance penalty reduce the price signal when comp data is poor.

3. **Land acreage can be NULL**: HomeHarvest's acres data is inconsistent for land parcels. The normalize function has an extensive fallback chain (20+ possible column names) but some parcels still have NULL acres. The land scoring handles this by redistributing weight away from acreage-dependent signals and capping the maximum possible score below HOT.

4. **Score breakdown for land**: Frontend expects 5 score components, but land has different keys (zoning_bonus instead of assessor_gap, acreage_premium instead of condition). Mapping is done in `web/app.py` in the background scan thread.

5. **Realtor.com hides sold prices**: Comp card links use Zillow address URLs (not Realtor.com) since Realtor.com hides sold prices on listing pages.

6. **No coordinate-based sold comps**: `fetch_sold_comps_near_coords()` returns empty — use city-level fetch instead. This function is defined twice in `redfin_scraper.py`, both returning `[]`.

7. **`fetch_sold_comps()` is defined twice**: The stale function in `homeharvest_scraper.py` returns `[]` and should NOT be used. The real one is in `redfin_scraper.py`.

8. **FEMA API is intermittently unreliable**: The free government ArcGIS endpoint frequently returns `"Failed to execute query"` errors under load. Retry logic (2 attempts) and caching help, but `--skip-flood` is recommended for fast scans.

9. **`assessed_value` is never available from HomeHarvest**: The `estimated_value` (AVM) is used as proxy. This is a Zestimate-like automated valuation, not an official tax assessment.

---

## 28. Quick Start (From Scratch)

```bash
# 1. Create project structure as above
cd /workspaces/REgog

# 2. Install dependencies
pip install homeharvest beautifulsoup4 httpx lxml aiosqlite sqlite-utils rich geopy apscheduler jinja2 playwright
playwright install chromium

# 3. Init database
python3 -c "from db.database import init_db; init_db()"

# 4. Verify with tests
python -m pytest tests/ -v --tb=short

# 5. Start web server
python3 serve_report.py
# → Open http://localhost:8080/

# 6. Run a scan from the web UI
# → Enter "Dallas, TX", price max 400000, click SCAN
# → Verify SSE stream, property cards, history, saved

# 7. Or use CLI:
python3 regog/main.py scan residential --location "Dallas, TX" --price-max 400000 --limit 10
python3 regog/main.py leads --tier HOT
```

---

## 29. Architecture Diagram (Data Flow)

```
┌─────────────────┐     ┌──────────────────────┐     ┌────────────────────┐
│ Realtor.com     │────▶│ HomeHarvest           │────▶│ normalize_listing  │
│ (Scraped)       │     │ scrape_property()     │     │ (g(*keys) mapper)  │
└─────────────────┘     └──────────────────────┘     └────────┬───────────┘
                                                              │
┌─────────────────┐     ┌──────────────────────┐              ▼
│ SOLD data       │────▶│ fetch_sold_comps    │──▶ normalize_sold_listing()
│ (same city)     │     │ (listing_type="sold")│              │
└─────────────────┘     └──────────────────────┘              │
                                                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Pipeline (per listing)                                  │
│                                                                             │
│  raw_dict ─▶ normalize_listing() ─▶ property_dict                          │
│                                         │                                   │
│                                         ▼                                   │
│                               brain.classify_property()                     │
│                               (keyword-based, no LLM)                      │
│                                         │                                   │
│                                         ▼                                   │
│                             listing_filter.filter_listing()                 │
│                             (skip: auction/bait, flag: burned/demolition)   │
│                                         │                                   │
│                                         ▼                                   │
│                               enricher.enrich_property()                    │
│                               (assessor, FEMA flood, permit signals)        │
│                                         │                                   │
│                                         ▼                                   │
│                    comp_engine.calculate_comps()                             │
│                    (style filter → 2D expansion (radius × time) →           │
│                     similarity filter → medians → variance → confidence)    │
│                                         │                                   │
│                                         ▼                                   │
│                    score_*(property_dict)                                    │
│                    (residential/land/commercial, 5-6 signals each)          │
│                    + apply_comp_fallback / confidence_cap / variance_penalty │
│                                         │                                   │
│                                         ▼                                   │
│                              upsert_property(DB)                            │
│                              + push to SSE stream (web app)                 │
└─────────────────────────────────────────────────────────────────────────────┘
```
