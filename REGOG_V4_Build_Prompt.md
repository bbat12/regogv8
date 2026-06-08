# REGOG V4 — Real Estate Go/No-Go Scanner
## Complete Build Prompt for a New AI Agent

> **Purpose:** A new AI agent (Claude/Codebuff) with no prior knowledge of this project should be able to rebuild REGOG from scratch using this document alone. Every detail is included: architecture, data flow, rules, scoring math, UI specs, and conventions learned across V1–V3.

---

## TABLE OF CONTENTS

1. [Project Overview](#1-project-overview)
2. [Technology Stack](#2-technology-stack)
3. [Architecture & Data Flow](#3-architecture--data-flow)
4. [File Structure](#4-file-structure)
5. [Database Schema](#5-database-schema)
6. [Configuration System](#6-configuration-system)
7. [HomeHarvest Scraper](#7-homeharvest-scraper)
8. [Sold Comps Pipeline](#8-sold-comps-pipeline)
9. [Comp Engine (Style-Filtered)](#9-comp-engine-style-filtered)
10. [Brain Classifier](#10-brain-classifier)
11. [Enrichment Pipeline](#11-enrichment-pipeline)
12. [Scoring Engine](#12-scoring-engine)
13. [CLI Interface](#13-cli-interface)
14. [Web UI Architecture](#14-web-ui-architecture)
15. [Rate Limiting & Anti-Bot](#15-rate-limiting--anti-bot)
16. [Scheduler](#16-scheduler)
17. [Testing](#17-testing)
18. [UI Aesthetic Rules](#18-ui-aesthetic-rules)
19. [Critical Rules & Gotchas](#19-critical-rules--gotchas)

---

## 1. Project Overview

**REGOG** (Real Estate Go/No-Go) is a nationwide US real estate intelligence scanner that automatically finds undervalued properties using only free, no-API-key methods. It:

1. **Scrapes** listings from Realtor.com (via HomeHarvest library) and optionally Zillow (via Playwright)
2. **Enriches** each listing with:
   - Assessor valuation data (from HomeHarvest)
   - FEMA flood zone data (free ArcGIS WMS endpoint)
   - Permit signals (keyword inference from listing descriptions)
3. **Computes comps** by finding recently sold comparable properties filtered by property **style** (apples-to-apples comparison)
4. **Scores** every property 0–100 using a multi-signal algorithm with configurable weights
5. **Surfaces** results via a dark-themed web UI with SSE streaming or a Rich terminal dashboard

**Core Philosophy:**
- **Zero API costs** — every data source is free and requires no API key
- **Apples-to-apples comps** — properties are compared only against same-style sold properties (SINGLE_FAMILY vs SINGLE_FAMILY, not SINGLE_FAMILY vs CONDOS)
- **Real-time feedback** — the web UI streams results as they're scored via Server-Sent Events
- **Single-file SQLite** — no external database server needed; everything runs locally

---

## 2. Technology Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| Language | Python 3.10+ | Type hints required on all functions |
| Database | SQLite (via `sqlite3`) | Single `regog.db` file, WAL mode |
| Listing Data | `homeharvest` (PyPI) | Free Realtor.com scraper, no API key |
| Sold Comps | `homeharvest` (same library) | `listing_type="sold"` fetches sold data |
| Zillow Scraper | `playwright` + `playwright-stealth` | Optional secondary source |
| Flood Zones | FEMA NFHL ArcGIS WMS | Free REST API, no auth needed |
| Web Framework | Flask | Single-page app with SSE streaming |
| Terminal UI | `rich` (PyPI) | Dark theme with red/crimson accents |
| HTML Reports | `jinja2` | Dark-themed report generation |
| Geocoding | `httpx` + Nominatim (OSM) | Free, 1 req/sec rate limit — **note: currently unused by the pipeline** |
| Scheduler | `apscheduler` (optional) | Background recurring scans |
| HTML Parsing | `beautifulsoup4` | County portal scraping |

### Dependencies (`requirements.txt`)

```
homeharvest
playwright
playwright-stealth
rich
flask
flask-cors
httpx
beautifulsoup4
geopy          # NOTE: listed in requirements but UNUSED in the actual codebase
apscheduler
jinja2
```

After install: `playwright install chromium`

### `.gitignore`

Create a `.gitignore` at project root with at minimum:
```
regog.db
regog_config.json
__pycache__/
*.pyc
regog_report.html
/tmp/
```
The SQLite database (`regog.db`) and generated reports should never be committed.

---

## 3. Architecture & Data Flow

The system runs as a linear pipeline for each property:

```
User Input (location, type, price range)
        │
        ▼
┌─────────────────────┐
│ 1. Fetch Sold Comps  │ ◄── HomeHarvest (listing_type="sold")
│    (up to 200)       │     Same-area sold properties
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 2. Fetch Listings    │ ◄── HomeHarvest (listing_type="for_sale")
│    (for sale)        │     + optional Zillow merge
└─────────┬───────────┘
          │
          ▼  (for each listing)
┌─────────────────────┐
│ 3. Normalize         │ ◄── Map HomeHarvest columns → REGOG schema
│    (per listing)     │     Capture: style, property_url, lat/lon
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 4. Price Filter      │ ◄── Skip if outside user's price range
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 5. Brain Classify    │ ◄── Keyword-based: distressed, luxury, etc.
│    (description)      │     No LLM required for V4
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 6. Enrichment        │ ◄── Assessor data, FEMA flood zone, permit signals
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 7. Calculate Comps   │ ◄── Style-filtered + radius + sqft matching
│    (vs sold data)     │     Returns: median price, deviation%, comp count
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 8. Score Property    │ ◄── 0-100 score with tier assignment
│    (multi-signal)     │     HOT ≥ 70, WARM ≥ 50, etc.
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 9. Upsert to DB      │ ◄── Strip UI-only fields (style, property_url)
│    + Stream to UI     │     before DB insert; restore for SSE
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 10. Display Results  │ ◄── Web UI (SSE stream) or CLI terminal
└─────────────────────┘
```

### Important Data Flow Rules

1. **Sold comps are fetched ONCE per scan** (up to 200), then reused for all listings
2. **`style` and `property_url` must be popped before DB upsert** (not in SQLite schema) and restored after for SSE streaming
3. **The comp engine filters by style FIRST** before radius, before sqft — this is critical for accuracy
4. **Properties are streamed in processing order** (raw listing order) — the **frontend** inserts cards in score-sorted order using DOM insertion comparison in `addProperty()`, so the displayed list is always highest-score-first.

---

## 4. File Structure

```
regog/
├── README.md
├── serve_report.py              # Entry point — runs Flask web app on port 8080
│
├── regog/
│   ├── __init__.py
│   ├── main.py                  # CLI entry point with argparse
│   ├── config.py                # ALL settings, weights, thresholds in one file
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.sql           # SQLite schema (properties + scan_sessions tables)
│   │   └── database.py          # DB connection, init, upsert, query helpers
│   │
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── homeharvest_scraper.py   # fetch_listings(), normalize_listing()
│   │   ├── redfin_scraper.py        # fetch_sold_comps() — uses HomeHarvest for sold
│   │   ├── zillow_stealth.py         # Playwright-based Zillow scraper
│   │   ├── fema_scraper.py          # FEMA NFHL flood zone via WMS
│   │   ├── assessor_scraper.py      # Provides estimated/assessed values
│   │   └── permit_scraper.py        # Keyword permit inference + county portals
│   │
│   ├── enrichment/
│   │   ├── __init__.py
│   │   ├── brain.py                 # Keyword-based property classifier
│   │   ├── comp_engine.py           # Style-filtered comp calculation
│   │   ├── enricher.py              # Orchestrates: assessor + FEMA + permits
│   │   └── geocoder.py              # Nominatim geocoding (free) — ⚠️ DEAD CODE, never called by pipeline
│   │
│   ├── scoring/
│   │   ├── __init__.py
│   │   ├── residential_score.py     # 0-100 for residential (6 signals)
│   │   ├── land_score.py            # 0-100 for land (6 signals)
│   │   ├── commercial_score.py      # 0-100 for commercial (5 signals)
│   │   └── utils.py                 # assign_tier(), parse_flags()
│   │
│   ├── scheduler/
│   │   └── scan_scheduler.py        # APScheduler wrapper for recurring scans
│   │
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── terminal.py              # Rich terminal dashboard
│   │   ├── report_generator.py      # Jinja2 HTML report generator
│   │   └── templates/ │   │       └── report.html.j2       # Dark-themed HTML template (Jinja2) — generates static HTML reports with stats bars, property cards, flags, and score bars matching the web UI aesthetic
│   │
│   └── utils/
│       ├── __init__.py
│       ├── config_store.py          # Persistent JSON config store
│       └── rate_limiter.py          # Per-source rate limiting with backoff
│
├── web/
│   ├── app.py                  # Flask app with all API endpoints + SSE
│   └── static/
│       └── index.html          # Single-page dark UI (all CSS/JS inline)
│
└── tests/
    ├── __init__.py
    ├── conftest.py             # Shared test fixtures
    ├── test_residential_score.py   # 40+ tests for scoring
    ├── test_land_score.py          # Land scoring tests
    ├── test_utils.py               # assign_tier, parse_flags tests
    └── test_permit_scraper.py      # Permit inference tests
```

---

## 5. Database Schema

### `properties` Table

```sql
CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT UNIQUE,
    source TEXT,                    -- 'realtor', 'redfin', 'zillow'
    scan_type TEXT,                 -- 'residential', 'land', 'commercial'
    commercial_subtype TEXT,        -- 'multifamily', 'hotel', 'industrial', 'office', 'retail', 'skyscraper', null
    address TEXT,
    city TEXT,
    state TEXT,
    zip TEXT,
    lat REAL,
    lon REAL,
    list_price INTEGER,
    price_per_sqft REAL,
    price_per_acre REAL,
    sqft INTEGER,
    acres REAL,
    beds INTEGER,
    baths REAL,
    year_built INTEGER,
    lot_sqft INTEGER,
    days_on_market INTEGER,
    listing_status TEXT,
    listing_description TEXT,
    price_history TEXT,             -- JSON array stored as TEXT
    last_sold_price INTEGER,
    last_sold_date TEXT,
    assessed_value INTEGER,
    estimated_value INTEGER,        -- AVM from HomeHarvest
    assessed_year INTEGER,
    flood_zone TEXT,                -- FEMA zone code
    zoning TEXT,
    permit_flags TEXT,              -- JSON object
    brain_classification TEXT,      -- 'luxury','standard','distressed','teardown','fire_damage','vacant','land_only'
    brain_red_flags TEXT,           -- JSON array as TEXT
    brain_green_flags TEXT,         -- JSON array as TEXT
    brain_seller_motivation TEXT,   -- 'high','medium','low'
    comp_median_price INTEGER,
    comp_count INTEGER,
    comp_radius_miles REAL,
    comp_price_per_sqft_median REAL,
    comp_price_per_acre_median REAL,
    score_total REAL,               -- 0–100
    score_price_deviation REAL,
    score_dom_signal REAL,
    score_assessor_gap REAL,
    score_condition REAL,
    score_acreage_value REAL,
    score_flood_penalty REAL,
    lead_tier TEXT,                 -- 'HOT','WARM','NEUTRAL','RISKY','SKIP'
    price_deviation_pct REAL,       -- negative = below median (good)
    first_seen TEXT,
    last_updated TEXT,
    scan_session_id TEXT
);
```

### `scan_sessions` Table

```sql
CREATE TABLE IF NOT EXISTS scan_sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT,
    completed_at TEXT,
    scan_type TEXT,
    search_params TEXT,             -- JSON object
    properties_found INTEGER,
    hot_leads_found INTEGER
);
```

### `price_history_tracking` Table

```sql
CREATE TABLE IF NOT EXISTS price_history_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT,
    recorded_at TEXT,
    price INTEGER,
    days_on_market INTEGER,
    FOREIGN KEY (listing_id) REFERENCES properties(listing_id)
);
```

### Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_properties_listing_id ON properties(listing_id);
CREATE INDEX IF NOT EXISTS idx_properties_scan_session ON properties(scan_session_id);
CREATE INDEX IF NOT EXISTS idx_properties_tier ON properties(lead_tier);
CREATE INDEX IF NOT EXISTS idx_properties_score ON properties(score_total DESC);
CREATE INDEX IF NOT EXISTS idx_properties_location ON properties(city, state);
```

### JSON Field Handling

The `_JSON_FIELDS` set in `database.py` defines which columns are auto-serialized/deserialized:

```python
_JSON_FIELDS = {
    "brain_red_flags",
    "brain_green_flags",
    "price_history",
    "permit_flags",
}
```

- **On write**: Lists/dicts are `json.dumps()` → TEXT
- **On read**: TEXT values are `json.loads()` → Python objects

### CRITICAL: Fields NOT in DB Schema

These fields are used in-memory and during SSE streaming but are **NOT columns in SQLite**:
- `property_url` — Realtor.com detail URL (must be popped before upsert)
- `style` — Property type for comp matching (must be popped before upsert)
- `scan_type` — Already stored differently in DB

**Both `main.py` and `web/app.py` must pop these before calling `upsert_property()`, then restore them afterward for streaming.**

### `score_acreage_value` — Land-Only Field

The database has a `score_acreage_value REAL` column, but it is **only populated by land scoring** (`land_score.py` → `acreage_premium`). Residential and commercial scoring never set this field — it will remain `NULL` for those property types.

---

## 6. Configuration System

All settings live in `regog/config.py`:

### Scoring Weights

```python
RESIDENTIAL_WEIGHTS = {
    "price_deviation": 0.40,   # 40 pts max
    "dom_signal": 0.15,        # 15 pts max
    "assessor_gap": 0.20,      # 20 pts max
    "condition": 0.15,         # 15 pts max
    "flood_penalty": 0.10,     # 10 pts max (deduction for risk)
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

### Tier Thresholds

```python
TIER_THRESHOLDS = {
    "HOT": 70,
    "WARM": 50,
    "NEUTRAL": 35,
    "RISKY": 20,
    "SKIP": 0,
}
```

### Comp Defaults

```python
COMP_DEFAULTS = {
    "radius_miles": 3,
    "min_comps_required": 3,
    "max_radius_miles": 10,
    "similar_sqft_pct": 0.30,    # ±30%
    "similar_acres_pct": 0.50,   # ±50%
    "sold_months": 12,
}
```

### Rate Limits

```python
RATE_LIMITS = {
    "realtor": {"delay_min": 2, "delay_max": 5, "max_per_hour": 200},
    "redfin": {"delay_min": 1, "delay_max": 3, "max_per_hour": 300},
    "zillow": {"delay_min": 4, "delay_max": 9, "max_per_hour": 60},
    "assessor": {"delay_min": 3, "delay_max": 8, "max_per_hour": 100},
}
```

### Brain Classifier Keywords

See `config.py` for full keyword lists for:
- `CLASSIFICATION_KEYWORDS` — distressed, teardown, fire_damage, vacant, luxury
- `SELLER_MOTIVATION_KEYWORDS` — high, medium
- `RED_FLAG_KEYWORDS` — foundation issues, structural, mold, etc.
- `GREEN_FLAG_KEYWORDS` — renovated, updated, new roof, etc.

### Scoring Maps

```python
FLOOD_SCORES = {"X": 10, "AE": 3, "A": 4, "VE": 0, None: 8}
CONDITION_SCORES = {"standard": 15, "luxury": 12, "vacant": 10,
                    "distressed": 7, "teardown": 4, "fire_damage": 3}
PERMIT_SCORES = {"low": 3, "unknown": 0, "medium": -2, "high": -5}
DOM_SCORE_BRACKETS = [(30, 15), (90, 10), (180, 5), (float("inf"), 2)]
```

---

## 7. HomeHarvest Scraper

**File:** `regog/scrapers/homeharvest_scraper.py`

### `fetch_listings(location, listing_type, past_days, property_type)`

- Calls `homeharvest.scrape_property()` with the given parameters
- Returns raw DataFrame converted to list of dicts
- Handles `ImportError` gracefully (returns `[]` if homeharvest not installed)

### `normalize_listing(raw, source, scan_session_id, scan_type)`

**⚠️ IMPORTANT: `homeharvest_scraper.py` also contains a STALE `fetch_sold_comps(lat, lon, radius_miles, scan_type)` function that always returns `[]`. Do NOT use it — the real sold comps function is in `redfin_scraper.py`.**

This is the **most critical normalization function** in the app. It maps HomeHarvest column names (which vary) to REGOG's schema.

**The `g(*keys)` helper** tries multiple possible column names:

```python
def g(*keys):
    """Get first non-None value from a list of possible keys."""
    for k in keys:
        v = raw.get(k)
        if v is not None:
            return v
    return None
```

**Field mappings (each tries multiple key names):**

| REGOG Field | HomeHarvest Keys Tried |
|------------|----------------------|
| `listing_id` | `property_id`, `listing_id`, `mls_id`, `id` |
| `style` | `style`, `property_type`, `home_type` |
| `address` | `full_street_line`, `street`, `address`, `full_address`, `formatted_address` |
| `city` | `city`, `municipality` |
| `state` | `state`, `province` |
| `zip` | `zip`, `zip_code`, `postal_code` |
| `list_price` | `list_price`, `price`, `current_price`, `sold_price` |
| `price_per_sqft` | `price_per_sqft`, `ppsf`, `price_sqft` (or computed from price/sqft) |
| `sqft` | `sqft`, `square_feet`, `sq_ft`, `living_area`, `building_area` |
| `beds` | `beds`, `bedrooms`, `baths_full`, `bathrooms_full` |
| `full_baths` / `baths` | `full_baths`, `baths`, `bathrooms`, `bathrooms_total` |
| `days_on_market` | `days_on_market`, `dom`, `days_on_mls`, `listing_age` |
| `property_url` | `property_url`, `rdc_web_url`, `href`, `url` |
| `last_sold_price` | `last_sold_price`, `sold_price` |
| `estimated_value` | `estimated_value`, `value`, `zestimate`, `avm_value` |
| `assessed_value` | `assessed_value`, `tax_assessment`, `assessed_valuation` |
| `description` | `description`, `listing_description`, `text`, `remarks`, `public_remarks` |

**`style` field is CRITICAL** — it's used by the comp engine for apples-to-apples filtering. Must capture from HomeHarvest's `style` column which returns values like: `SINGLE_FAMILY`, `CONDOS`, `TOWNHOMES`, `MULTI_FAMILY`, `LAND`, `APARTMENT`, `MOBILE`.

**`property_url` is CRITICAL** — it provides the direct Realtor.com listing URL that the frontend needs for "View Listing" buttons.

### Property Type Mapping

HomeHarvest accepts these property types:

```python
PROPERTY_TYPES = {
    "residential": ["single_family", "multi_family", "condos", "townhomes", "duplex_triplex"],
    "land": ["land"],
    "commercial": ["multi_family"],  # MULTI_FAMILY = 5+ units
}
```

**NOTE:** `condo_townhome` returns zero results — must use `townhomes` and `condos` separately.

---

## 8. Sold Comps Pipeline

**File:** `regog/scrapers/redfin_scraper.py`

### `fetch_sold_comps(location, scan_type, past_days, limit)`

1. Maps `scan_type` to property types (same mapping as for_sale)
2. Calls `homeharvest.scrape_property()` with `listing_type="sold"`
3. Returns up to `limit` normalized property dicts

**Important:** Sold comps are fetched ONCE per scan (up to 200) and reused across all properties. They're normalized via the same `normalize_listing()` function, so they have the same schema including `style`, `last_sold_price`, etc.

**Fallback if HomeHarvest unavailable:** Returns `[]`.

---

## 9. Comp Engine (Style-Filtered)

**File:** `regog/enrichment/comp_engine.py`

### `calculate_comps(property_dict, sold_properties, radius_miles, scan_type)`

This is the **heart of the deal-finding logic**. It compares each active listing against recently sold properties.

#### Algorithm (in order):

1. **Style Filter** (Step 1 — most important):
   ```python
   target_style = property_dict.get("style", "")
   style_map = {
       "SINGLE_FAMILY": ["SINGLE_FAMILY"],
       "CONDOS": ["CONDOS"],
       "TOWNHOMES": ["TOWNHOMES"],
       "MULTI_FAMILY": ["MULTI_FAMILY"],
       "APARTMENT": ["APARTMENT", "MULTI_FAMILY"],
       "LAND": ["LAND"],
       "MOBILE": ["MOBILE", "SINGLE_FAMILY"],
   }
   matching_styles = style_map.get(target_style.upper(), [])
   ```
   If style is unknown, falls back to scan_type-based matching:
   - `residential`: SINGLE_FAMILY, CONDOS, TOWNHOMES, MULTI_FAMILY
   - `land`: LAND
   - `commercial`: MULTI_FAMILY, APARTMENT

2. **Radius Filter** (Step 2): Simple bounding box using lat/lon approximation:
   - 1° lat ≈ 69 miles
   - 1° lon ≈ 54 miles (at US mid-latitude)
   - Default radius: 3 miles (from config)

3. **Size Similarity** (Step 3):
   - Residential: ±30% sqft
   - Land: ±50% acres
   - Only applies if enough comps remain after filtering (keeps unfiltered if too few)

4. **Radius Expansion** (Step 4): If fewer than `min_comps_required` (3) comps found:
   - Expand to 5mi, 7mi, 10mi
   - Re-apply style filter at each expansion

5. **Median Calculation** (Step 5):
   ```python
   prices = [c.get("list_price") or c.get("last_sold_price") for c in comps]
   comp_median_price = median(prices)
   price_deviation_pct = ((target_price - comp_median_price) / comp_median_price) * 100
   ```

6. **Returns:**
   ```python
   {
       "comp_median_price": int,
       "comp_count": int,
       "comp_radius_miles": float,
       "comp_price_per_sqft_median": float,
       "comp_price_per_acre_median": float,
       "price_deviation_pct": float,  # NEGATIVE = below median = good deal
   }
   ```

**CRITICAL:** Negative `price_deviation_pct` means the listing is priced BELOW the median comp price — that's a good deal. The scoring algorithm rewards this heavily.

---

## 10. Brain Classifier

**File:** `regog/enrichment/brain.py`

### `classify_property(address, scan_type, list_price, sqft, year_built, days_on_market, description)`

**Keyword-based classifier** — no LLM required for V4. Scans listing description text for signal keywords.

#### Classification Priority Order (first match wins):
1. **fire_damage** — fire/smoke/water damage keywords
2. **teardown** — land value, buildable lot, demolish, scrape
3. **distressed** — as-is, needs work, fixer-upper, deferred maintenance
4. **vacant** — vacant, abandoned, boarded up
5. **luxury** — luxury, high-end, premium, estate (only if still "standard")
6. **land_only** — if `scan_type == "land"`

#### Seller Motivation:
- High: motivated seller, must sell, relocation, divorce, estate sale, short sale, price reduced
- Medium: open to offers, flexible, seller motivated

#### Returns:
```python
{
    "classification": str,          # 'standard' | 'luxury' | 'distressed' | 'teardown' | 'fire_damage' | 'vacant' | 'land_only'
    "confidence": float,            # 0.0–1.0
    "red_flags": [str],             # Detected problem keywords
    "green_flags": [str],           # Detected opportunity keywords
    "seller_motivation": str,       # 'high' | 'medium' | 'low'
    "motivation_signals": [str],    # Matched keyword list
    "estimated_condition": str,     # 'excellent' | 'good' | 'fair' | 'poor' | 'uninhabitable'
    "is_luxury": bool,
    "notes": str,                   # Summary for investor
}
```

---

## 11. Enrichment Pipeline

**File:** `regog/enrichment/enricher.py`

### `enrich_property(property_dict, skip_flood)`

Orchestrates three enrichment sources:

1. **Assessor Data** (`assessor_scraper.py`):
   - Extracts `estimated_value` and `assessed_value` already provided by HomeHarvest
   - Falls back: if `assessed_value` is None but `estimated_value` exists, uses estimated as proxy
   - Resolves county from city/state via built-in registry (~60 major US cities)

2. **FEMA Flood Zone** (`fema_scraper.py`):
   - Queries FEMA NFHL ArcGIS WMS: `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query`
   - Free, no API key required
   - Rate-limited to 1 req/sec
   - Cached by (lat, lon) rounded to 3 decimal places (~100m resolution)
   - Returns zone code: `X` (low), `AE`/`A` (high), `VE` (coastal extreme)
   - Uses `httpx` with retry (2 attempts) and 15s timeout

3. **Permit Signals** (`permit_scraper.py`):
   - Two-tier: keyword inference + county portal scraping (V1 limited)
   - Keyword inference detects: `unpermitted addition`, `code violation`, `red tag`, `condemned`
   - Also detects positive signals: `permitted`, `approved plans`, `building permit`
   - County portal scraping is best-effort (most portals are JS-heavy)

---

## 12. Scoring Engine

Three scoring modules in `regog/scoring/`:

### Residential Score (`residential_score.py`)

Six signals, max ~103 points (can exceed 100):

| Signal | Max Pts | Weight | Logic |
|--------|---------|--------|-------|
| `price_deviation` | 40 | 0.40 | `max(0, min(40, (-dev/50)*40))` — -50% = 40pts, 0% = 0pts |
| `dom_signal` | 15 | 0.15 | ≤30d=15, ≤90d=10, ≤180d=5, >180d=2 |
| `assessor_gap` | 20 | 0.20 | `max(0, min(20, (gap_pct/30)*20))` — 30% gap = 20pts |
| `condition` | 15 | 0.15 | standard=15, luxury=12, vacant=10, distressed=7, teardown=4, fire_damage=3 |
| `flood_penalty` | 10 | 0.10 | X=10 (no penalty), AE=3, A=4, VE=0, None=8 |
| `permit_risk` | +3 to -5 | **Flat modifier** (not weighted) | low=+3, unknown=0, medium=-2, high=-5. Added directly to total AFTER weighted sum. |

**Tier assignment:** ≥70=HOT, ≥50=WARM, ≥35=NEUTRAL, ≥20=RISKY, <20=SKIP
**Override:** fire_damage/teardown → `DISTRESSED_HOT`, `DISTRESSED_WARM`, etc.

### Land Score (`land_score.py`)

Six signals: price_per_acre_deviation (40), zoning_bonus (20), road_access_bonus (10), utilities_bonus (10), acreage_premium (10), flood_penalty (10)

### Commercial Score (`commercial_score.py`)

Five signals: price_deviation (35), assessor_gap (25), cap_rate_estimate (20), condition (10), flood_penalty (10)

---

## 13. CLI Interface

**File:** `regog/main.py`

### Commands

```bash
regog init                                   # Initialize SQLite database
regog scan residential --location "Dallas, TX" --price-max 400000
regog scan land --location "Texas" --acres-min 5
regog scan commercial --location "Chicago, IL" --type multifamily
regog leads --tier HOT --limit 20
regog report --session-id abc123
regog schedule --location "Los Angeles, CA" --interval 24
regog config --show
regog config --set comp_radius_miles=5
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
| `--zillow-pages` | Zillow pages to scrape (default 2, ~40 listings/page) |
| `--past-days` | Look back period for listings (default 90) |
| `--limit` | Max raw listings to fetch from HomeHarvest (default 50) — controls scraper output, not displayed count |
| `--fresh` | Only show listings added/updated in last N days |

### Pipeline (same for all paths)

Every scan follows the same pipeline:
1. Fetch sold comps → `fetch_sold_comps()`
2. Fetch listings → `fetch_listings()`
3. For each: normalize → classify → enrich → comps → score → upsert

---

## 14. Web UI Architecture

**Files:** `web/app.py` (Flask backend) + `web/static/index.html` (SPA frontend)

### Backend (`web/app.py`)

**Entry point:** `serve_report.py` imports `app` from `web.app` and runs on port 8080.

**API Endpoints:**

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Serves index.html |
| `/api/config` | GET | Returns current weights, thresholds, comp defaults |
| `/api/stats` | GET | DB stats (total properties, HOT/WARM counts) |
| `/api/scans` | GET | Recent scan sessions (last 20) |
| `/api/scan` | POST | Start a new scan → returns `{session_id, stream_url}` |
| `/api/scan/<id>/results` | GET | Paginated results for completed scan |
| `/api/scan/<id>/status` | GET | Current scan status |
| `/api/scan/<id>/stream` | GET | SSE stream of properties as they're scored |
| `/api/saved` | GET | Saved properties |
| `/api/saved/<listing_id>` | POST | Toggle save status |
| `/api/property/<listing_id>` | GET | Single property detail |

**SSE Streaming:**

```python
# Stream sends events:
event: connected\ndata: {"session_id": "abc123"}\n\n
event: property\ndata: {json serialized property}\n\n
event: complete\ndata: {status json}\n\n
event: keepalive\ndata: {}\n\n  # every 30s if no data
```

**Background Scan Thread:**

```python
# In _run_scan_background():
# 1. Fetch sold comps
# 2. Fetch listings
# 3. Process each property through the pipeline
# 4. For each property:
#    a. Normalize → classify → enrich → comps → score
#    b. Pop style, property_url
#    c. upsert_property()
#    d. Restore style, property_url
#    e. progress_q.put(property)  # → SSE stream
# 5. progress_q.put(None)  # Signal completion
```

### Frontend (`index.html`)

**Single-page app** — all CSS and JS embedded in one HTML file.

**Layout:**
- Header: REGOG logo (clickable → `/`), Back button, History button, Saved button
- Scan bar: Location input, Type dropdown, Min/Max price, SCAN button
- Stats bar: Total, HOT count, WARM count, Avg score, Live count (during scan)
- Results grid: Property cards streamed in real-time, sorted by score
- History panel: Scans grouped by type (Residential/Land/Commercial) with formatted dates
- Saved panel: Starred properties

**Property Card:**
- Clickable → expands to show detail grid
- Badges: HOT (red glow), WARM (amber)
- Score with color (green ≥ 70, amber ≥ 50, red < 50)
- Card row: Price, vs Median%, DOM, Beds/Baths, Sqft, Comp count
- Score bar at bottom
- Expanded detail: full grid, segmented score bar, brain output, comp info, actions
- "View Listing" button → uses `property_url` (Realtor.com) → Zillow search → Google Maps fallback
- Save button (star toggle)

**URL Priority in `getListingUrl(prop)`:**
```javascript
function getListingUrl(prop) {
    if (prop.property_url) return prop.property_url;  // Realtor.com direct
    if (prop.detail_url) return prop.detail_url;        // Zillow direct
    // Zillow address search fallback
    // Google Maps last resort
}
```

**Comp deviation display:** `prop.price_deviation_pct` shown as percentage, green if negative (good deal).

**UI State Management:**
- `currentSessionId` — active scan session
- `eventSource` — SSE connection
- `allProperties` — accumulated properties array
- `savedListingIds` — Set of starred listing IDs
- `scanActive` / `scanCompleted` — prevent double events

### JS Functions

| Function | Purpose |
|----------|---------|
| `startScan()` | POST to `/api/scan`, open SSE stream, poll status |
| `addProperty(prop)` | Insert card in score-sorted order, update stats |
| `toggleExpand(id)` | Toggle detail view |
| `toggleSave(id, btn)` | Save/unsave via API |
| `filterTier(tier)` | Filter visible cards by tier |
| `updateStats()` | Recalculate and display stats |
| `togglePanel(panel)` | Show/hide history or saved panel |
| `loadHistory()` | Fetch `/api/scans`, group by type, render |
| `loadSession(id)` | Load historical scan results |
| `loadSaved()` | Fetch saved properties |
| `goHome()` | Reset to initial state |
| `pollStatus()` | Poll `/api/scan/<id>/status` |

### CSS Design System

- **Background:** `#0a0a0a`
- **Surface:** `#111111` / `#111118`
- **Accent:** `#ff2233` (red)
- **Accent glow:** `rgba(255, 34, 51, 0.4)`
- **Text:** `#e8e8f0`
- **Muted:** `#888899`
- **Border:** `rgba(255, 255, 255, 0.06)`
- **Green:** `#44ff66` (good deals, high scores)
- **Amber:** `#ffaa00` (medium scores)
- **Magenta:** `#ff44aa` (flags, brain output)
- **Fonts:** `'Orbitron'` for headings, `'Inter'` for body
- **Border radius:** 12px cards, 8px inputs/buttons

---

## 15. Rate Limiting & Anti-Bot

**File:** `regog/utils/rate_limiter.py`

### Per-Source Rate Limits (from `config.py`):

```python
{
    "realtor": {"delay_min": 2, "delay_max": 5, "max_per_hour": 200},
    "redfin": {"delay_min": 1, "delay_max": 3, "max_per_hour": 300},
    "zillow": {"delay_min": 4, "delay_max": 9, "max_per_hour": 60},
    "assessor": {"delay_min": 3, "delay_max": 8, "max_per_hour": 100},
}
```

### Features:
1. **Minimum delay** between requests per source
2. **Hourly cap** enforcement (rolling 1-hour window)
3. **Random jitter** within configured delay range
4. **Exponential backoff** on consecutive errors: `base * 2^(errors-1)` capped at 60s
5. **Success/error reporting** — `report_success()` resets error counter

### Zillow Stealth (separate in `zillow_stealth.py`):

- Playwright with randomized viewport, user agent, locale, timezone
- `playwright-stealth` plugin to hide automation fingerprints
- Human-like scrolling behavior
- Random delays between actions
- **Unique import pattern:** `from utils.rate_limiter import rate_limit as _shared_rate_limit, report_success as _report_success, report_error as _report_error` — this aliasing pattern is unique to `zillow_stealth.py` and not used in any other scraper

---

## 16. Scheduler

**File:** `regog/scheduler/scan_scheduler.py`

- Wraps APScheduler for recurring scans
- Runs in background thread
- Configurable interval (default 24h)
- Runs the same pipeline as CLI/web scans

---

## 17. Testing

**86 tests total** across 4 files:

### `tests/test_residential_score.py` (~40+ tests)
- `TestBaselineScore` — standard property, signal presence, positive values
- `TestPriceDeviation` — deep discount (40pts), slight discount (16pts), overpriced (0pts), None→0
- `TestDaysOnMarket` — 0-30=15, 31-90=10, 91-180=5, 180+=2, None→15
- `TestAssessorGap` — big gap=20pts, small gap~6.06, negative gap=0, missing→5
- `TestCondition` — all classifications map to correct scores
- `TestFloodPenalty` — X=10, AE=3, A=4, VE=0, None=8
- `TestPermitRisk` — low=+3, unknown=0, medium=-2, high=-5, JSON string parsing
- `TestTierAssignment` — HOT threshold, SKIP, DISTRESSED_ override
- `TestEdgeCases` — empty dict, all None, exact boundaries
- `TestDataTypes` — return structure validation

### `tests/test_land_score.py`
- Buildable zoning (20pts), non-buildable (2pts)
- Small parcel premium (10pts), large parcel discount (2pts)
- Empty dict defaults

### `tests/test_utils.py`
- `assign_tier`: all thresholds, boundaries, negative scores
- `parse_flags`: list identity, JSON strings, None, invalid JSON

### `tests/test_permit_scraper.py`
- No description → unknown risk
- Unpermitted addition → high risk
- Code violations → high risk
- Permitted renovation → low risk
- Mixed signals → high risk wins
- Case insensitivity, edge cases

---

## 18. UI Aesthetic Rules

### Terminal (Rich)

```python
# Table styling
table = Table(
    box=box.HEAVY_HEAD,
    border_style="red",
    header_style="bold red",
    show_lines=True,
)
```

**Tier colors:** HOT=bold red, WARM=bold yellow, NEUTRAL=white, RISKY=bold magenta, SKIP=dim

### Web HTML

- **Dark theme** — near-black with red accents
- **Logo** uses `Orbitron` font with gradient `#ff2233 → #ff4466`
- **SCAN button** has red gradient with glow shadow: `0 0 12px var(--accent-dim)`
- **HOT cards** have red border glow: `box-shadow: 0 0 12px rgba(255, 34, 51, 0.08)`
- **Score colors:** ≥70 green, ≥50 amber, <50 red
- **Property cards** animate in with `slideIn` keyframe
- **Badges:** HOT = red gradient, WARM = amber gradient
- **Values** displayed in `#ff4466` (bright red-pink)
- **Labels** in `#aaaacc` (muted lavender)
- **Stats bar** shows live count during scan with green color
- **Segmented score bar** breaks down component scores with colored sections
- **History** groups scans by type with icons (🏠 🌲 🏢)

---

## 19. Critical Rules & Gotchas

### MUST DO — DB Safety

1. **`style` and `property_url` are NOT in the SQLite schema.**
   - Before every `upsert_property()` call in ALL pipelines (web, CLI CLI, scheduled):
     ```python
     prop_url = prop.pop("property_url", None)
     prop_style = prop.pop("style", None)
     # ... upsert ...
     if prop_url is not None:
         prop["property_url"] = prop_url
     if prop_style is not None:
         prop["style"] = prop_style
     ```
   - In `web/app.py`, use `try/finally` to guarantee restoration:
     ```python
     prop_url = prop.pop("property_url", None)
     prop_style = prop.pop("style", None)
     try:
         upsert_property(conn, prop)
     finally:
         if prop_url is not None: prop["property_url"] = prop_url
         if prop_style is not None: prop["style"] = prop_style
     ```

2. **The fix exists in 3 places:** `web/app.py`, `regog/main.py` (cmd_scan + cmd_schedule)

### MUST DO — Comp Accuracy

3. **Style filter FIRST in comp engine.** A single-family home must NEVER be compared against condos.

4. **Sold comps have no price range filter.** A $50k listing gets compared against ALL sold comps in the area. This inflates deviations for cheap properties but is accepted behavior for V4.

5. **180-day sold lookback window.** Configurable but default is 180 days. Min 3 comps required.

### MUST DO — Web UI

6. **SSE stream must handle `event: complete` for cleanup.** Frontend sets `scanCompleted = true` to prevent double-fire.

7. **History groups by scan_type** with icons and formatted dates. Don't flatten to a simple list.

8. **Logo is clickable → `location.href='/'`** (not a link, uses onclick JS).

9. **Back button appears on scan complete** and calls `goHome()` which resets everything.

### Convention Rules

10. **Use `from config import ...` for all settings.** Never hardcode weights or thresholds.

11. **All functions must have type hints.** Return types required.

12. **JSON fields (red_flags, green_flags, price_history, permit_flags)** are auto-serialized by `database.py`. Don't manually JSON.stringify them.

13. **`normalize_listing()` uses `g(*keys)` to try multiple column names.** Always add new key variations when HomeHarvest changes its column names.

14. **Scan sessions use 8-char UUID** (first 8 chars of uuid4).

15. **Property listing_id falls back to `{source}_{hash(address + price)}`** if no property_id/listing_id available.

### HomeHarvest Specifics

16. **HomeHarvest's `style` column** returns property types like `SINGLE_FAMILY`, `CONDOS`, `TOWNHOMES`, `MULTI_FAMILY`, `LAND` — NOT the `property_type` filter parameter.

17. **`condo_townhome` filter returns ZERO results.** Use `condos` and `townhomes` separately.

18. **HomeHarvest is optional** — all scrapers check `HAS_HOMEHARVEST` flag and return `[]` gracefully if not installed.

19. **`property_url` from HomeHarvest** is the only reliable way to link to the actual Realtor.com listing. Zillow's `detail_url` is fragile.

### FEMA Specific

20. **Rate limit to 1 req/sec minimum.** Use cache keyed to 3-decimal-place (lat, lon).

21. **Retry up to 2 times** on HTTP errors with 2s delay.

22. **No API key needed** — the FEMA NFHL WMS is publicly accessible.

---

## Appendix A: Entry Points & Import Setup

### `serve_report.py` (the actual entry point)

```python
#!/usr/bin/env python3
"""
REGOG Web App Server — serves the full REGOG web application.
Run this, then open http://localhost:8080/ in your browser.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from web.app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
```

### Import Path Setup (CRITICAL)

Every entry point must add the project root to `sys.path` before any REGOG imports:

```python
# In serve_report.py:
sys.path.insert(0, os.path.dirname(__file__))

# In regog/main.py:
sys.path.insert(0, str(Path(__file__).parent))

# In web/app.py:
sys.path.insert(0, str(Path(__file__).parent.parent / "regog"))
sys.path.insert(0, str(Path(__file__).parent.parent))
```

### `__init__.py` Conventions

- All subdirectories (`scrapers/`, `db/`, `enrichment/`, `scoring/`, `ui/`, `utils/`, `scheduler/`, `tests/`) need an **empty** `__init__.py` file to be importable as Python packages.
- `regog/__init__.py` → empty (marks the package root)
- `web/__init__.py` → just needs to exist so `web/` is a Python package; actual content is just a comment `# REGOG Web App`. The `serve_report.py` entry point imports directly from `web.app`, not through the package init.

### Deferred Imports Pattern (CRITICAL)

Both `main.py` and `web/app.py` import heavy modules **inside functions**, not at module level:

```python
def cmd_scan(args):
    from db.database import get_connection, create_scan_session  # Inside function!
    from scrapers.homeharvest_scraper import fetch_listings
    # ... rest of function
```

**Why:** Because `sys.path` is modified at module level before any function is called. If imports were at the top of the file, they'd execute before `sys.path` is ready, causing `ModuleNotFoundError`.

### `skip_flood=True` Behavior

When `skip_flood=True` (which is the web app default):
- `enrich_property(prop, skip_flood=True)` immediately sets `prop["flood_zone"] = None`
- No FEMA API call is made
- The scoring engine then uses `FLOOD_SCORES.get(None, 8)` → 8 pts (slight penalty for unknown)
- CLI scans default to **not skipping** (FEMA runs) unless `--skip-flood` is passed

### Verification Steps for a New Build

After implementing:
```bash
# 1. Initialize the database
python -c "from db.database import init_db; init_db()"

# 2. Run tests (86 expected)
python -m pytest tests/ -v

# 3. Test the CLI with a small scan
python main.py scan residential --location "Dallas, TX" --price-max 400000 --limit 10

# 4. Start the web app
python serve_report.py
# → Open http://localhost:8080/

# 5. Run a scan from the web UI
# → Enter "Dallas, TX", price max 400000, click SCAN
# → Verify SSE stream, property cards, history, saved
```

---

## Appendix B: Key Data Points & Sources

| Data Point | Source | Method | Status |
|-----------|--------|--------|--------|
| Listings | HomeHarvest (Realtor.com) | `scrape_property(for_sale)` | ✅ Working |
| Sold Comps | HomeHarvest (Realtor.com) | `scrape_property(sold)` | ✅ Working |
| Property URL (listing) | HomeHarvest | `property_url` column | ✅ Working |
| Property Style | HomeHarvest | `style` column | ✅ Working |
| Lat/Lon | HomeHarvest | `latitude`, `longitude` | ✅ Working |
| Price/Sqft | HomeHarvest | `price_per_sqft` or computed | ✅ Working |
| Assessed Value | HomeHarvest | `assessed_value` | ⚠️ Sometimes null |
| Estimated Value | HomeHarvest | `estimated_value` | ⚠️ Sometimes null |
| FEMA Flood Zone | FEMA NFHL WMS | ArcGIS REST query by lat/lon | ✅ Working (free) |
| Permit Signals | Keyword inference | Description text analysis | ✅ Working |
| Zillow Listings | Playwright stealth | Browser automation | ⚠️ Optional, fragile |

### Price Deviation Formula

```
price_deviation_pct = ((list_price - comp_median_price) / comp_median_price) * 100
```

- **Negative** = listing is below median comp price = **GOOD DEAL**
- **Positive** = listing is above median = overpriced
- -50% deviation → max price_deviation score (40pts)
- -10% deviation → 8 pts for price_deviation

### Score Ranges

| Score | Tier | Color | Meaning |
|-------|------|-------|---------|
| ≥ 70 | HOT | Green score / Red badge | Screaming deal — act fast |
| ≥ 50 | WARM | Amber | Good opportunity |
| ≥ 35 | NEUTRAL | White | Consider with investigation |
| ≥ 20 | RISKY | Magenta (terminal only) | High risk, possibly distressed — **RISKY has no dedicated badge styling in the web UI** (renders as default badge) |
| < 20 | SKIP | Gray (terminal only) | Avoid — **SKIP has no dedicated badge styling in the web UI** (renders as default badge) |

---

*REGOG V4 — Built from scratch with Claude/Codebuff*
*All data sources: public, free, no API keys required*
*86 passing tests · SQLite · Flask SSE · Style-filtered comps · Dark UI*
