# REGOG REBUILD V6 — Complete From-Scratch Handoff

> # ⚠️ SUPERSEDED — USE V8 INSTEAD ⚠️
>
> **Superseded as of `5f2ca9d` (June 2026) by [`REGOG_REBUILD_V8.md`](REGOG_REBUILD_V8.md).** V6 is no longer the source of truth. A new CLI agent should start from V8, which is more comprehensive and includes:
>
> - **Dedicated mission / laws / rules / goals section** (V8 §1)
> - **Comprehensive keys / cookies / storage files section** (V8 §37)
> - **Full chronology of fixes and attempted solutions** (V8 §35)
> - **File-by-file walkthroughs** of every file in the project (V8 §5, §9-§32)
> - **FLIP RADAR source routing table** (V8 §26)
> - **Code-component → DB-column mapping for land display** (V8 §21)
> - **DEPRECATION NOTICE for V5 and V6** (V8 §39)
> - **Dead-code markers** for `geocoder.py`, duplicate `fetch_sold_comps_near_coords`, stale `fetch_sold_comps` (V8 §36)
>
> **V6 is preserved here for historical reference only.** If V6 contradicts V8, V8 wins.

---

> **Purpose (legacy):** A new CLI agent (Codebuff/Claude) with **ZERO knowledge** of this project must be able to rebuild the entire REGOG application from scratch using this document alone, plus start running scans, fix common issues, and continue development. Every detail, problem, fix, convention, and gotcha is included.
>
> **Scope (legacy):** Captures the state of the project as of `5f2ca9d` (HEAD). Supersedes the previous V6 doc. Includes the LoopNet cookie bundle work and codespace keepalive (both landed in `00481a6` and `5f2ca9d`).

---

## TABLE OF CONTENTS

1. [Application Overview](#1-application-overview)
2. [Current State & Git History](#2-current-state--git-history)
3. [Project Structure](#3-project-structure)
4. [Quick Start (from scratch)](#4-quick-start-from-scratch)
5. [Configuration (config.py)](#5-configuration-configpy)
6. [Database (db/)](#6-database-db)
7. [Entry Points & Import Paths](#7-entry-points--import-paths)
8. [Scan Pipeline (the core loop)](#8-scan-pipeline-the-core-loop)
9. [HomeHarvest Scraper — Active Listings](#9-homeharvest-scraper--active-listings)
10. [Redfin Scraper — Sold Comps](#10-redfin-scraper--sold-comps)
11. [Optional Scrapers (Zillow, Redfin Playwright, Craigslist)](#11-optional-scrapers-zillow-redfin-playwright-craigslist)
12. [LoopNet Auth (cookie bundle import)](#12-loopnet-auth-cookie-bundle-import)
13. [FEMA Flood Zone Scraper](#13-fema-flood-zone-scraper)
14. [Brain Classifier (keyword-based, no LLM)](#14-brain-classifier-keyword-based-no-llm)
15. [Listing Filter](#15-listing-filter)
16. [Acreage Enricher](#16-acreage-enricher)
17. [Comp Engine (2D Expansion Search)](#17-comp-engine-2d-expansion-search)
18. [Scoring Modules (Residential / Land / Commercial)](#18-scoring-modules-residential--land--commercial)
19. [Scoring Utilities](#19-scoring-utilities)
20. [Web App Backend (Flask + SSE)](#20-web-app-backend-flask--sse)
21. [Web Frontend (Single-Page HTML)](#21-web-frontend-single-page-html)
22. [CLI (main.py)](#22-cli-mainpy)
23. [Deal Radar Mode](#23-deal-radar-mode)
24. [Lava Search Mode](#24-lava-search-mode)
25. [Flip Radar Mode](#25-flip-radar-mode)
26. [Utility Modules](#26-utility-modules)
27. [Tests](#27-tests)
28. [Operational: Codespace Idle-Kill + Keepalive](#28-operational-codespace-idle-kill--keepalive)
29. [ALL KNOWN PROBLEMS & HOW THEY WERE FIXED](#29-all-known-problems--how-they-were-fixed)
30. [Problems That STILL EXIST](#30-problems-that-still-exist)
31. [Build Doc References (sibling files)](#31-build-doc-references-sibling-files)

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
8. **Deal Radar** 🎯 — default mode (renamed from "Regular Scan" in V7), finds underpriced properties scored against 6 signals (residential/land/commercial)
9. **Lava Search** 🌋 — only surfaces extreme deals (200%+ profit ratio)
10. **Flip Radar** 🔨 — distress-scored properties with ARV/rehab/profit/ROI analysis
11. **LoopNet auth** — semicolon-separated cookie bundle import (no Playwright login)

**Stack:** Python 3.11+ · SQLite · Flask · HomeHarvest · Playwright · Rich · Jinja2

**Zero API costs** — every data source is free and requires no API key.

---

## 2. Current State & Git History

### Git State (HEAD = `5f2ca9d`)

- **Branch:** `main`, working tree clean except for one untracked file (`loopnet_session.json` — see §12)
- **HEAD:** `5f2ca9d` — "chore: keepalive — fail-fast on missing dir, track child PID, stop on clean exit"
- **Ahead of `origin/main`:** 2 commits (`5f2ca9d` + `00481a6`). **Not pushed.**
- **Last 3 commits:**
  1. `5f2ca9d` — keepalive script improvements (cd guard, child-PID tracking, clean-exit detection)
  2. `00481a6` — "chore: LoopNet cookie bundle import + codespace keepalive" (4 files: `web/app.py`, `web/static/index.html`, `regog/scrapers/loopnet_auth.py`, new `scripts/regog_keepalive.sh`)
  3. `788b162` — "chore: also ignore *.pyo and *.pyd" (`.gitignore` only)

### Tests

- **98 tests passing** (run `pytest -q` to verify)

### App Status

- **App is OFFLINE right now** (HTTP 000, no `serve_report` process running). Must be started from the user's local terminal (see §28 — basher subshell in AI agent environment reaps all detached processes).

---

## 3. Project Structure

```
/workspaces/regogv8/
├── REGOG_REBUILD_V6.md          ← THIS FILE
├── TEMP_HANDOFF.md              ← Short handoff for previous agent (delete after use)
├── README.md                    ← Minimal: "# REgog\nreal estate gog"
├── requirements.txt             ← (does not exist as a file — see §4 for the actual deps)
├── .gitignore                   ← ignores regog.db, regog_config.json, *.pyo, *.pyd, regog_report.html, etc.
│
├── serve_report.py              ← ENTRY POINT: starts Flask web app on port 8080
├── start-regog.sh               ← Boot script (Xvfb + tmux + serve_report)
├── start-display.sh             ← Boot script (Xvfb + x11vnc + noVNC for LoopNet auth popup — legacy)
├── requirements.txt             ← MAY NOT EXIST (see §4 for the actual dep list)
│
├── regog.db                     ← SQLite database (auto-created in project root, gitignored)
├── loopnet_session.json         ← LoopNet cookies (UNTRACKED — contains real/test cookies, never commit)
├── regog_config.json            ← Config overrides (auto-created, gitignored)
├── regog_report.html            ← Generated HTML report (gitignored)
│
├── regog/                       ← Main Python package
│   ├── __init__.py
│   ├── config.py                ← ALL settings, weights, thresholds
│   ├── main.py                  ← CLI entry point (argparse)
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.sql           ← CREATE TABLE + indexes
│   │   └── database.py          ← SQLite wrapper: init, CRUD, upsert, migrations, tier-fix migration
│   │
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── homeharvest_scraper.py   ← fetch_listings() + normalize_listing() (PRIMARY listing source)
│   │   ├── redfin_scraper.py        ← fetch_sold_comps() + normalize_sold_listing() (uses HomeHarvest for sold)
│   │   ├── zillow_stealth.py        ← Playwright-based Zillow scraper (optional, --use-zillow)
│   │   ├── redfin_playwright.py     ← Playwright Redfin browser scraper (optional, --use-redfin)
│   │   ├── craigslist_scraper.py    ← HTTPX+BS Craigslist FSBO scraper (optional, --use-craigslist)
│   │   ├── loopnet_auth.py          ← LoopNet cookie loader (Cookie header on all requests)
│   │   ├── fema_scraper.py          ← FEMA flood zone API (free ArcGIS)
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
│   │   ├── utils.py                 ← Shared: tiers, fallback, confidence, variance, completeness
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
│       └── location_resolver.py     ← Colloquial→City,ST resolution
│
├── web/
│   ├── __init__.py
│   ├── app.py                      ← Flask backend: all API + SSE + background scans + LoopNet cookie endpoints
│   └── static/
│       └── index.html              ← Single-page dark UI (all CSS+JS inline)
│
├── scripts/
│   └── regog_keepalive.sh          ← while-true restart wrapper (see §27)
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
# 1. Clone and enter (assuming git is set up)
cd /workspaces/regogv8

# 2. Create venv and install deps
python3 -m venv venv && source venv/bin/activate
pip install homeharvest beautifulsoup4 httpx lxml rich geopy apscheduler jinja2 playwright flask flask-cors
playwright install chromium   # for Zillow/Redfin scrapers (optional)

# 3. Initialize database (creates regog.db with schema + migrations)
python3 -c "from db.database import init_db; init_db()"

# 4. Run tests (98 expected green)
pytest -q

# 5. Start web app (USER'S LOCAL TERMINAL — not via AI tool calls)
nohup bash scripts/regog_keepalive.sh > /tmp/regog-app.log 2>&1 < /dev/null & disown
sleep 5
curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://localhost:8080/  # expect: 200

# 6. Or use CLI directly
python3 regog/main.py scan residential --location "Dallas, TX" --price-max 400000
python3 regog/main.py leads --tier HOT
```

### Deps (the real list, in case `requirements.txt` is missing)

```
homeharvest>=0.8.0
beautifulsoup4>=4.12.0
httpx>=0.25.0
lxml>=4.9.0
rich>=13.0.0
geopy>=2.3.0
apscheduler>=3.10.0
jinja2>=3.1.0
playwright>=1.40.0
flask>=2.0
flask-cors>=3.0
# playwright-stealth>=1.0.6  # optional — Zillow scraper degrades gracefully
```

---

## 5. Configuration (config.py)

**ALL tunable parameters in ONE file:** `regog/config.py`

### DB_PATH — **MUST BE ABSOLUTE**

```python
from pathlib import Path
DB_PATH = str(Path(__file__).parent.parent / "regog.db")  # ABSOLUTE path
```

**CRITICAL:** This was previously relative (`"regog.db"`) which caused a **dual-database bug** where the CLI and web app wrote to different SQLite files. CLI resolved to `regog/regog.db`, web app resolved to `regog.db`. Both had different data and different schema versions. **Always absolute.**

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

### Lead Tiers (current V6 thresholds)

```python
TIER_THRESHOLDS = {
    "HOT": 100,   # Only scores above 100 (uncapped) qualify as HOT
    "MEDIUM": 50, # 50-100: solid leads worth investigating
    "WARM": 0,    # 0-49: low-priority, needs more data
}
# SKIP is implicit for any score < 0 (no explicit key in the dict)
# NOTE: RISKY tier was REMOVED. Current thresholds are HOT/MEDIUM/WARM + implicit SKIP.
```

### Comp Engine

```python
COMP_DEFAULTS = {
    "radius_miles": 3,
    "min_comps_required": 3,
    "max_radius_miles": 10,
    "similar_sqft_pct": 0.30,   # ±30% sqft for residential
    "similar_acres_pct": 0.50,  # ±50% acres for land
    "similar_beds_range": 1,    # ±1 bedroom for comp matching
    "similar_baths_range": 1,   # ±1 bathroom for comp matching
    "sold_months": 12,          # look back window
}

MIN_COMPS_REQUIRED = 5  # minimum comps before accepting a tier — expanded search tries harder to find 5+
COMP_LOOKBACK_TIERS = [180, 270, 365, 540, 730]  # 2 years max lookback
COMP_STALENESS_PENALTY = 0.15  # 15% confidence reduction when lookback > 365 days
COMP_CONFIDENCE_HIGH = 0.80
COMP_CONFIDENCE_MEDIUM = 0.50
COMP_CONFIDENCE_LOW = 0.00

# Comp search radii: 3 tiers per density per category
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

### Sold Comp Pool Sizing (Part 4 fix)

```python
SOLD_COMPS_BASE = 300          # minimum pool size
SOLD_COMPS_PER_LISTING = 0.15  # 15% of active listing count
SOLD_COMPS_MAX = 2000          # hard cap

def get_comp_pool_size(active_listing_count: int) -> int:
    dynamic_size = int(active_listing_count * SOLD_COMPS_PER_LISTING)
    return max(SOLD_COMPS_BASE, min(dynamic_size, SOLD_COMPS_MAX))
```

### FEMA Flood Zone Scoring

```python
FLOOD_SCORES = {
    "X": 10,        # Minimal risk — no penalty
    "AE": 3,        # High risk — 7pt penalty
    "A": 4,         # High risk
    "VE": 0,        # Coastal extreme — full penalty
    "UNKNOWN": 0,   # No data — ZERO penalty. Never penalize for data we lack.
    None: 0,        # Same — null flood_zone yields 0 not 8
}

# CRITICAL: FLOOD_SCORES[None] WAS 8. Changed to 0 in Part 1 fix.
# The old default penalized every property 8 pts when flood zone was unknown.
# Since FEMA data is unreliable and often missing for rural areas, this was
# unfairly tanking scores.
```

### Other Scoring Maps

```python
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

SCAN_DEFAULTS = {"past_days": 180}  # was 90 — increased to capture older inventory
HIGH_RISE_MIN_STORIES = 5  # CONDO with ≥5 stories → reclassified as commercial
```

### Brain Classifier Keywords

```python
CLASSIFICATION_KEYWORDS = {
    "distressed": ["distressed", "as-is", "needs work", "fixer-upper", "deferred maintenance", ...],
    "teardown":   ["teardown", "land value", "demolish", "knockdown", ...],
    "fire_damage":["fire damage", "smoke damage", "burnt", "structure fire", ...],
    "vacant":     ["vacant", "abandoned", "unoccupied", "boarded up", ...],
    "luxury":     ["luxury", "high-end", "premium", "estate", "gourmet kitchen", "marble", "waterfront", ...],
}

SELLER_MOTIVATION_KEYWORDS = {
    "high":   ["motivated seller", "must sell", "relocation", "divorce", "estate sale",
               "short sale", "pre-foreclosure", "bankruptcy", "price reduced", "price reduction"],
    "medium": ["open to offers", "flexible", "seller motivated", "offers encouraged"],
}

RED_FLAG_KEYWORDS = ["foundation issues", "structural", "mold", "termites", "roof leak",
                     "electrical", "plumbing", "septic", "well water", "no heat",
                     "no ac", "code violation", "unpermitted", "lien", "title issue"]
GREEN_FLAG_KEYWORDS = ["renovated", "updated", "new roof", "new hvac", "new windows",
                       "new kitchen", "new bath", "remodeled", "move-in ready",
                       "turnkey", "investment opportunity", "positive cash flow",
                       "tenant occupied", "rental", "income producing"]
```

### Rate Limits

```python
RATE_LIMITS = {
    "realtor":    {"delay_min": 2, "delay_max": 5, "max_per_hour": 200},
    "redfin":     {"delay_min": 1, "delay_max": 3, "max_per_hour": 300},
    "zillow":     {"delay_min": 4, "delay_max": 9, "max_per_hour": 60},
    "assessor":   {"delay_min": 3, "delay_max": 8, "max_per_hour": 100},
    "craigslist": {"delay_min": 3, "delay_max": 7, "max_per_hour": 80},
}

USER_AGENTS = [  # 5 modern Chrome/Firefox UAs, rotated
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # ... 4 more
]
```

---

## 6. Database (db/)

### Tables (schema.sql)

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
| `_fix_corrupted_tiers()` | Fixes `DISTRESSED_HOT` → `HOT` (Part 3 fix — strips `DISTRESSED_` prefix) |
| `create_scan_session()` | INSERT, returns 8-char UUID |
| `complete_scan_session()` | Updates completed_at + counts |
| `upsert_property()` | INSERT OR UPDATE by listing_id. Returns True if new. |
| `get_session_properties()` | SELECT * for session, ORDER BY score DESC |
| `get_stats()` | Total, hot, warm, sessions, avg_score |
| `search_properties()` | Filtered search with all optional params |
| `get_leads_by_tier()` | Top properties by tier |
| `_deserialize_row()` | Parses JSON fields on read |

### Lava Columns (added V7)

```sql
lava_profit_pct REAL
lava_profit_ratio REAL
lava_city TEXT
```

### IMPORTANT: Transient fields popped before upsert

These fields are used in-memory and during SSE streaming but are **popped** before `upsert_property()` to avoid DB errors (or because the schema didn't have them at some point):
- `property_url` — Realtor.com detail URL
- `style` — Property type for comp matching
- `cap_rate_data` — Estimated cap rate, NOI, GRM (computed for commercial)
- `completeness` — Score completeness factors
- `comp_acreage_matched` — Bool indicating acreage-filtered comps

All three callers (`regog/main.py`, `web/app.py`, both scan paths) pop these, call `upsert_property()`, then restore. Pattern:

```python
cap_rate_data = prop.pop("cap_rate_data", None)
completeness_data = prop.pop("completeness", None)
comp_acreage_matched = prop.pop("comp_acreage_matched", None)

upsert_property(conn, prop)

# Restore for SSE stream / display
if cap_rate_data: prop["cap_rate_data"] = cap_rate_data
if completeness_data: prop["completeness"] = completeness_data
if comp_acreage_matched is not None: prop["comp_acreage_matched"] = comp_acreage_matched
```

---

## 7. Entry Points & Import Paths

### `serve_report.py` (THE web app entry point)

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

### Import Path Setup (CRITICAL)

Every entry point must add the project root to `sys.path` before any REGOG imports:

- **`serve_report.py`**: `sys.path.insert(0, os.path.dirname(__file__))` + `sys.path.insert(0, os.path.join(os.path.dirname(__file__), "regog"))`
- **`regog/main.py`**: `sys.path.insert(0, str(Path(__file__).parent))`
- **`web/app.py`**: `sys.path.insert(0, str(Path(__file__).parent.parent / "regog"))` + `sys.path.insert(0, str(Path(__file__).parent.parent))`
- **Tests**: `sys.path.insert(0, str(Path(__file__).parent.parent / "regog"))`

### Deferred Imports Pattern (CRITICAL)

Both `main.py` and `web/app.py` import heavy modules **inside functions**, not at module level:

```python
def cmd_scan(args):
    from db.database import get_connection, create_scan_session  # Inside function!
    from scrapers.homeharvest_scraper import fetch_listings
    # ... rest of function
```

**Why:** `sys.path` is modified at module level before any function is called. Top-level imports would execute before `sys.path` is ready → `ModuleNotFoundError`.

### All `__init__.py` files must exist

Every subdirectory (`scrapers/`, `db/`, `enrichment/`, `scoring/`, `ui/`, `utils/`, `scheduler/`, `tests/`, `web/`) needs an empty `__init__.py` to be importable as a Python package.

---

## 8. Scan Pipeline (the core loop)

Both CLI and web app follow the same pipeline:

```
1. Fetch SOLD comps ────────── redfin_scraper.fetch_sold_comps(location, scan_type)
   (up to dynamic pool size: max(base=300, count*0.15, cap=2000))

2. Fetch ACTIVE listings ───── homeharvest_scraper.fetch_listings(location, for_sale)

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

### `fetch_listings(location, listing_type, past_days, property_type)`

- Calls `homeharvest.scrape_property()` → returns pandas DataFrame
- Converts to list of dicts
- Returns `[]` if `homeharvest` not installed (graceful)

### `normalize_listing(raw, source, scan_session_id, scan_type) → dict`

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

**Acres fallback:** If `acres` is still None, derive from `lot_sqft / 43560`.
**Sqft fallback for land:** If no sqft but has acres, sqft = acres * 43560.
**lot_sqft fallback chain:** ~10 possible keys.
**Helpers `num(v)` and `flt(v)`** are defined INSIDE `normalize_listing`, BEFORE use.

⚠️ **This file ALSO has a STALE `fetch_sold_comps()` that returns `[]`. Do NOT use it.** The real sold comps function is in `redfin_scraper.py`.

---

## 10. Redfin Scraper — Sold Comps

**File:** `regog/scrapers/redfin_scraper.py`

### `fetch_sold_comps(location, scan_type, past_days=180, limit=200) → list[dict]`

- Uses HomeHarvest under the hood with `listing_type="sold"`
- Returns up to `limit` sold comps
- Each normalized via `normalize_sold_listing()` — **NOT** `normalize_listing()`

### `normalize_sold_listing(raw, scan_type) → dict | None`

**Explicitly handles sold-specific column names:**

- `list_price` → tries `sold_price`, `last_sold_price`, `close_price`, `sale_price`, `price`, `list_price`
- `last_sold_date` → tries `last_sold_date`, `sold_date`, `close_date`, `closing_date`
- `listing_status` → forced to `"sold"`
- Returns `None` if no `sold_price` (critical field)

⚠️ `fetch_sold_comps_near_coords()` is defined TWICE in this file — both return `[]`. HomeHarvest doesn't support coordinate-based queries.

---

## 11. Optional Scrapers

### Zillow (zillow_stealth.py) — `--use-zillow`

- Playwright-based with anti-bot: stealth plugin, viewport/UA/locale randomization, human-like scrolling
- 3 extraction methods: Next.js JSON → Apollo GraphQL → DOM fallback
- **Unique import pattern:** `from utils.rate_limiter import rate_limit as _shared_rate_limit, report_success as _report_success, report_error as _report_error`

### Redfin Playwright (redfin_playwright.py) — `--use-redfin`

- Playwright browser fallback for Redfin
- 2 methods: embedded JSON → DOM fallback

### Craigslist (craigslist_scraper.py) — `--use-craigslist`

- HTTPX + BeautifulSoup for FSBO/motivated seller listings
- Maps 20+ cities via `CL_CITY_MAP`
- 3 subcategories: `reo` (FSBO real estate), `rea` (land), `reb` (commercial)

### Deduplication (utils/dedup.py)

When multiple sources are used, `merge_and_deduplicate()` normalizes addresses and removes duplicates. Primary source (HomeHarvest) wins on conflicts.

---

## 12. LoopNet Auth (cookie bundle import)

**File:** `regog/scrapers/loopnet_auth.py` + endpoints in `web/app.py`

### The old vs new flow

**OLD (deprecated):** Playwright login popup, then save the `storage_state` to a file. Fragile, hard to maintain, and broke when Cloudflare protected the auth flow.

**NEW (current, since `00481a6`):** User pastes a semicolon-separated cookie bundle from DevTools → backend parses it → saved to `loopnet_session.json` → scraper sends the cookies on every request.

### Endpoints (in `web/app.py`)

#### `POST /api/loopnet/save-cookie`
Accepts `{"cookies": "SessionFarm_GUID=...; UserPreferences=...; UserInfo_AssociateID=..."}`. Parses and saves to `loopnet_session.json`.

The parser is `_parse_cookie_bundle(bundle: str) -> dict` and returns:
```python
{
    "cookies":          {name: value, ...},
    "cookie_string":    "name1=value1; name2=value2; ...",   # rebuilt, normalized
    "saved_at":         "ISO-8601",
    "missing_expected": ["TDID", "UserPreferences", ...],   # which expected cookies are absent
    "expected_cookies": ["SessionFarm_GUID", "UserPreferences", "UserInfo_AssociateID"],
}
```

Validation: raises `ValueError` on empty bundle, missing `=`, empty name/value, etc. The endpoint passes `data.get("cookies") or ""` to the parser — an empty string is handled correctly via `if not bundle or not bundle.strip()`.

#### `GET /api/loopnet/session/status`
Returns whether the file exists, age in minutes, cookie count, and missing expected cookies. **Guarded against old `storage_state` format** via `isinstance(_cookies, dict)` check.

### Expected cookies (3, not 5)

```python
EXPECTED_LOOPNET_COOKIES = [
    "SessionFarm_GUID",
    "UserPreferences",
    "UserInfo_AssociateID",
]
# TDID and TDCPM (Trade Desk / ad-tracking) intentionally EXCLUDED.
# Browsers are phasing them out and they aren't needed for LoopNet auth.
# Surfaced back to the UI so the user knows when their DevTools export was incomplete.
```

### UI flow (in `web/static/index.html`)

1. User logs into LoopNet in their browser
2. Opens DevTools → Application → Cookies → loopnet.com
3. Copies the 3 expected cookies as `name=value; name=value; ...`
4. Pastes into the LoopNet cookie bar in the REGOG UI
5. `saveLoopnetCookie()` (JS function) POSTs to `/api/loopnet/save-cookie`
6. The dot indicator refreshes via `refreshLoopnetSessionDot()` (also shows cookie count)

### Scraper use (loopnet_auth.py)

`_load_session() -> dict` reads `loopnet_session.json`. `_session_to_cookies() -> list[dict]` converts to Playwright's `add_cookies` format.

In the LoopNet scraper:
```python
context = await browser.new_context(...)
await context.set_extra_http_headers({"Cookie": cookie_string})  # for HTTP requests
await context.add_cookies(cookie_list)                           # for document.cookie
```

### Storage file

`/workspaces/regogv8/loopnet_session.json` — **UNTRACKED in git** (in `.gitignore`). Contains real/test cookies. Never commit. Will be regenerated each time the user pastes a fresh bundle.

---

## 13. FEMA Flood Zone Scraper

**File:** `regog/scrapers/fema_scraper.py`

### `get_flood_zone(lat, lon) → str | None`

**Endpoint:** `https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query`

**Query params:** `geometry={lon},{lat}`, `geometryType=esriGeometryPoint`, `spatialRel=esriSpatialRelIntersects`, `outFields=FLD_ZONE,ZONE_SUBTY,SFHA_TF`, `returnGeometry=false`, `f=json`

**Features:**
- Cached by (lat, lon) rounded to 4 decimal places (~10m resolution)
- 0.5s min delay between requests
- 2 retries with 1s backoff
- Returns zone code: `X` (minimal risk), `AE`/`A` (high risk), `VE` (coastal extreme), or `"UNKNOWN"`

**KNOWN PROBLEM (FIXED):** The original NFHL API used a different JSON geometry format that caused all queries to fail. Rewritten with the simpler `esriGeometryPoint` format. Also, `FLOOD_SCORES[None]` was changed from 8 to 0 — see §28.

---

## 14. Brain Classifier (keyword-based, no LLM)

**File:** `regog/enrichment/brain.py`

### `classify_property(address, scan_type, list_price, sqft, year_built, days_on_market, description) → dict`

**Classification priority order:** `fire_damage > teardown > distressed > vacant > luxury > standard > land_only`

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

## 15. Listing Filter

**File:** `regog/enrichment/listing_filter.py`

Filters out junk listings before scoring. Order matters — first match wins:

1. **`check_auction`** → `skip`: "foreclosure auction", "opening bid", "sheriff sale"
2. **`check_bait_price`** → `skip`: Price < $1K, or < $10K + residential + no sqft
3. **`check_burned`** → `flag`: "burnt", "fire damaged", "structure fire"
4. **`check_demolition`** → `flag`: "must demolish", "condemned", "uninhabitable"
5. **`check_land_masquerade`** → `flag`: Houses listed as land/lots

Returns: `{"action": "skip" | "flag", "reason": "...", "filter_type": "auction"|"bait"|"burned"|"demolition"|"land_masquerade"}`

---

## 16. Acreage Enricher

**File:** `regog/enrichment/acreage_enricher.py` (added in Part 1 fix of V5)

Fills missing acreage from 4 fallback sources:

1. Compute from `lot_sqft / 43560`
2. Parse from `listing_description` via regex: `"1.5 acres"`, `"0.25 AC"`, `"43,560 sq ft"`
3. Parse from title/address text
4. Estimate from price-based heuristic (for land-only listings)

When acreage is **estimated** (not measured), sets `acres_estimated = True` and the land scoring applies a **30% penalty** to the price-per-acre deviation.

---

## 17. Comp Engine (2D Expansion Search)

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

## 18. Scoring Modules

### Residential Score (residential_score.py)

**6 components + 3 post-processing steps:**

**Components:**
1. **price_deviation** (40 pts max): Percentile-band scoring (Part 2 fix)
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

NOTE: No `DISTRESSED_` prefix on tiers. Removed in Part 3 fix.

**Score-component → DB-column mapping for UI display (in `web/app.py`'s `_run_scan_background`):**

The `score_*` columns on the `properties` table are the same names across scan types, but the underlying scoring function returns scan-type-specific keys. The web app maps them for UI display:

```python
if scan_type == "land":
    prop["score_price_deviation"] = scores.get("price_deviation",
        scores.get("price_per_acre_deviation", 0))
    prop["score_assessor_gap"] = scores.get("assessor_gap",
        scores.get("zoning_bonus", 0))
    prop["score_condition"] = scores.get("condition",
        scores.get("acreage_premium", 0))
else:
    prop["score_price_deviation"] = scores.get("price_deviation", 0)
    prop["score_assessor_gap"] = scores.get("assessor_gap", 0)
    prop["score_condition"] = scores.get("condition", 0)
```

### Land Score (land_score.py)

**7 components:**
1. **price_per_acre_deviation** (40 pts): Same percentile bands as residential, but against $/acre
   - If acres=NULL/0: returns 0 (DO NOT use total price as proxy — was a bug, now fixed)
   - If comps are significantly different size (<50% or >200% of target): 50% reduction
   - If acres_estimated: 30% penalty

2. **zoning_bonus** (20 pts): Buildable=20, Non-buildable=2, Unknown=10
3. **road_access_bonus** (10 pts): From brain_green_flags
4. **utilities_bonus** (10 pts): From brain_green_flags
5. **acreage_premium** (10 pts): ≤1ac=10, ≤5ac=8, ≤10ac=6, ≤40ac=4, >40ac=2
6. **flood_penalty** (0-10): Same as residential
7. **(Plus redistributed signals when acres=NULL to keep total <70)**

**Fallback when acres=NULL:** Redistributes weight, caps below HOT, `data_confidence=LOW`.

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

Result stored in `prop["cap_rate_data"]`:
```python
{
    "estimated_cap_rate": float,  # %
    "estimated_noi": float,       # $/yr
    "estimated_grm": float,       # x
    "rent_psf_used": float,
}
```

---

## 19. Scoring Utilities

**File:** `regog/scoring/utils.py`

### `assign_tier(score) → str`
Looks up score in `TIER_THRESHOLDS` (sorted descending).

### `parse_flags(flags_value) → list`
Parses JSON string or list — handles both DB (JSON string) and in-memory (Python list) formats.

### `score_price_deviation(list_price, comp_median, comp_confidence) → float`
Percentile-band scoring from -10 to 40.

### `apply_comp_fallback(property_dict, scores) → dict`
When `comp_count == 0`:
- If `estimated_value` exists: uses `((list_price - estimated) / estimated) * 100` as proxy deviation
- If no estimated_value: sets `_fb_cap_at_risky = True`
- **CRITICAL:** Uses `_fb_` prefix for metadata keys — these MUST be filtered out when summing

### `apply_confidence_cap(property_dict, scores) → dict`
- LOW confidence: caps price_deviation/price_per_acre_deviation at 10
- MEDIUM confidence: caps at 20

### `apply_variance_penalty(property_dict, scores) → dict`
comps < 5 + `comp_variance_high` → 25% reduction on price signals

### `cap_score_if_no_comps(total, scores) → (float, str | None)`
When `_fb_cap_at_risky` is set, max total = 30 (below MEDIUM threshold)

### `get_score_completeness(property_dict) → dict`
Returns factors_with_data / total_factors for UI badge (Part 7):
- `completeness_pct`: int (0-100)
- `missing_factors`: list[str]
- `badge`: "COMPLETE" | "PARTIAL" | "LIMITED DATA"
- `badge_color`: "green" | "yellow" | "red"

---

## 20. Web App Backend (Flask + SSE)

**File:** `web/app.py`

### Endpoints

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Serves `index.html` |
| `/api/config` | GET | Weights, thresholds, comp defaults |
| `/api/stats` | GET | DB aggregate stats |
| `/api/scans` | GET | Recent 20 scan sessions |
| `/api/scan` | POST | Start a new scan → `{session_id, stream_url}` |
| `/api/scan/<id>/results` | GET | Paginated results |
| `/api/scan/<id>/status` | GET | Current scan status (for polling after SSE closes) |
| `/api/scan/<id>/cancel` | POST | Set cancel event for running scan |
| `/api/scan/<id>/stream` | GET | SSE endpoint streaming properties |
| `/api/saved` | GET | List saved properties |
| `/api/saved/<listing_id>` | POST | Toggle save/unsave |
| `/api/saved/<listing_id>/status` | GET | Check if saved |
| `/api/property/<listing_id>` | GET | Single property detail |
| `/api/loopnet/save-cookie` | POST | Save LoopNet cookie bundle (see §12) |
| `/api/loopnet/session/status` | GET | LoopNet session status |

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
- For land: maps `price_per_acre_deviation` → `score_price_deviation` for UI display

### Scan Modes Overview

The web app has THREE mutually exclusive scan modes (selected via the stacked mode boxes in the UI — see `web/static/index.html` lines 1183-1280). Only one mode can be active at a time; `toggleMode()` enforces mutual exclusion:

1. **DEAL RADAR** 🎯 — `_run_scan_background()` with `scan_type ∈ {residential, land, commercial}`, `lava_mode=False`, no flip. **Default** — web app boots into this box pre-checked. See §23.
2. **LAVA SCAN** 🌋 — `_run_nationwide_lava_scan()` cycles through TOP_20_METROS, OR `_run_scan_background` with `lava_mode=True` (single-city). Emits only deals where `comp_median / list_price >= 2.0` (default 200%, user-adjustable). See §24.
3. **FLIP RADAR** 🔨 — `_run_flip_scan()` with `scan_type = "flip"`, distress scoring + ARV/rehab/profit/ROI/deal-grade. See §25.

### TOP_20_METROS

**Used by Lava Search's nationwide path only** (`_run_nationwide_lava_scan`, see §24). DEAL RADAR and FLIP RADAR do not iterate this list — they take a single user-provided location.

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

When `lava_state` is set, metros are filtered: `[c for c in TOP_20_METROS if c.endswith(f", {lava_state}")]`

### Flip Radar Mode (since V7) — full details in §25

A separate scan type `"flip"` with its own pipeline (`_run_flip_scan` in `web/app.py`):
- Distress scoring (DISTRESS_HIGH / MEDIUM / LOW keyword tiers, 3/2/1 pts per match)
- ARV / repair / max-offer / profit / ROI / deal grade computation
- Tier mapped to REGOG lead_tier: `LAVA` / `HOT` / `WARM` / `NEUTRAL` / `SKIP`
- Property-type dropdown: single_family, multi_family, condos, commercial, townhomes, hotel, rv_park, mixed_use, all
- Each selection maps to its own listing source(s) (Realtor / Zillow / LoopNet) — see `_flip_property_types()` in `web/app.py`

### Logging

`logging.basicConfig(level=logging.DEBUG, force=True, ...)` — `force=True` was added (Part: error logging invisible in Flask fix) so the web app's logging isn't swallowed by Flask's defaults. All errors include full tracebacks via `logger.error(traceback.format_exc())`.

### Flask Debug Mode

`web/app.py`'s `__main__` runs Flask on port 5000 in debug mode. `serve_report.py` runs on port 8080 in non-debug mode with threading. **Always use `serve_report.py` in production — debug=False avoids the reloader child being killed by pkill -f.**

---

## 21. Web Frontend (Single-Page HTML)

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

### UI Layout (stacked mode boxes)

```
┌────────────────────────────────────────────────────┐
│ Location: [______________]                         │
│ Category: [Single Family Homes ▼]                  │
├────────────────────────────────────────────────────┤
│ ✓ 🎯 DEAL RADAR  (active, default)                 │
│ Category [Single Family ▼]  $ [____] - [____] [SCAN]│
├────────────────────────────────────────────────────┤
│ ○ 🌋 LAVA SCAN   (dimmed when DEAL active)         │
│ State: [All States ▼]              [🌋 LAVA SCAN]  │
├────────────────────────────────────────────────────┤
│ ○ 🔨 FLIP RADAR  (dimmed when DEAL active)         │
│ Type: [All Properties ▼]          [🔨 FLIP SCAN]   │
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
| `toggleMode()` | Mutual exclusion between the THREE mode checkboxes (DEAL / LAVA / FLIP). If all three are unchecked, auto-defaults to DEAL RADAR. |
| `startScan(mode)` | Takes `'regular'` (DEAL RADAR), `'lava'`, or `'flip'`, POSTs to `/api/scan` |
| `stopScan()` | Cancels current session, resets both mode's buttons |
| `addProperty(prop)` | Creates card DOM element, inserts in sort order |
| `toggleExpand(listingId)` | Toggles detail view |
| `toggleSave(listingId, btn)` | Save/unsave via API |
| `filterTier(tier)` | Filter by HOT/WARM/ALL |
| `setSort(mode)` | Re-sort by price/profit/score |
| `getListingUrl(prop)` | Build URL: Realtor.com > Zillow > Google Maps |
| `saveLoopnetCookie()` | POSTs cookie bundle to `/api/loopnet/save-cookie` |
| `refreshLoopnetSessionDot()` | Refreshes LoopNet session indicator + cookie count |

### Property Card

- Clickable → expands detail grid
- **Badges:** HOT (red glow), LAVA (orange gradient)
- **Score:** Color-coded (green ≥100, amber ≥50, red <50)
- **Card row:** Price, Lava Profit%, vs Median%, DOM, Beds/Baths, Stories, Sqft, Comps
- **Flags:** Brain classification, filter flags, red/green flag pills
- **Expanded detail:** Full grid, lava banner, segmented score bar, brain output, comp listings
- **Score completeness badge** (Part 7): COMPLETE / PARTIAL / LIMITED DATA

### Comp Cards (horizontal scroll)

Each comp card shows: thumbnail, address (35 char max), price (green), beds/baths/sqft/acres/distance, sold/active label with date. Clickable → opens Realtor.com or Zillow.

---

## 22. CLI (main.py)

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

### Pipeline (same as DEAL RADAR web-app path, see §23)

1. Resolve location (see §26 location_resolver)
2. Fetch sold comps (dynamic pool)
3. Fetch active listings
4. Optionally fetch secondary sources
5. For each property: normalize → brain → filter → enrich → comps → score → upsert
6. Show results in Rich terminal table

**Note:** The CLI exposes only the **DEAL RADAR** standard pipeline (`residential` / `land` / `commercial`). Lava Search and Flip Radar are web-app only — there's no `regog scan lava` or `regog scan flip` subcommand. (The `scan` subcommand's `scan_type` choices are `["residential", "land", "commercial"]` only — see `regog/main.py` line 61.)

### Detailed output

`_print_property_details(properties)` shows top 10 HOT/WARM:
- Cap rate (commercial)
- Score completeness (badge + missing factors)
- Acreage warning for land (estimated vs measured)

---

## 23. Deal Radar Mode

**Deal Radar** 🎯 (renamed from "Regular Scan" in V7) is the **default scan mode** — the web app boots with the DEAL RADAR box pre-checked (`regular-mode` checkbox, `checked` attribute in the HTML). It's the bread-and-butter underpriced-property finder: fetch listings → score against 6 signals → tier them HOT/MEDIUM/WARM/SKIP.

### When to use

- "Find underpriced homes in a specific city" (e.g., Dallas under $400K)
- "Show me all HOT leads in Chicago" — score_total >= 100
- Any case where you want the full 0-100+ scoring against the standard tier thresholds, with **all** properties emitted (no minimum profit filter, no distress filter)

### How the three modes differ

| Mode | Filter | Pipeline | Use case |
|------|--------|----------|----------|
| **DEAL RADAR** 🎯 | None — all scored properties emitted | `_run_scan_background` (single city, full pipeline) | Default — find underpriced properties |
| **LAVA SCAN** 🌋 | `comp_median / list_price >= 2.0` (default 200%, slider-adjustable) | `_run_nationwide_lava_scan` (cycles TOP_20_METROS) OR `_run_scan_background` with `lava_mode=True` (single city) | Only extreme deals — "I want 100%+ profit" |
| **FLIP RADAR** 🔨 | `distress_score >= 2` | `_run_flip_scan` (separate scan type `"flip"`) | Distressed properties worth fixing & flipping |

### DEAL RADAR pipeline

Drives `_run_scan_background()` in `web/app.py` with `scan_type ∈ {"residential", "land", "commercial"}`, `lava_mode=False`, `flip_property_type` unused. Same pipeline as §8:

1. **Resolve location** — colloquial ("South GA", "NorCal") → "City, ST" via `utils.location_resolver.resolve_with_details`
2. **Fetch sold comps** — dynamic pool size via `get_comp_pool_size(listing_count)` (300 base, 0.15× count, capped at 2000)
3. **Fetch active listings** — HomeHarvest (Realtor.com)
4. **Optionally** fetch Zillow (`--use-zillow`), Redfin Playwright (`--use-redfin`), Craigslist (`--use-craigslist`) — then dedup via `utils.dedup.merge_and_deduplicate`
5. **For each listing:** normalize → price-filter → brain-classify → listing-filter (skip auction/bait) → enrich (assessor → FEMA → permits) → calculate comps (2D expansion) → score (residential/land/commercial) → upsert → push to SSE queue
6. **Complete session** — `complete_scan_session(conn, session_id, processed, hot_count)`

### Parameters (from the 🎯 DEAL RADAR box in the UI)

- **Location** (required) — "City, ST", ZIP, or colloquial term
- **Category dropdown** — `Single Family Homes` / `Land` / `Commercial` — sets `scan_type`
- **Min/Max price** — applied per-listing after `normalize_listing()`

### Tier thresholds (DEAL RADAR's output)

```python
TIER_THRESHOLDS = {"HOT": 100, "MEDIUM": 50, "WARM": 0}  # <0 implicit SKIP
```

A DEAL RADAR HOT lead needs a score >= 100 (uncapped percentile-band total). Most properties score 0-80, so HOTs are rare and precious. MEDIUM (50-99) and WARM (0-49) are the workhorses.

### Stats shown in the DEAL RADAR results panel

- Total found
- HOT count
- MEDIUM count
- WARM count
- Avg score
- Live count (during scan, grows as properties stream in)
- Filtered-out count (skipped by listing_filter — auctions, bait, etc.)

### Code references

- **`web/static/index.html`** lines 1183-1209 — DEAL RADAR scan box (the source comment `<!-- 🎯 DEAL RADAR Scan Box (was: Regular Scan) -->` documents the rename history)
- **`web/app.py` `start_scan()`** — the `POST /api/scan` route handler. When called with a non-flip `scan_type` and no `lava_mode=True`, routes to `_run_scan_background()`
- **`regog/main.py` `cmd_scan()`** — `regog scan residential|land|commercial` is the CLI equivalent
- **Mutual exclusion** — `toggleMode()` in JS (line 1519) ensures only one of the three checkboxes is checked at a time. If all three are unchecked, DEAL RADAR auto-defaults (line 1535).

---

## 24. Lava Search Mode

**Lava Search** is a special scan mode that only surfaces extreme deals — properties where the comp median is at least 200% of list price (the **default** threshold; user-adjustable via the `lava_min_profit` slider in the web UI). The filter is `comp_median / list_price >= (lava_min_profit / 100.0)`.

### How it works

1. User selects Lava mode + optional state filter via checkboxes
2. Backend runs `_run_nationwide_lava_scan()` which cycles through TOP_20_METROS
3. For each metro, fetches listings + sold comps, runs full pipeline
4. After scoring, applies lava filter: `comp_median / list_price >= 2.0` (200% profit)
5. Only lava-quality deals are emitted via SSE
6. Properties tagged with `lava_profit_pct`, `lava_profit_ratio`, `lava_city`

### Lava Filter

```python
if lava_mode:
    comp_median = prop.get("comp_median_price") or 0
    list_price = prop.get("list_price") or 0
    if comp_median > 0 and list_price > 0:
        profit_ratio = comp_median / list_price
        min_ratio = lava_min_profit / 100.0
        prop["lava_profit_pct"] = round((profit_ratio - 1.0) * 100, 1)
        prop["lava_profit_ratio"] = round(profit_ratio, 2)
        if profit_ratio < min_ratio:
            continue  # Skip — not lava quality
    else:
        continue  # No comp data — skip
```

---

## 25. Flip Radar Mode

A separate scan pipeline (`_run_flip_scan` in `web/app.py`). Distress-scored properties with ARV/rehab/profit/ROI analysis.

### Distress Scoring

```python
DISTRESS_HIGH = ["as-is", "needs work", "fixer", "cash only", "handyman special",
                 "tear down", "fire damage", "flood damage", "foundation", ...]
DISTRESS_MEDIUM = ["estate sale", "motivated seller", "price reduced", "below market",
                   "tlc", "updating needed", "cosmetic", "original condition", ...]
DISTRESS_LOW = ["sold as is", "older home", "bring offers", "priced to sell", "make offer"]

def score_distress(text: str) -> tuple[int, list[str]]:
    # 3 pts per HIGH match, 2 per MEDIUM, 1 per LOW
    ...
```

Properties with distress_score < 2 are filtered out.

### Repair Cost Estimation

```python
def estimate_repair_cost(distress_score: int, sqft: int | None) -> tuple[int, str]:
    if distress_score >= 8: cost_per_sqft, tier, flat_fallback = 45, "heavy", 85000
    elif distress_score >= 5: cost_per_sqft, tier, flat_fallback = 28, "medium", 45000
    else: cost_per_sqft, tier, flat_fallback = 15, "light", 20000
    if sqft and sqft > 0:
        return int(cost_per_sqft * sqft), tier
    return flat_fallback, tier
```

### Flip Metrics

```python
def compute_flip_metrics(prop: dict) -> dict:
    arv = prop.get("comp_median_price") or 0
    list_price = prop.get("list_price") or 0
    sqft = prop.get("sqft")
    distress_score = prop.get("flip_distress_score") or 0

    repair_cost, rehab_tier = estimate_repair_cost(distress_score, sqft)
    max_offer = int(arv * 0.70) - repair_cost
    projected_profit = arv - list_price - repair_cost
    total_investment = list_price + repair_cost
    roi_pct = (projected_profit / total_investment) * 100.0 if total_investment > 0 else 0.0

    if projected_profit >= 50000 and roi_pct >= 20: deal_grade = "A"
    elif projected_profit >= 25000 and roi_pct >= 15: deal_grade = "B"
    elif projected_profit >= 10000 and roi_pct >= 10: deal_grade = "C"
    else: deal_grade = "D"
    ...
```

### Flip Tier Mapping

```python
def _flip_tier(prop: dict) -> str:
    profit = prop.get("flip_projected_profit") or 0
    roi = prop.get("flip_roi_pct") or 0
    grade = prop.get("flip_deal_grade") or "D"
    if profit <= 0: return "SKIP"
    if grade == "A" and roi >= 40: return "LAVA"
    if grade == "A" or (grade == "B" and roi >= 25): return "HOT"
    if grade in ("B", "C"): return "WARM"
    return "NEUTRAL"
```

### Property Type Routing

`_flip_property_types(selection)` maps the FLIP RADAR dropdown to listing sources:
- `single_family` → Realtor (single_family, mobile)
- `multi_family` → Realtor (multi_family, duplex_triplex) — **excludes condos**
- `condos` → Realtor (condos, apartment) — **own category, doesn't leak**
- `commercial` → Realtor (townhomes, farm) — **excludes multi-family/condos**
- `townhomes` → Realtor (townhomes)
- `hotel` → Zillow (LoopNet is Cloudflare-blocked)
- `rv_park` → Zillow (Zillow carries RV/mobile/manufactured)
- `mixed_use` → LoopNet-only
- `all` → merge from all three sources

---

## 26. Utility Modules

### Density (`utils/density.py`)
ZIP prefix → urban/suburban/rural. Static lookup for 150+ urban prefixes (major metro cores) and 200+ rural prefixes (MT, WY, ID, SD, ND, NV, WV, MS, NM, IA, AK, HI).

### Property Type (`utils/property_type.py`)
Style string → 'residential'|'land'|'commercial'. High-rise detection: CONDO with ≥5 stories → commercial.

### Rate Limiter (`utils/rate_limiter.py`)
Per-source throttling: min delay, hourly cap, random jitter, exponential backoff on errors.

### Config Store (`utils/config_store.py`)
Persistent JSON config overrides (`regog_config.json` next to DB).

### Dedup (`utils/dedup.py`)
Address-normalized deduplication for merging multiple scraper sources.

### Location Resolver (`utils/location_resolver.py`)
**CRITICAL:** Converts colloquial terms ("South Georgia", "North GA", "NorCal") to valid "City, ST" search strings. Resolves state names → anchor cities. HomeHarvest TIMES OUT on bare state queries like "Georgia".

```python
from utils.location_resolver import resolve_with_details as _resolve_loc
loc_info = _resolve_loc(args.location)
search_location = loc_info["resolved"]
# loc_info = {"original", "resolved", "changed": bool, "method": str}
```

If the resolved location differs, the new location is persisted into the scan session's `search_params` JSON for traceability.

---

## 27. Tests

**98 tests total.** Run with:
```bash
cd /workspaces/regogv8
pytest -q
```

### Test Files

- **`test_residential_score.py`** — 50+ tests: 6 signals, tiers, edge cases, boundary conditions, data types
- **`test_land_score.py`** — Land scoring (zoning, acreage premium, empty dict, estimated acreage penalty)
- **`test_scoring_fallback.py`** — `_fb_` metadata filter fix (comp_count=0 + estimated_value paths)
- **`test_utils.py`** — Tier thresholds, boundary tests, parse_flags (list/JSON/None/invalid), get_score_completeness
- **`test_permit_scraper.py`** — Permit inference (unpermitted, code violations, mixed signals)

### Fixtures (`conftest.py`)

- `standard_residential`: Baseline with all fields
- `hot_deal_residential`: Deep discount (-60%), large assessor gap, low permit risk. Must score >= 100 for HOT tier.
- `skip_residential`: Overpriced (+15%), high flood risk, high permit risk
- `missing_data_residential`: All None values
- `distressed_residential`: Fire damage classification

### Known test gap

- No test coverage for Lava Search mode
- No test coverage for Flip Radar mode
- No test for `comp_count=0` + `estimated_value` path that triggered the original `_fb_` filter crash (now fixed but no regression test)

---

## 28. Operational: Codespace Idle-Kill + Keepalive

### The problem

**Symptom:** The Flask server (started with `python3 serve_report.py`, running on port 8080) keeps going offline. The log at `/tmp/regog-app.log` shows it WAS running and successfully serving requests (5+ HTTP 200s visible) — but then it dies. Subsequent curl checks return HTTP 000 (connection refused, exit code 7). The log just **stops with no Python traceback**.

**Root cause:** **Codespace idle-kill.** After ~20 minutes of inactivity, the container reaps the process. The log stopping with no error is the signature of an external kill, not a Python exception.

### The fix: `scripts/regog_keepalive.sh`

A `while true` restart-loop wrapper that makes the app self-healing regardless of cause.

```bash
#!/usr/bin/env bash
# regog_keepalive.sh — auto-restart the REGOG Flask app on any death.
# Solves the codespace-idle-kill problem: after ~20 min of inactivity the
# container reaps the process, the log just stops, and curl returns 000.

cd /workspaces/regogv8 || { echo "fatal: project dir not found" >&2; exit 1; }
echo $$ > /tmp/regog-keepalive.pid
while true; do
    python3 serve_report.py &
    CHILD_PID=$!
    wait $CHILD_PID
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 0 ]; then
        echo "[keepalive $(date -Is)] serve_report.py exited cleanly — not restarting" >> /tmp/regog-app.log
        break
    fi
    echo "[keepalive $(date -Is)] serve_report.py exited with code $EXIT_CODE — restarting in 2s" >> /tmp/regog-app.log
    sleep 2
done
```

### Known bug in the keepalive (follow-up)

The script does **NOT** install a `trap 'kill $CHILD_PID 2>/dev/null' EXIT` to forward signals. So `pkill -f regog_keepalive.sh` alone leaves `serve_report.py` orphaned (reparented to PID 1 and still running).

**Stop commands (always BOTH):**
```bash
pkill -f regog_keepalive.sh
pkill -f serve_report.py
```

**Better long-term fix:** add `trap 'kill $CHILD_PID 2>/dev/null' EXIT` to the keepalive script, then a single `pkill -f regog_keepalive.sh` will cleanly stop both. Worth a follow-up commit.

### How to start the keepalive (user's local terminal ONLY)

```bash
cd /workspaces/regogv8
nohup bash scripts/regog_keepalive.sh > /tmp/regog-app.log 2>&1 < /dev/null & disown
sleep 5
curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://localhost:8080/  # expect: 200
pgrep -f regog_keepalive   # non-empty = loop alive
```

### Why this can't be started from inside an AI agent's tool calls

The AI agent's "basher" subshell reaps every detached background process on exit. Multiple detach patterns were tried in the previous session — `setsid`, `nohup`, `disown`, Python double-fork — and none survived past the 7-second poll window. The keepalive is correct; it has to be started by the user directly in their terminal.

### Verify the app is up (no restart, just check)

```bash
pgrep -f regog_keepalive   # non-empty = loop alive
pgrep -f serve_report      # non-empty = server alive
curl -s -o /dev/null -w 'HTTP %{http_code}\n' --max-time 3 http://localhost:8080/
```

If `pgrep` shows the keepalive but `curl` fails → check `/tmp/regog-app.log` for the crash reason.
If `pgrep` is empty → the keepalive isn't running. Start it manually (see above).
If `HTTP 200` but process is gone within 30 seconds → codespace-idle-kill, re-read this section.

---

## 29. ALL KNOWN PROBLEMS & HOW THEY WERE FIXED

This section catalogs every significant bug or issue encountered during development, with the root cause and the fix applied.

### 🔴 CRITICAL BUGS (Fixed)

| # | Problem | Root Cause | Fix Applied |
|---|---------|-----------|-------------|
| 1 | **Dual database files** | Relative `DB_PATH = "regog.db"` resolved differently for CLI vs web app | Absolute path: `str(Path(__file__).parent.parent / "regog.db")` |
| 2 | **Zero results in web app** | Web app's DB missing schema columns (`style`, `property_url`) — all `upsert_property()` calls silently failed | Added `init_db()` to `serve_report.py` startup |
| 3 | **`sum(scores.values())` TypeError** | `apply_comp_fallback()` added string `_fb_source` key to scores dict, then residential/commercial scorers crashed on `sum()` | Changed to `sum(v for k,v in scores.items() if not k.startswith("_fb_"))` |
| 4 | **FEMA flood zone always returning UNKNOWN** | Used wrong geometry format in ArcGIS query (JSON geometry instead of `esriGeometryPoint`) | Rewrote with simple `geometry={lon},{lat}` + `geometryType=esriGeometryPoint` |
| 5 | **FEMA penalty unfairly tanking all scores** | `FLOOD_SCORES[None] = 8` penalized every property 8 points when flood data was missing | Changed to `FLOOD_SCORES[None] = 0` — never penalize for missing data |
| 6 | **DISTRESSED_ tier prefix corruption** | Tier labels concatenated brain classification with tier name: `"DISTRESSED_" + tier` → corrupted 102 records | Removed concatenation. Added DB migration `_fix_corrupted_tiers()`. |
| 7 | **Residential price deviation ceiling** | Binary scoring (below/above median) gave max 40 pts to every Manhattan listing | Percentile-band scoring: -60%→40, -50%→36, ..., >10%→-5 |
| 8 | **Land scoring flatlining at 76.0** | No per-acre deviation scoring, automatic bonuses creating artificial floor | Added `score_price_per_acre_deviation()`, `score_land_assessor_gap()` with PPA heuristic |
| 9 | **Commercial cap rate was dead code** | `_estimate_cap_rate()` returned 0 for all properties | GRM-based estimator with market rent estimates per state/style |
| 10 | **Land acreage NULL for most parcels** | HomeHarvest's acres column is inconsistent for land | Created `acreage_enricher.py` with 4 fallback sources (lot_sqft, description parsing, title parsing, price heuristic) |
| 11 | **Mode checkboxes trapped in disabled boxes** | `.mode-box.mode-disabled` set `pointer-events: none` on entire box, including its own checkbox | Added `pointer-events: auto !important` override on `.mode-box-header` |
| 12 | **LoopNet Playwright login flow broken** | Cloudflare-protected auth popup wouldn't capture storage_state reliably | Replaced with cookie bundle import (semicolon-separated HTTP cookies) |
| 13 | **Codespace idle-kill** | ~20 min of inactivity reaps the process with no log/error | `scripts/regog_keepalive.sh` while-true restart loop |

### 🟡 MINOR FIXES (Applied)

| # | Problem | Fix |
|---|---------|-----|
| 14 | **Comp scrollbar snapping to edges** | Removed `scroll-snap-type: x mandatory` from comp scroll CSS |
| 15 | **Error logging invisible in Flask** | Added `force=True` to `logging.basicConfig`, `import traceback`, `logger.error(traceback.format_exc())` |
| 16 | **Score key name mismatch for land** | `web/app.py` maps land's `price_per_acre_deviation` → `score_price_deviation` for UI display |
| 17 | **Lava checkbox unclickable when another mode active** | Same as #11 — checkbox pointer-events override |
| 18 | **lava_profit_pct column missing from schema** | Added `lava_profit_pct`, `lava_profit_ratio`, `lava_city` columns + migration |

---

## 30. Problems That STILL EXIST

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
| 8 | **Land score breakdown shows wrong component names in UI** | `score_price_deviation` maps to price per acre, `score_assessor_gap` maps to zoning |
| 9 | **No test coverage for `comp_count=0` + `estimated_value` path** | Critical edge case only caught in production |
| 10 | **No test coverage for Lava Search or Flip Radar modes** | |
| 11 | **Keepalive script missing signal trap** | `pkill -f regog_keepalive.sh` leaves `serve_report.py` orphaned |
| 12 | **LoopNet auth requires manual cookie paste** | User must log in to LoopNet, copy cookies, paste back — every time cookies expire |

### 🔵 ARCHITECTURE GAPS

| # | Problem | Priority |
|---|---------|----------|
| 13 | **Single point of failure on HomeHarvest** | If Realtor.com blocks HomeHarvest, the entire app stops working |
| 14 | **No sold comps for rural areas** | For loose geography scans, sold comp pool is too small (e.g., 24 comps for North Georgia) |
| 15 | **`fetch_sold_comps_near_coords()` defined twice in `redfin_scraper.py`** | Both return `[]` — dead code that shouldn't be called. **Cleanup:** delete both definitions. |
| 16 | **Stale `fetch_sold_comps()` in `homeharvest_scraper.py`** | Returns `[]` — the real one is in `redfin_scraper.py`. **Cleanup:** delete the stale function. |
| 17 | **`geocoder.py` is dead code** | Never called by any pipeline module |
| 18 | **`requirements.txt` does not exist** | Dependencies listed in this doc only (see §4) |

---

## 31. Build Doc References (sibling files)

The repo root contains a number of historical build / debug / analysis docs. **Read them in this order for deep context** (or skip and just use this V6 doc for most needs):

1. **This file** (`REGOG_REBUILD_V6.md`) — current handoff (supersedes #2)
2. (Older) `REGOG_REBUILD_V6.md` was the previous V6 doc — now replaced by this file
3. `REGOG_V5_REBUILD.md` — V5-era rebuild guide (pre-scoring-fixes)
4. `REGOG_V5_FIXES.md` — V5 scoring fix build instructions (Parts 1-7, all complete)
5. `REGOG_Comprehensive_Analysis_Audit.md` — 3-dev debug session, real scan data
6. `REGOG_Architecture_Deep_Dive.md` — every data point, scraper method, formula
7. `REGOG_Scraping_Playbook.md` — production scraping architecture, anti-blocking
8. `REGOG_V1_Build_Prompt.md` — original V1 build instructions
9. `REGOG_V4_Build_Prompt.md` — V4 build instructions (pre-keepalive, pre-cookie bundle)
10. `REGOG_V1_Status.md` — Phase 1-3 completion report
11. `REGOG_Billings_Scan_Report.md` — 3-category scan verification report (post-fixes)
12. `REGOG_Analysis_and_Debate.md` — 3-dev pipeline analysis
13. `REGOG_Scan_Analysis_and_Debate.md` — 3-dev scan verification
14. `REGOG_V4_Three_Dev_Debug_Analysis.md` — V4 debug analysis
15. `REGOG_V4_Three_Dev_Zero_Results_Debug_Analysis.md` — zero-results bug analysis
16. `REGOG_Board_Meeting_Q2_2026.md` — board meeting findings, agreed priorities
17. `REGOG_COMP_PIPELINE.md` — full comp pipeline technical doc

**Don't bother with:** `REGOG_Deal_Audit.md` doesn't exist (referenced in old docs).

---

## Quick Reference: Most Important Commands

```bash
# Verify environment
git log -1 --format='%H %s'         # expect: 5f2ca9d ... keepalive ...
git status --short                   # expect: only ?? loopnet_session.json
pytest -q                            # expect: 98 passed

# Static checks
bash -n scripts/regog_keepalive.sh
python3 -m py_compile web/app.py regog/scrapers/loopnet_auth.py

# Start the app (USER'S TERMINAL — not via AI tool calls)
cd /workspaces/regogv8
nohup bash scripts/regog_keepalive.sh > /tmp/regog-app.log 2>&1 < /dev/null & disown

# Stop the app (ALWAYS BOTH)
pkill -f regog_keepalive.sh
pkill -f serve_report.py

# Quick CLI scan
python3 regog/main.py scan residential --location "Dallas, TX" --price-max 400000 --skip-flood --limit 10

# View HOT leads
python3 regog/main.py leads --tier HOT --limit 20

# View DB stats
python3 -c "from db.database import get_connection, get_stats; conn=get_connection(); print(get_stats(conn)); conn.close()"

# Test FEMA flood zone
python3 -c "from scrapers.fema_scraper import get_flood_zone; print(get_flood_zone(32.7767, -96.7970))"

# Check corrupted tiers (should be 0)
sqlite3 regog.db "SELECT COUNT(*) FROM properties WHERE lead_tier LIKE 'DISTRESSED_%'"

# List recent git tags
git tag -l 'v*' --sort=-version:refname
```

---

*REGOG REBUILD V6 — current as of `5f2ca9d`*
*98 passing tests · SQLite · Flask SSE · Style-filtered comps · Dark UI · LoopNet cookie bundle · Codespace keepalive*
*Three scan modes: DEAL RADAR · LAVA SCAN · FLIP RADAR*
*All data sources: public, free, no API keys required*
