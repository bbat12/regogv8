# REGOG REBUILD V6 — Complete From-Scratch Handoff

> **Purpose:** A new CLI agent (Codebuff/Claude) with **ZERO knowledge** of this project must be able to rebuild the entire REGOG application from scratch using this document alone. Every detail, problem, fix, convention, and gotcha is included.

---

## 📋 TABLE OF CONTENTS

1. [Application Overview](#1-application-overview)
2. [Current State & Conventions](#2-current-state--conventions)
3. [Project Structure](#3-project-structure)
4. [Quick Start (from scratch)](#4-quick-start-from-scratch)
5. [Configuration (config.py)](#5-configuration-configpy)
6. [Database (db/)](#6-database-db)
7. [Entry Points & Import Paths](#7-entry-points--import-paths)
8. [Scan Pipeline (the core loop)](#8-scan-pipeline-the-core-loop)
9. [HomeHarvest Scraper — Active Listings](#9-homeharvest-scraper--active-listings)
10. [Redfin Scraper — Sold Comps](#10-redfin-scraper--sold-comps)
11. [Optional Scrapers (Zillow, Redfin Playwright, Craigslist)](#11-optional-scrapers-zillow-redfin-playwright-craigslist)
12. [FEMA Flood Zone Scraper](#12-fema-flood-zone-scraper)
13. [Brain Classifier (keyword-based, no LLM)](#13-brain-classifier-keyword-based-no-llm)
14. [Listing Filter](#14-listing-filter)
15. [Acreage Enricher](#15-acreage-enricher)
16. [Comp Engine (2D Expansion Search)](#16-comp-engine-2d-expansion-search)
17. [Scoring Modules (Residential / Land / Commercial)](#17-scoring-modules-residential--land--commercial)
18. [Scoring Utilities](#18-scoring-utilities)
19. [Web App Backend (Flask + SSE)](#19-web-app-backend-flask--sse)
20. [Web Frontend (Single-Page HTML)](#20-web-frontend-single-page-html)
21. [CLI (main.py)](#21-cli-mainpy)
22. [Lava Search Mode](#22-lava-search-mode)
23. [Mode Separation (Regular vs Lava)](#23-mode-separation-regular-vs-lava)
24. [Utility Modules](#24-utility-modules)
25. [Tests](#25-tests)
26. [ALL KNOWN PROBLEMS & HOW THEY WERE FIXED](#26-all-known-problems--how-they-were-fixed)
27. [Problems That STILL EXIST](#27-problems-that-still-exist)

---

## 1. Application Overview

**REGOG** (Real Estate Go/No-Go) is a nationwide US real estate intelligence scanner that:

1. **Scrapes** active listings from Realtor.com (free, via HomeHarvest library)
2. **Fetches** sold comparable properties for the same market
3. **Classifies** each property via keyword matching (no LLM needed)
4. **Enriches** with flood zone data (free FEMA API), permit signals, and acreage estimates
5. **Computes comparable sales** using a 2D expansion search (radius × time)
6. **Scores** each property 0-100+ across 5-6 signals (residential/land/commercial variants)
7. **Displays** results via a dark-themed Flask web app with real-time SSE streaming, OR a Rich CLI terminal

**Stack:** Python 3.11+ · SQLite · Flask · HomeHarvest · Playwright · Rich · Jinja2

**Zero API costs** — every data source is free and requires no API key.

---

## 2. Current State & Conventions

### Git State

- **Tags:** v6, v7
- **Latest commit (v7):** Stacked mode boxes with per-mode scan buttons
- **17 commits** total from initial through V7
- **98 tests** passing

### Coding Conventions

- **Type hints** required on all functions
- **Deferred imports** — heavy modules imported INSIDE functions (not at module top), because `sys.path` is modified at module level before any function is called
- **Config-driven** — all thresholds, weights, and settings in `regog/config.py`, never hardcoded
- **`g(*keys)` pattern** in normalizers — tries multiple possible column names, returns first non-None
- **`_fb_` prefix** for metadata keys in scores dicts — filtered out when summing numeric scores
- **In-memory cache** for FEMA flood zones and county lookups
- **`__init__.py`** needed in ALL subdirectories for Python package imports

### The Two Entry Points

1. **`serve_report.py`** (port 8080, non-debug, threaded) — the web app entry point
2. **`python regog/main.py`** — the CLI entry point

Both call `init_db()` which runs schema + migrations.

### Critical Import Pattern

```python
# serve_report.py:
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "regog"))

# regog/main.py:
sys.path.insert(0, str(Path(__file__).parent))

# web/app.py:
sys.path.insert(0, str(Path(__file__).parent.parent / "regog"))
sys.path.insert(0, str(Path(__file__).parent.parent))
```

---

## 3. Project Structure

```
/workspaces/REgog/
├── REGOG_REBUILD_V6.md          ← THIS FILE
├── REGOG_V5_REBUILD.md          ← Previous rebuild guide (V5 era)
├── REGOG_V4_Build_Prompt.md     ← Original V4 build instructions
├── REGOG_V5_FIXES.md            ← V5 scoring fix instructions
├── REGOG_Comprehensive_Analysis_Audit.md  ← 3-dev debug session
├── REGOG_Architecture_Deep_Dive.md        ← Architecture doc
├── REGOG_Board_Meeting_Q2_2026.md        ← Board meeting findings
├── REGOG_V4_Three_Dev_Zero_Results_Debug_Analysis.md  ← Zero-results bug
├── REGOG_Deal_Audit.md          ← (may not exist, is referenced)
├── REGOG_Scan_Analysis_and_Debate.md     ← (may exist)
├── REGOG_Billings_Scan_Report.md         ← (may exist)
├── README.md                    ← Minimal
├── serve_report.py              ← ENTRY POINT: starts Flask web app on port 8080
├── regog.db                     ← SQLite database (auto-created, gitignored)
├── regog_config.json            ← Config overrides (auto-created, gitignored)
├── regog_report.html            ← Generated HTML report (gitignored)
│
├── regog/                       ← Main Python package
│   ├── __init__.py              ← Empty
│   ├── config.py                ← ALL settings, weights, thresholds
│   ├── main.py                  ← CLI entry point (argparse)
│   ├── requirements.txt         ← (may not exist — deps listed below)
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.sql           ← CREATE TABLE + indexes + migrations
│   │   └── database.py          ← SQLite wrapper: init, CRUD, upsert, migrations
│   │
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── homeharvest_scraper.py   ← fetch_listings() + normalize_listing()
│   │   ├── redfin_scraper.py        ← fetch_sold_comps() (uses HomeHarvest for sold)
│   │   ├── zillow_stealth.py        ← Playwright-based Zillow scraper
│   │   ├── redfin_playwright.py     ← Playwright Redfin browser scraper
│   │   ├── craigslist_scraper.py    ← HTTPX+BS Craigslist FSBO scraper
│   │   ├── fema_scraper.py          ← FEMA flood zone API
│   │   ├── assessor_scraper.py      ← Assessor data + county registry
│   │   └── permit_scraper.py        ← Permit signal inference
│   │
│   ├── enrichment/
│   │   ├── __init__.py
│   │   ├── brain.py                 ← Keyword property classifier
│   │   ├── comp_engine.py           ← 2D expansion comp search
│   │   ├── enricher.py              ← Orchestrates enrichment
│   │   ├── listing_filter.py        ← Filters junk listings
│   │   ├── acreage_enricher.py      ← Acreage fallback enrichment
│   │   └── geocoder.py              ← DEAD CODE — never called
│   │
│   ├── scoring/
│   │   ├── __init__.py
│   │   ├── utils.py                 ← Shared: tiers, fallback, confidence, variance
│   │   ├── residential_score.py     ← 0-100 scoring for homes
│   │   ├── land_score.py            ← 0-100 scoring for land
│   │   └── commercial_score.py      ← 0-100 scoring for commercial
│   │
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── scan_scheduler.py        ← APScheduler recurring scans
│   │
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── terminal.py              ← Rich console output
│   │   ├── report_generator.py      ← Jinja2 HTML report
│   │   └── templates/
│   │       └── report.html.j2
│   │
│   └── utils/
│       ├── __init__.py
│       ├── property_type.py         ← Style→category mapping
│       ├── density.py               ← ZIP→urban/suburban/rural
│       ├── rate_limiter.py          ← Per-source request throttling
│       ├── config_store.py          ← JSON config file
│       ├── dedup.py                 ← Address-based dedup
│       └── location_resolver.py    ← Colloquial→City,ST resolution
│
├── web/
│   ├── __init__.py
│   ├── app.py                      ← Flask backend: all API + SSE + background scans
│   └── static/
│       └── index.html              ← Single-page dark UI (all CSS+JS inline)
│
└── tests/
    ├── __init__.py
    ├── conftest.py                 ← 5 fixtures (standard, hot, skip, missing, distressed)
    ├── test_residential_score.py   ← 50+ tests
    ├── test_land_score.py          ← Land scoring tests
    ├── test_scoring_fallback.py    ← _fb_ fallback tests
    ├── test_utils.py               ← assign_tier + parse_flags tests
    └── test_permit_scraper.py      ← Permit inference tests
```

---

## 4. Quick Start (from scratch)

```bash
# 1. Environment
cd /workspaces/REgog
python3 -m venv venv && source venv/bin/activate

# 2. Dependencies
pip install homeharvest beautifulsoup4 httpx lxml sqlite-utils rich geopy apscheduler jinja2 playwright flask flask-cors
playwright install chromium  # for Zillow/Redfin scrapers

# 3. Init database
python3 -c "from db.database import init_db; init_db()"

# 4. Run tests (98 expected)
python -m pytest tests/ -v --tb=short

# 5. Start web app
python3 serve_report.py
# → http://localhost:8080/

# 6. Or use CLI:
python3 regog/main.py scan residential --location "Dallas, TX" --price-max 400000 --limit 10
python3 regog/main.py leads --tier HOT
```

---

## 5. Configuration (config.py)

**ALL tunable parameters in ONE file:** `regog/config.py`

### DB_PATH — **MUST BE ABSOLUTE**

```python
from pathlib import Path
DB_PATH = str(Path(__file__).parent.parent / "regog.db")  # ABSOLUTE path
```

**CRITICAL:** This was previously relative (`"regog.db"`) which caused a **dual-database bug** where the CLI and web app wrote to different SQLite files. CLI resolved to `regog/regog.db`, web app resolved to `regog.db`. Both had different data and different schema versions.

### Scoring Weights

```python
RESIDENTIAL_WEIGHTS = {
    "price_deviation": 0.40,   # 40 pts max
    "dom_signal": 0.15,        # 15 pts max
    "assessor_gap": 0.20,      # 20 pts max
    "condition": 0.15,         # 15 pts max
    "flood_penalty": 0.10,     # 10 pts max
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

### Lead Tiers (EVOLVED — changed from V4→V5)

```python
# V4 had HOT≥70, WARM≥50, NEUTRAL≥35, RISKY≥20, SKIP<20
# V5 changed to: HOT≥100, MEDIUM≥50, WARM≥0, SKIP<0
# NOTE: RISKY tier was REMOVED. Current thresholds:
TIER_THRESHOLDS = {
    "HOT": 100,   # Only scores above 100 qualify
    "MEDIUM": 50, # 50-100: solid leads
    "WARM": 0,    # 0-49: low priority
}
# Negative scores → SKIP
```

### Comp Engine

```python
MIN_COMPS_REQUIRED = 5        # Minimum comps before accepting
COMP_LOOKBACK_TIERS = [180, 270, 365, 540, 730]  # 2 years max
COMP_STALENESS_PENALTY = 0.15  # 15% confidence reduction when lookback > 365d
COMP_CONFIDENCE_HIGH = 0.80
COMP_CONFIDENCE_MEDIUM = 0.50
COMP_CONFIDENCE_LOW = 0.00
```

### Comp Radii (3 tiers per density × category)

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

### Scoring Maps

```python
FLOOD_SCORES = {
    "X": 10,        # Minimal risk — no penalty
    "AE": 3,        # High risk — 7pt penalty
    "A": 4,
    "VE": 0,        # Coastal extreme — full penalty
    "UNKNOWN": 0,   # No data — ZERO penalty. Never penalize for missing data.
    None: 0,        # Same fix — was 8, changed to 0 (Part 1 fix)
}
# CRITICAL: FLOOD_SCORES[None] WAS 8. Changed to 0 in Part 1 fix.
# The old default penalized every property 8 pts when flood zone was unknown.
# Since FEMA data is unreliable and often missing for rural areas, this was
# unfairly tanking scores.

CONDITION_SCORES = {
    "standard": 15, "luxury": 12, "vacant": 10,
    "distressed": 7, "teardown": 4, "fire_damage": 3,
}

PERMIT_SCORES = {"low": 3, "unknown": 0, "medium": -2, "high": -5}

DOM_SCORE_BRACKETS = [
    (30, 15),     # 0-30 days → 15 pts
    (90, 10),     # 31-90 days → 10 pts
    (180, 5),     # 91-180 days → 5 pts
    (365, 2),     # 181-365 days → 2 pts
    (float("inf"), 0),  # 365+ → 0 pts (was 2, now 0 to enable SKIP)
]
```

### Brain Classifier Keywords

```python
CLASSIFICATION_KEYWORDS = {
    "distressed": ["distressed", "as-is", "needs work", "fixer-upper", "deferred maintenance", ...],
    "teardown": ["teardown", "land value", "demolish", "knockdown", ...],
    "fire_damage": ["fire damage", "smoke damage", "burnt", "structure fire", ...],
    "vacant": ["vacant", "abandoned", "boarded up", ...],
    "luxury": ["luxury", "high-end", "estate", "waterfront", "gourmet kitchen", ...],
}

SELLER_MOTIVATION_KEYWORDS = {
    "high": ["motivated seller", "must sell", "relocation", "divorce", "estate sale", "short sale", "price reduced", ...],
    "medium": ["open to offers", "flexible", "offers encouraged"],
}

RED_FLAG_KEYWORDS = ["foundation issues", "structural", "mold", "termites", "roof leak", ...]
GREEN_FLAG_KEYWORDS = ["renovated", "updated", "new roof", "new hvac", "move-in ready", ...]
```

### Rate Limits

```python
RATE_LIMITS = {
    "realtor":    {"delay_min": 2,  "delay_max": 5,  "max_per_hour": 200},
    "redfin":     {"delay_min": 1,  "delay_max": 3,  "max_per_hour": 300},
    "zillow":     {"delay_min": 4,  "delay_max": 9,  "max_per_hour": 60},
    "assessor":   {"delay_min": 3,  "delay_max": 8,  "max_per_hour": 100},
    "craigslist": {"delay_min": 3,  "delay_max": 7,  "max_per_hour": 80},
}
```

### Dynamic Comp Pool Sizing (Part 4 fix)

```python
SOLD_COMPS_BASE = 300          # minimum pool size
SOLD_COMPS_PER_LISTING = 0.15  # 15% of active listing count
SOLD_COMPS_MAX = 2000          # hard cap

def get_comp_pool_size(active_listing_count: int) -> int:
    dynamic_size = int(active_listing_count * SOLD_COMPS_PER_LISTING)
    return max(SOLD_COMPS_BASE, min(dynamic_size, SOLD_COMPS_MAX))
```

### High-Rise Detection

```python
HIGH_RISE_MIN_STORIES = 5  # CONDOs with >=5 stories → reclassified as commercial
```

---

## 6. Database (db/)

### schema.sql

Three tables:
- **`properties`** — 65+ columns (all scoring, comp, enrichment, and metadata fields)
- **`scan_sessions`** — id, started_at, completed_at, scan_type, search_params (JSON), properties_found, hot_leads_found
- **`price_history_tracking`** — id, listing_id, recorded_at, price, days_on_market

### Indexes
```sql
idx_properties_listing_id, idx_properties_scan_session,
idx_properties_tier, idx_properties_score, idx_properties_location
```

### JSON Fields (auto-serialized by database.py)

```python
_JSON_FIELDS = {
    "brain_red_flags",    # list → JSON string on write, ← parsed on read
    "brain_green_flags",
    "price_history",
    "permit_flags",
    "comp_listings",
}
```

### Key Functions in database.py

| Function | Purpose |
|----------|---------|
| `init_db()` | Reads schema.sql, runs `_run_migrations()`, `_fix_corrupted_tiers()` |
| `_run_migrations()` | ALTER TABLE ADD COLUMN for 20+ columns (non-destructive) |
| `_fix_corrupted_tiers()` | Fixes `DISTRESSED_HOT` → `HOT` (Part 3 fix) |
| `create_scan_session()` | INSERT, returns 8-char UUID |
| `complete_scan_session()` | Updates completed_at + counts |
| `upsert_property()` | INSERT OR UPDATE by listing_id |
| `get_session_properties()` | SELECT * for session, ORDER BY score DESC |
| `get_stats()` | Total, hot, warm, sessions, avg_score |
| `search_properties()` | Filtered search with all optional params |

### Lava Columns (added V7)

```sql
lava_profit_pct REAL
lava_profit_ratio REAL
lava_city TEXT
```

These store Lava Search metadata — the profit percentage, ratio, and source city for nationwide lava scans.

---

## 7. Entry Points & Import Paths

### serve_report.py (THE main entry point)

```python
#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "regog"))

from db.database import init_db
init_db()  # RUNS MIGRATIONS — CRITICAL for new columns!

from web.app import app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
```

### Deferred Imports Pattern

**BOTH** `main.py` and `web/app.py` import heavy modules INSIDE functions:

```python
def cmd_scan(args):
    from db.database import get_connection, create_scan_session  # Inside function!
    from scrapers.homeharvest_scraper import fetch_listings
    # ...
```

**Why:** `sys.path` is modified at module level before any function runs. Top-level imports would execute before `sys.path` is ready → `ModuleNotFoundError`.

---

## 8. Scan Pipeline (the core loop)

Both CLI and web app follow the same pipeline:

```
1. Fetch SOLD comps ──── redfin_scraper.fetch_sold_comps(location, scan_type)
   (up to dynamic pool size: max(base=300, count*0.15, cap=2000))

2. Fetch ACTIVE listings ─ homeharvest_scraper.fetch_listings(location, for_sale)

3. (Optional secondary scrapers) ─ Zillow, Redfin Playwright, Craigslist

4. Deduplicate (if secondary sources used)

5. For EACH listing:
   a. normalize_listing(raw_dict → property schema with ~30 fields)
   b. Price filter (skip if outside min/max)
   c. Brain classify (keyword-based)
   d. Listing filter (skip auctions/bait, flag burned/demolition)
   e. Enrich (acreage → assessor → FEMA flood → permits)
   f. Calculate comps (2D expansion: radius × time)
   g. Score (residential/land/commercial)
   h. upsert_property(conn, prop) → DB
   i. (web app only) push to SSE queue

6. complete_scan_session()
```

### Property Type Mapping (for HomeHarvest API)

```python
property_types = {
    "residential": ["single_family", "mobile"],
    "land":        ["land"],
    "commercial":  ["multi_family", "apartment", "condos", "townhomes", "duplex_triplex", "farm"],
}.get(scan_type)
```

---

## 9. HomeHarvest Scraper — Active Listings

**File:** `regog/scrapers/homeharvest_scraper.py`

### fetch_listings(location, listing_type, past_days, property_type)

- Calls `homeharvest.scrape_property()` → returns pandas DataFrame
- Converts to list of dicts
- Returns `[]` if homeharvest not installed (graceful)

### normalize_listing(raw, source, scan_session_id, scan_type) → dict

**THE MOST CRITICAL normalization function.** Maps HomeHarvest's varied column names to REGOG's schema.

Uses the `g(*keys)` helper pattern:

```python
def g(*keys):
    for k in keys:
        v = raw.get(k)
        if v is not None:
            return v
    return None
```

**Partial field mapping (each tries multiple key names):**

| REGOG Field | HomeHarvest Keys Tried |
|------------|----------------------|
| `listing_id` | `property_id`, `listing_id`, `mls_id`, `id` → fallback: `{source}_{hash(address+price)}` |
| `style` | `style`, `property_type`, `home_type` — **CRITICAL for comp matching** |
| `address` | `full_street_line`, `street`, `address`, `full_address`, `formatted_address` |
| `list_price` | `list_price`, `price`, `current_price`, `sold_price` |
| `sqft` | `sqft`, `square_feet`, `sq_ft`, `living_area`, `building_area` |
| `acres` | `acres`, `acreage`, `lot_size_acres`, `lot_acres`, `total_acres`, `parcel_acres`, `land_area`, `land_acres`, `area_acres`, `gross_acres`, `net_acres`, `lot_area_acres` |
| `property_url` | `property_url`, `rdc_web_url`, `href`, `url` |
| `estimated_value` | `estimated_value`, `value`, `zestimate`, `avm_value` |
| `assessed_value` | `assessed_value`, `tax_assessment`, `assessed_valuation` |
| `listing_description` | `description`, `listing_description`, `text`, `remarks`, `public_remarks` |
| `primary_photo` | `primary_photo`, `photo`, `image_url`, `thumbnail_url` |
| `stories` | `stories`, `num_stories`, `floors`, `total_stories` |

**Acres fallback:** If acres is still None, derive from `lot_sqft` / 43560.
**Sqft fallback for land:** If no sqft but has acres, sqft = acres * 43560.

**⚠️ This file ALSO has a STALE `fetch_sold_comps()` that returns `[]`. Do NOT use it.** The real sold comps function is in `redfin_scraper.py`.

---

## 10. Redfin Scraper — Sold Comps

**File:** `regog/scrapers/redfin_scraper.py`

### fetch_sold_comps(location, scan_type, past_days=180, limit=200) → list[dict]

- Uses HomeHarvest under the hood with `listing_type="sold"`
- Returns up to `limit` sold comps
- Normalized via `normalize_sold_listing()` — **NOT** `normalize_listing()`

### normalize_sold_listing(raw, scan_type) → dict | None

**Explicitly handles sold-specific column names:**
- `list_price` → tries `sold_price`, `last_sold_price`, `close_price`, `sale_price`, `price`, `list_price`
- `last_sold_date` → tries `last_sold_date`, `sold_date`, `close_date`, `closing_date`
- `listing_status` → forced to `"sold"`
- Returns `None` if no `sold_price` (critical field)

**⚠️ `fetch_sold_comps_near_coords()` is defined TWICE in this file** — both return `[]`. HomeHarvest doesn't support coordinate-based queries.

---

## 11. Optional Scrapers

### Zillow (zillow_stealth.py)

- Playwright-based with anti-bot: stealth plugin, viewport/UA/locale randomization, human-like scrolling
- 3 extraction methods: Next.js JSON → Apollo GraphQL → DOM fallback
- Activated with `--use-zillow`
- **Unique import pattern:** `from utils.rate_limiter import rate_limit as _shared_rate_limit`

### Redfin Playwright (redfin_playwright.py)

- Playwright browser fallback for Redfin
- 2 methods: embedded JSON → DOM fallback
- Activated with `--use-redfin`

### Craigslist (craigslist_scraper.py)

- HTTPX + BeautifulSoup for FSBO/motivated seller listings
- Maps 20+ cities via `CL_CITY_MAP`
- Activated with `--use-craigslist`

### Deduplication (utils/dedup.py)

When multiple sources are used, `merge_and_deduplicate()` normalizes addresses and removes duplicates. Primary source (HomeHarvest) wins on conflicts.

---

## 12. FEMA Flood Zone Scraper

**File:** `regog/scrapers/fema_scraper.py`

### get_flood_zone(lat, lon) → str | None

**Endpoint:** `https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query`

**Query params:** `geometry={lon},{lat}`, `geometryType=esriGeometryPoint`, `spatialRel=esriSpatialRelIntersects`, `outFields=FLD_ZONE,ZONE_SUBTY,SFHA_TF`, `returnGeometry=false`, `f=json`

**Features:**
- Cached by (lat, lon) rounded to 4 decimal places (~10m resolution)
- 0.5s min delay between requests
- 2 retries with 1s backoff
- Returns zone code: `X` (minimal risk), `AE`/`A` (high risk), `VE` (coastal extreme), or `"UNKNOWN"`

**KNOWN PROBLEM (FIXED):** The original NFHL API used a different JSON geometry format that caused all queries to fail. Rewritten with the simpler `esriGeometryPoint` format. Also, `FLOOD_SCORES[None]` was changed from 8 to 0 — the old default unfairly penalized every property 8 points when flood data was missing.

---

## 13. Brain Classifier (keyword-based, no LLM)

**File:** `regog/enrichment/brain.py`

### classify_property(address, scan_type, list_price, sqft, year_built, days_on_market, description) → dict

**Classification priority order:** fire_damage > teardown > distressed > vacant > luxury > standard > land_only

**Returns:**
```python
{
    "classification": "standard" | "luxury" | "distressed" | "teardown" | "fire_damage" | "vacant" | "land_only",
    "confidence": float,            # 0.0-1.0, increments per matched keyword
    "red_flags": [str],             # Matched RED_FLAG_KEYWORDS
    "green_flags": [str],           # Matched GREEN_FLAG_KEYWORDS
    "seller_motivation": "high" | "medium" | "low",
    "motivation_signals": [str],    # Matched keyword phrases
    "estimated_condition": str,     # Maps classification
    "is_luxury": bool,
    "notes": str,                   # Human-readable summary
}
```

If `scan_type == "land"`, classification is forced to `"land_only"`.

---

## 14. Listing Filter

**File:** `regog/enrichment/listing_filter.py`

Filters out junk listings before scoring. Order matters — first match wins:

1. **`check_auction`** → `skip`: "foreclosure auction", "opening bid", "sheriff sale"
2. **`check_bait_price`** → `skip`: Price < $1K, or < $10K + residential + no sqft
3. **`check_burned`** → `flag`: "burnt", "fire damaged", "structure fire"
4. **`check_demolition`** → `flag`: "must demolish", "condemned", "uninhabitable"
5. **`check_land_masquerade`** → `flag`: Houses listed as land/lots

Returns: `{"action": "skip" | "flag", "reason": "...", "filter_type": "auction"|"bait"|"burned"|"demolition"|"land_masquerade"}`

---

## 15. Acreage Enricher

**File:** `regog/enrichment/acreage_enricher.py` (added in Part 1 fix)

Fills missing acreage from 4 fallback sources:

1. Compute from `lot_sqft` / 43560
2. Parse from `listing_description` via regex: `"1.5 acres"`, `"0.25 AC"`, `"43,560 sq ft"`
3. Parse from title/address text
4. Estimate from price-based heuristic (for land-only listings)

When acreage is estimated (not measured), sets `acres_estimated = True` and the land scoring applies a **30% penalty** to the price-per-acre deviation.

---

## 16. Comp Engine (2D Expansion Search)

**File:** `regog/enrichment/comp_engine.py` — THE CORE DEAL-FINDING LOGIC

### How it works

For each active listing, the engine finds comparable sold properties using a **two-dimensional expansion search**: first tries all radius tiers, then expands the lookback window.

### Algorithm (in order):

**Step 1: Style filter** — Only compare apples-to-apples:
```python
style_map = {
    "SINGLE_FAMILY": ["SINGLE_FAMILY", "MANUFACTURED", "MOBILE"],
    "CONDOS": ["CONDOS"], "TOWNHOMES": ["TOWNHOMES"],
    "MULTI_FAMILY": ["MULTI_FAMILY", "APARTMENT"],
    "LAND": ["LAND"], "FARM": ["FARM", "LAND"],
    ...
}
```

**Step 2: 2D Expansion Search** — `find_comps_with_expansion()`

Outer loop = time windows `[180, 270, 365, 540, 730]` days
Inner loop = radius tiers `[r1, r2, r3, r3×2, r3×4, ... up to 100mi]`

```python
# Example for suburban residential: r1=0.5, r2=1.0, r3=1.5
# Search order:
#   180d/0.5mi → 180d/1.0mi → 180d/1.5mi → 180d/3mi → 180d/4.5mi → ...
#   270d/0.5mi → 270d/1.0mi → ...
#   ...up to 730d/100mi
```

Requires `MIN_COMPS_REQUIRED` (5) comps before accepting.

**Step 3: Similarity filters** (if 5+ comps remain):
- Sqft: ±30% for residential/commercial
- Beds/baths: ±1 for residential
- Acres: ±50% for land
- If filtering reduces comps below 5, uses unfiltered set

**Step 4: Land acreage pre-filter** — For land, filters by ±50% acres BEFORE expansion. If the acreage-filtered pool has ≥5 comps, only searches within that pool. Otherwise falls back to all-acreage pool.

**Step 5: Calculate medians** — price, $/sqft, $/acre

**Step 6: Calculate price_deviation_pct:**
```python
price_deviation_pct = ((target_price - comp_median) / comp_median) * 100
# NEGATIVE = below median = GOOD DEAL
```

**Step 7: Variance metrics** — `comp_price_range`, `comp_price_stddev`, `comp_variance_high` (true when range/median > 50%)

**Step 8: Confidence calculation** — `calculate_comp_confidence(count, tier, lookback)`
- 1.0 base, subtracts for: low count, expanded radius, long lookback
- ≥0.80 → HIGH, ≥0.50 → MEDIUM, <0.50 → LOW

**Step 9: Top comps** — 10 nearest-price comps with full details for clickable display

### Return dict fields:
```python
{
    "comp_median_price": int, "comp_count": int,
    "comp_radius_miles": float, "comp_tier_used": int,
    "comp_lookback_used": int,
    "comp_price_per_sqft_median": float, "comp_price_per_acre_median": float,
    "price_deviation_pct": float,  # negative = below median = good deal
    "comp_confidence": float, "comp_confidence_label": "HIGH"|"MEDIUM"|"LOW",
    "comp_staleness_penalty_applied": bool,
    "comp_price_range": float, "comp_price_stddev": float,
    "comp_variance_high": bool,
    "comp_acreage_matched": bool,  # True if acreage pre-filter succeeded
    "comp_category": str, "comp_density": str,
    "comp_listings": list[dict],  # Top 10 comps
}
```

---

## 17. Scoring Modules

### Residential Score (residential_score.py)

**6 components + 3 post-processing steps:**

**Components:**
1. **price_deviation** (40 pts max): Percentile-band scoring
   - ≤-60% → 40, ≤-50% → 36, ≤-40% → 32, ≤-30% → 26, ≤-20% → 20, ≤-10% → 13, ≤-5% → 7, ≤0 → 3, ≤+10% → 0, >+10% → -5
   - LOW confidence → ×0.5, MEDIUM → ×0.75

2. **dom_signal** (15 pts): 0-30d=15, 31-90d=10, 91-180d=5, 181-365d=2, 365+=0

3. **assessor_gap** (20 pts): `max(0, min(20, (gap_pct/30)*20))`. Missing=5

4. **condition** (15 pts): standard=15, luxury=12, vacant=10, distressed=7, teardown=4, fire_damage=3

5. **flood_penalty** (0-10): X=10, AE=3, A=4, VE=0, UNKNOWN/None=0

6. **permit_risk** (-5 to +3): low=+3, unknown=0, medium=-2, high=-5

**Post-processing (from scoring/utils.py):**
7. **comp_fallback**: If comp_count=0, use `estimated_value` as proxy
8. **confidence_cap**: LOW→cap at 10, MEDIUM→cap at 20
9. **variance_penalty**: comps<5 + variance_high → 25% reduction

**Tier:** ≥100=HOT, ≥50=MEDIUM, ≥0=WARM, <0=SKIP

### Land Score (land_score.py)

**7 components:**
1. **price_per_acre_deviation** (40 pts): Same percentile bands as residential, but against $/acre
   - If acres=NULL/0: returns 0 (DO NOT use total price as proxy)
   - If comps are significantly different size (<50% or >200% of target): 50% reduction
   - If acres_estimated: 30% penalty

2. **zoning_bonus** (20 pts): Buildable=20, Non-buildable=2, Unknown=10

3. **assessor_gap** (20 pts): Uses PPA heuristic if no assessed_value:
   - $/acre < $5K → 12, <$15K → 8, <$30K → 4, else 0

4. **road_access_bonus** (10 pts): From brain_green_flags

5. **utilities_bonus** (10 pts): From brain_green_flags

6. **acreage_premium** (10 pts): ≤1ac=10, ≤5ac=8, ≤10ac=6, ≤40ac=4, >40ac=2

7. **flood_penalty** (0-10): Same as residential

**Fallback when acres=NULL:** Redistributes weight, caps below HOT, data_confidence=LOW

### Commercial Score (commercial_score.py)

**5 components:**
1. **price_deviation** (35 pts): Scaled from 40→35
2. **assessor_gap** (25 pts): For skyscrapers, uses tighter (gap/20) instead of (gap/30)
3. **cap_rate_estimate** (20 pts): GRM-based estimator using market rent estimates
4. **condition** (10 pts): Scaled from CONDITION_SCORES (×10/15)
5. **flood_penalty** (0-10): Same

### Cap Rate Estimator (commercial_score.py)

Uses Gross Rent Multiplier (GRM) method with market-average rent estimates:

```python
MARKET_RENTS_PSF = {
    ("CA", "MULTI_FAMILY"): 2.50,
    ("TX", "MULTI_FAMILY"): 1.20,
    ("DEFAULT", "MULTI_FAMILY"): 1.25,
    ...
}
```

Calculates: monthly_gross = sqft × rent_psf, applies 10% vacancy, 40% expense ratio → NOI → cap_rate = NOI/price

---

## 18. Scoring Utilities

**File:** `regog/scoring/utils.py`

### assign_tier(score) → str
Looks up score in TIER_THRESHOLDS (sorted descending).

### parse_flags(flags_value) → list
Parses JSON string or list — handles both DB (JSON string) and in-memory (Python list) formats.

### score_price_deviation(list_price, comp_median, comp_confidence) → float
Percentile-band scoring from -10 to 40.

### apply_comp_fallback(property_dict, scores) → dict
When comp_count=0:
- If estimated_value exists: uses as proxy for price deviation
- If no estimated_value: sets `_fb_cap_at_risky = True`
- **CRITICAL:** Uses `_fb_` prefix for metadata keys — these MUST be filtered out when summing

### apply_confidence_cap(property_dict, scores) → dict
- LOW: caps price deviation at 10
- MEDIUM: caps at 20

### apply_variance_penalty(property_dict, scores) → dict
comps < 5 + variance_high → 25% reduction on price signals

### cap_score_if_no_comps(total, scores) → (float, str | None)
When `_fb_cap_at_risky` is set, max total = 30 (below MEDIUM threshold)

### get_score_completeness(property_dict) → dict
Returns factors_with_data / total_factors for UI badge

---

## 19. Web App Backend (Flask + SSE)

**File:** `web/app.py`

### Endpoints

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Serves index.html |
| `/api/config` | GET | Weights, thresholds, comp defaults |
| `/api/stats` | GET | DB aggregate stats |
| `/api/scans` | GET | Recent 20 scan sessions |
| `/api/scan` | POST | Start a new scan → `{session_id, stream_url}` |
| `/api/scan/<id>/results` | GET | Paginated results |
| `/api/scan/<id>/status` | GET | Current scan status (for polling) |
| `/api/scan/<id>/cancel` | POST | Set cancel event for running scan |
| `/api/scan/<id>/stream` | GET | SSE endpoint streaming properties |
| `/api/saved` | GET | List saved properties |
| `/api/saved/<listing_id>` | POST | Toggle save/unsave |
| `/api/saved/<listing_id>/status` | GET | Check if saved |
| `/api/property/<listing_id>` | GET | Single property detail |

### SSE Events (in order)
1. `event: connected\ndata: {session_id}\n\n`
2. `event: property\ndata: {json serialized property}\n\n`
3. `event: complete\ndata: {status json}\n\n`
4. `event: keepalive\ndata: {}\n\n` (every 30s if no data)

### Background Scan Thread

`_run_scan_background()` runs the same pipeline as CLI with additions:
- Thread-safe status updates via `_scan_status_lock`
- SSE queue pushes each property as it's scored
- Cancel event checked every iteration
- `filtered_out` counter tracked in status

### Lava Search Mode

The web app has TWO scan paths:

1. **Normal path** (`_run_scan_background`): Standard pipeline with optional lava filter
2. **Nationwide lava path** (`_run_nationwide_lava_scan`): Cycles through TOP_20_METROS, only emits lava-quality deals

### TOP_20_METROS

```python
TOP_20_METROS = [
    "New York, NY", "Los Angeles, CA", "Chicago, IL", "Dallas, TX",
    "Houston, TX", "Miami, FL", "Atlanta, GA", "Phoenix, AZ",
    "Philadelphia, PA", "San Antonio, TX", "San Diego, CA",
    "Orlando, FL", "Seattle, WA", "Denver, CO", "Tampa, FL",
    "Portland, OR", "Charlotte, NC", "Nashville, TN",
    "Las Vegas, NV", "Austin, TX",
]
```

When lava_state is set, metros are filtered: `[c for c in TOP_20_METROS if c.endswith(f", {lava_state}")]`

---

## 20. Web Frontend (Single-Page HTML)

**File:** `web/static/index.html`

Single HTML file with ALL CSS + JS inline. Dark theme with REGOG styling.

### CSS Design System

```css
--bg: #0a0a0a;           --bg-surface: #111111;
--bg-card: #111118;       --accent: #ff2233;
--lava: #ff8800;          --lava-glow: rgba(255, 136, 0, 0.5);
--text: #ffffff;          --text-muted: #ddddee;
--text-dim: rgba(255,255,255,0.7);
--green: #44ff66;         --amber: #ffaa00;
--magenta: #ff44aa;       --border: rgba(255,255,255,0.1);
--radius: 12px;           --radius-sm: 8px;
```

### UI Layout (stacked mode boxes — v7 redesign)

```
┌────────────────────────────────────────────────────┐
│ Location: [______________]                         │
│ Category: [Single Family Homes ▼]                  │
├────────────────────────────────────────────────────┤
│ ✓ 📋 Regular Scan  (active)                       │
│ City/State [________]  $ [____] - [____]  [SCAN]  │
├────────────────────────────────────────────────────┤
│ ○ 🔥 Lava Scan     (dimmed when regular active)   │
│ State: [All States ▼]                [🔥 LAVA SCAN]│
└────────────────────────────────────────────────────┘
```

### Key CSS Classes

- `.mode-box` — Each scan mode section (border, padding, background)
- `.mode-box.mode-disabled` — Dimmed state (opacity 0.25, grayscale 0.8, pointer-events: none)
- `.mode-box-header` — Checkbox + label row (has `pointer-events: auto` override)
- `.mode-box-body` — Contains fields + scan button

### Key JS Functions

| Function | Purpose |
|----------|---------|
| `toggleMode()` | Mutual exclusion between regular/lava checkboxes |
| `startScan(mode)` | Takes 'regular' or 'lava', POSTs to `/api/scan` |
| `stopScan()` | Cancels current session, resets both mode's buttons |
| `addProperty(prop)` | Creates card DOM element, inserts in sort order |
| `toggleExpand(listingId)` | Toggles detail view |
| `toggleSave(listingId, btn)` | Save/unsave via API |
| `filterTier(tier)` | Filter by HOT/WARM/ALL |
| `setSort(mode)` | Re-sort by price/profit/score |
| `getListingUrl(prop)` | Build URL: Realtor.com > Zillow > Google Maps |

### Property Card

- Clickable → expands detail grid
- **Badges:** HOT (red glow), LAVA (orange gradient)
- **Score:** Color-coded (green ≥100, amber ≥50, red <50)
- **Card row:** Price, Lava Profit%, vs Median%, DOM, Beds/Baths, Stories, Sqft, Comps
- **Flags:** Brain classification, filter flags, red/green flag pills
- **Expanded detail:** Full grid, lava banner, segmented score bar, brain output, comp listings

### Comp Cards (horizontal scroll)

Each comp card shows: thumbnail, address (35 char max), price (green), beds/baths/sqft/acres/distance, sold/active label with date. Clickable → opens Realtor.com or Zillow.

---

## 21. CLI (main.py)

### Commands

```bash
regog init                                              # Init DB
regog scan residential --location "Dallas, TX" --price-max 400000
regog scan land --location "Billings, MT" --skip-flood
regog scan commercial --location "Chicago, IL" --type multifamily
regog leads --tier HOT --limit 20
regog report --session-id abc123
regog config --show
regog schedule --location "Los Angeles, CA" --interval 24
```

### Key Scan Arguments

`--location`, `--price-min/--price-max`, `--radius`, `--skip-flood`, `--use-zillow`, `--use-redfin`, `--use-craigslist`, `--past-days`, `--limit`

---

## 22. Lava Search Mode

**Lava Search** is a special scan mode that only surfaces extreme deals — properties where the comp median is at least 200% of list price (hardcoded minimum).

### How it works

1. User selects Lava mode + optional state filter via checkboxes
2. Backend runs `_run_nationwide_lava_scan()` which cycles through TOP_20_METROS
3. For each metro, fetches listings + sold comps, runs full pipeline
4. After scoring, applies lava filter: `comp_median / list_price >= 2.0` (200% profit)
5. Only lava-quality deals are emitted via SSE
6. Properties tagged with `lava_profit_pct`, `lava_profit_ratio`, `lava_city`

### Lava Filter in Background Scan

The normal scan path also has a lava filter:
```python
if lava_mode:
    comp_median = prop.get("comp_median_price") or 0
    list_price = prop.get("list_price") or 0
    if comp_median > 0 and list_price > 0:
        profit_ratio = comp_median / list_price
        prop["lava_profit_pct"] = round((profit_ratio - 1.0) * 100, 1)
        prop["lava_profit_ratio"] = round(profit_ratio, 2)
        if profit_ratio < (lava_min_profit / 100.0):
            continue  # Skip — not lava quality
```

---

## 23. Mode Separation (Regular vs Lava)

The scan bar has two `.mode-box` sections stacked vertically:

- **📋 Regular Scan box** — city/state, min price, max price, its own SCAN button
- **🔥 Lava Scan box** — state dropdown, its own LAVA SCAN button
- **Category dropdown** shared at the top (works for both modes)

**Mutual exclusion via `toggleMode()`:** Toggles `.mode-disabled` class on the `.mode-box` element of the other mode. Disabled box has `opacity: 0.25`, `filter: grayscale(0.8)`, `pointer-events: none`.

**CRITICAL FIX:** The `.mode-box-header` has `pointer-events: auto !important` override so checkboxes stay clickable even inside a disabled box.

---

## 24. Utility Modules

### Density (utils/density.py)
ZIP prefix → urban/suburban/rural. Static lookup for 150+ urban prefixes (major metro cores) and 200+ rural prefixes (MT, WY, ID, SD, ND, NV, WV, MS, NM, IA, AK, HI).

### Property Type (utils/property_type.py)
Style string → 'residential'|'land'|'commercial'. High-rise detection: CONDO with ≥5 stories → commercial.

### Rate Limiter (utils/rate_limiter.py)
Per-source throttling: min delay, hourly cap, random jitter, exponential backoff on errors.

### Config Store (utils/config_store.py)
Persistent JSON config overrides (`regog_config.json` next to DB).

### Dedup (utils/dedup.py)
Address-normalized deduplication for merging multiple scraper sources.

### Location Resolver (utils/location_resolver.py)
**CRITICAL:** Converts colloquial terms ("South Georgia", "North GA", "NorCal") to valid "City, ST" search strings. Resolves state names → anchor cities. HomeHarvest TIMES OUT on bare state queries like "Georgia".

---

## 25. Tests

**98 tests total.** Run with: `cd /workspaces/REgog && python -m pytest tests/ -v --tb=short`

### Test Files

- **test_residential_score.py** — 50+ tests: 6 signals, tiers, edge cases, boundary conditions, data types
- **test_land_score.py** — Land scoring (zoning, acreage premium, empty dict)
- **test_scoring_fallback.py** — `_fb_` metadata filter fix (comp_count=0 + estimated_value paths)
- **test_utils.py** — Tier thresholds, boundary tests, parse_flags (list/JSON/None/invalid)
- **test_permit_scraper.py** — Permit inference (unpermitted, code violations, mixed signals)

### Fixtures (conftest.py)
- `standard_residential`: Baseline with all fields
- `hot_deal_residential`: Deep discount (-60%), large assessor gap, low permit risk
- `skip_residential`: Overpriced (+15%), high flood risk, high permit risk
- `missing_data_residential`: All None values
- `distressed_residential`: Fire damage classification

---

## 26. ALL KNOWN PROBLEMS & HOW THEY WERE FIXED

This section catalogs every significant bug or issue encountered during development, with the root cause and the fix applied.

### 🔴 CRITICAL BUGS (Fixed)

| # | Problem | Root Cause | Fix Applied | Version |
|---|---------|-----------|-------------|---------|
| 1 | **Dual database files** | Relative `DB_PATH = "regog.db"` resolved differently for CLI vs web app | Absolute path: `str(Path(__file__).parent.parent / "regog.db")` | V4 |
| 2 | **Zero results in web app** | Web app's DB missing schema columns (`style`, `property_url`) — all `upsert_property()` calls silently failed | Added `init_db()` to `serve_report.py` startup | V4 |
| 3 | **`sum(scores.values())` TypeError** | `apply_comp_fallback()` added string `_fb_source` key to scores dict, then residential/commercial scorers crashed on `sum()` | Changed to `sum(v for k,v in scores.items() if not k.startswith("_fb_"))` | V5 |
| 4 | **FEMA flood zone always returning UNKNOWN** | Used wrong geometry format in ArcGIS query (JSON geometry instead of `esriGeometryPoint`) | Rewrote with simple `geometry={lon},{lat}` + `geometryType=esriGeometryPoint` | V5 |
| 5 | **FEMA penalty unfairly tanking all scores** | `FLOOD_SCORES[None] = 8` penalized every property 8 points when flood data was missing | Changed to `FLOOD_SCORES[None] = 0` — never penalize for missing data | V5 |
| 6 | **DISTRESSED_ tier prefix corruption** | Tier labels concatenated brain classification with tier name: `"DISTRESSED_" + tier` → corrupted 102 records | Removed concatenation. Added DB migration `_fix_corrupted_tiers()`. | V5 |
| 7 | **Residential price deviation ceiling** | Binary scoring (below/above median) gave max 40 pts to every Manhattan listing | Percentile-band scoring: -60%→40, -50%→36, ..., >10%→-5 | V5 |
| 8 | **Land scoring flatlining at 76.0** | No per-acre deviation scoring, automatic bonuses creating artificial floor | Added `score_price_per_acre_deviation()`, `score_land_assessor_gap()` with PPA heuristic | V5 |
| 9 | **Commercial cap rate was dead code** | `_estimate_cap_rate()` returned 0 for all properties | GRM-based estimator with market rent estimates per state/style | V5 |
| 10 | **Land acreage NULL for most parcels** | HomeHarvest's acres column is inconsistent for land | Created `acreage_enricher.py` with 4 fallback sources (lot_sqft, description parsing, title parsing, price heuristic) | V5 |
| 11 | **Mode checkboxes trapped in disabled boxes** | `.mode-box.mode-disabled` set `pointer-events: none` on entire box, including its own checkbox | Added `pointer-events: auto !important` override on `.mode-box-header` | V7 |

### 🟡 MINOR FIXES (Applied)

| # | Problem | Fix |
|---|---------|-----|
| 12 | **Comp scrollbar snapping to edges** | Removed `scroll-snap-type: x mandatory` from comp scroll CSS |
| 13 | **Error logging invisible in Flask** | Added `force=True` to `logging.basicConfig`, `import traceback`, `logger.error(traceback.format_exc())` |
| 14 | **Score key name mismatch for land** | `web/app.py` mapped land's `price_per_acre_deviation` → `score_price_deviation` for UI display |
| 15 | **Lava checkbox unclickable when another mode active** | Same as #11 — checkbox pointer-events override |
| 16 | **lava_profit_pct column missing from schema** | Added `lava_profit_pct`, `lava_profit_ratio`, `lava_city` columns + migration |

---

## 27. Problems That STILL EXIST

These are known issues that have NOT been fully resolved.

### 🟠 DATA QUALITY ISSUES

| # | Problem | Impact | Workaround | 
|---|---------|--------|------------|
| 1 | **Sold comps fetched city-wide, not by radius** | HomeHarvest doesn't support coordinate-based queries | Comps fetched for entire city → filtered by distance in comp engine. Sparse areas get fewer comps. |
| 2 | **`assessed_value` rarely available from HomeHarvest** | `estimated_value` (AVM) used as proxy. Land AVM values are notoriously unreliable. | Assessor gap falls back to PPA heuristic for land. |
| 3 | **FEMA API is intermittently unreliable** | Government ArcGIS endpoint frequently returns errors under load | Retry logic (2 attempts) and caching. `--skip-flood` recommended for fast scans. |
| 4 | **Realtor.com hides sold prices** | Comp card links use Zillow address URLs instead of Realtor.com | `getCompUrl()` builds Zillow address search URL. |
| 5 | **County portal scraping limited** | Most Accela portals require interactive JS sessions | Falls back to keyword-based permit inference. |
| 6 | **HomeHarvest column names change** | Libraries change column names between versions | `g(*keys)` pattern handles this with multiple fallback names. |

### 🟡 SCORING / UI ISSUES

| # | Problem | Impact | 
|---|---------|--------|
| 7 | **Score distribution skews low for land** | Zero HOT/WARM leads in rural land scans — may be accurate or thresholds too aggressive |
| 8 | **No `comp_acreage_matched` badge in UI** | User can't tell if comps are acreage-matched or fallback |
| 9 | **Land score breakdown shows wrong component names in UI** | `score_price_deviation` maps to price per acre, `score_assessor_gap` maps to zoning |
| 10 | **Dynamic comp pool not used in web app background scan** | Web app still uses `limit=200` instead of `get_comp_pool_size()` |
| 11 | **`report.html.j2` template lacks completeness badges and cap rates** | Outdated template |
| 12 | **No test coverage for `comp_count=0` + `estimated_value` path** | Critical edge case only caught in production |
| 13 | **Test for Lava Search mode** | No tests exist for the lava scan path |

### 🔵 ARCHITECTURE GAPS

| # | Problem | Priority |
|---|---------|----------|
| 14 | **Single point of failure on HomeHarvest** | If Realtor.com blocks HomeHarvest, the entire app stops working |
| 15 | **No sold comps for rural areas** | For loose geography scans, sold comp pool is too small (e.g., 24 comps for North Georgia) |
| 16 | **`fetch_sold_comps_near_coords()` defined twice** | Both return `[]` — dead code that shouldn't be called |
| 17 | **Stale `fetch_sold_comps()` in homeharvest_scraper.py** | Returns `[]` — the real one is in redfin_scraper.py |
| 18 | **`geocoder.py` is dead code** | Never called by any pipeline module |
| 19 | **`requirements.txt` may not exist** | Dependencies listed in REGOG docs only |

---

## Quick Reference: Most Important Commands

```bash
# Run tests
python -m pytest tests/ -v --tb=short

# Start web app (port 8080)
python serve_report.py

# Quick CLI scan (residential)
python regog/main.py scan residential --location "Dallas, TX" --price-max 400000 --skip-flood --limit 10

# Quick CLI scan (land)
python regog/main.py scan land --location "Billings, MT" --skip-flood --limit 10

# View HOT leads
python regog/main.py leads --tier HOT --limit 20

# View DB stats
python3 -c "from db.database import get_connection, get_stats; conn=get_connection(); print(get_stats(conn)); conn.close()"

# Test FEMA flood zone
python3 -c "from scrapers.fema_scraper import get_flood_zone; print(get_flood_zone(32.7767, -96.7970))"

# Check corrupted tiers
sqlite3 regog.db "SELECT COUNT(*), lead_tier FROM properties WHERE lead_tier LIKE 'DISTRESSED_%' GROUP BY lead_tier"

# List recent git tags
git tag -l 'v*' --sort=-version:refname
```
