# REGOG REBUILD V8 — Complete From-Scratch Handoff

> **Purpose:** A new CLI agent (Codebuff / Claude / etc.) with **ZERO knowledge** of this project must be able to read this document alone and build a pixel-perfect, feature-perfect replica of the running REGOG application. Frontend, backend, database, scoring, scraping, auth, keepalive, problems, fixes, laws, rules, goals, keys, cookies — everything is captured.
>
> **Scope:** Current as of `5f2ca9d` (HEAD of `main`). Supersedes all previous REGOG_REBUILD_V*.md docs.
>
> **Audience:** Cold-start agent. Assume nothing about the project, the host OS, the deployment, or the user's tools.
>
> **Total length budget:** This document is intentionally long. It is the single source of truth. The previous V5/V6 docs are now SUPERSEDED — see the very bottom for the deprecation notice.

---

## TABLE OF CONTENTS

1. [Mission, Laws, Rules, Goals](#1-mission-laws-rules-goals)
2. [Application Overview](#2-application-overview)
3. [Tech Stack & Runtime Requirements](#3-tech-stack--runtime-requirements)
4. [Current State & Git History](#4-current-state--git-history)
5. [Project Structure (file tree)](#5-project-structure-file-tree)
6. [Quick Start (from zero)](#6-quick-start-from-zero)
7. [Dependencies (the real list)](#7-dependencies-the-real-list)
8. [Configuration (`regog/config.py`)](#8-configuration-regogconfigpy)
9. [Database (`regog/db/`)](#9-database-regogdb)
10. [Entry Points & Import Paths](#10-entry-points--import-paths)
11. [Scan Pipeline (the core loop)](#11-scan-pipeline-the-core-loop)
12. [HomeHarvest Scraper — Active Listings](#12-homeharvest-scraper--active-listings)
13. [Redfin Scraper — Sold Comps](#13-redfin-scraper--sold-comps)
14. [Optional Scrapers (Zillow / Redfin / Craigslist)](#14-optional-scrapers-zillow--redfin--craigslist)
15. [LoopNet Auth (cookie bundle import)](#15-loopnet-auth-cookie-bundle-import)
16. [FEMA Flood Zone Scraper](#16-fema-flood-zone-scraper)
17. [Brain Classifier (keyword-based)](#17-brain-classifier-keyword-based)
18. [Listing Filter (junk-out detection)](#18-listing-filter-junk-out-detection)
19. [Acreage Enricher](#19-acreage-enricher)
20. [Comp Engine (2D Expansion Search)](#20-comp-engine-2d-expansion-search)
21. [Scoring Modules (Residential / Land / Commercial)](#21-scoring-modules-residential--land--commercial)
22. [Scoring Utilities (`scoring/utils.py`)](#22-scoring-utilities-scoringutilspy)
23. [Three Scan Modes — Overview & Comparison](#23-three-scan-modes--overview--comparison)
24. [DEAL RADAR Mode (default)](#24-deal-radar-mode-default)
25. [LAVA SEARCH Mode](#25-lava-search-mode)
26. [FLIP RADAR Mode](#26-flip-radar-mode)
27. [Web App Backend (`web/app.py`)](#27-web-app-backend-webapppy)
28. [Web Frontend (`web/static/index.html`)](#28-web-frontend-webstaticindexhtml)
29. [CLI (`regog/main.py`)](#29-cli-regogmainpy)
30. [Utility Modules (`regog/utils/`)](#30-utility-modules-regogutils)
31. [Scheduler (`regog/scheduler/`)](#31-scheduler-regogscheduler)
32. [Terminal UI (`regog/ui/`)](#32-terminal-ui-regogui)
33. [Tests (`tests/`)](#33-tests-tests)
34. [Codespace Keepalive (`scripts/regog_keepalive.sh`)](#34-codespace-keepalive-scriptsregog_keepalivesh)
35. [ALL KNOWN PROBLEMS & FIXES (chronological)](#35-all-known-problems--fixes-chronological)
36. [Outstanding Issues / TODOs](#36-outstanding-issues--todos)
37. [Secrets, Keys, Cookies, Storage Files](#37-secrets-keys-cookies-storage-files)
38. [Build Doc References (sibling files)](#38-build-doc-references-sibling-files)
39. [DEPRECATION NOTICE — V5 & V6 are now SUPERSEDED](#39-deprecation-notice--v5--v6-are-now-superseded)

---

## 1. Mission, Laws, Rules, Goals

### Mission

**REGOG** (Real Estate Go/No-Go) finds underpriced, distress-flagged, or high-yield real estate listings across the United States by aggregating public data sources, classifying properties via keyword heuristics (no LLM cost), and computing a multi-signal 0-100+ score for every property scanned.

The deliverable is a web app and CLI that surface **HOT leads** to a real-estate investor. Lead = underpriced property where comp-supported median is materially above asking price, distress signals suggest motivated seller, or ARV minus repair minus asking yields high ROI.

### Laws / Hard Constraints (DO NOT BREAK)

These constraints have been tested and re-tested. If you change them, you will regress the app:

1. **`DB_PATH` MUST be absolute.** Was a relative path once. The CLI and web app resolve relative paths from their own CWDs, which differ, leading to a dual-database bug where CLI and web write to two different `regog.db` files. Use:
   ```python
   from pathlib import Path
   DB_PATH = str(Path(__file__).parent.parent / "regog.db")
   ```
2. **`FLOOD_SCORES[None] = 0`** and `"UNKNOWN" = 0`. Never penalize a property 8 points for missing FEMA data — rural areas often have no data and this tanked every score.
3. **No `DISTRESSED_` prefix on `lead_tier`.** Storing `"DISTRESSED_HOT"` corrupted 102 rows. Strip the prefix. `brain_classification` is a separate column; do not concatenate.
4. **Filter `_fb_` prefix when summing scores.** `apply_comp_fallback` adds non-numeric metadata (strings, booleans) with `_fb_` prefix. `sum(scores.values())` will TypeError on them. Filter: `sum(v for k, v in scores.items() if not k.startswith("_fb_"))`.
5. **All `__init__.py` files must exist.** Empty files are fine. Every subdirectory in `regog/`, `web/`, `tests/`.
6. **`sys.path` is mutated at module level before any import.** Top-level `import` statements for heavy modules (db, scrapers, scoring) will fail. Use **deferred imports inside functions** instead. See §10.
7. **Realtor.com is gated by HomeHarvest.** If HomeHarvest changes column names, the `g(*keys)` helper in `normalize_listing` handles it by trying 5+ fallback names per field. **Do not remove this fallback chain.**
8. **The Flask server must be started via `serve_report.py` in production.** `web/app.py`'s `__main__` block uses `debug=True`, which spawns a reloader child that `pkill -f` will leave orphaned.
9. **The keepalive wraps `serve_report.py`, not the other way around.** Keepalive restarts the Flask server, not itself.
10. **LoopNet is Cloudflare/Akamai-gated.** The IP of the codespace is denylisted. Manual cookie paste is the only path. See §15 for the cookie flow.

### Rules (project conventions to follow)

- **No LLM dependency.** Brain classifier is keyword-based. Cap-rate estimator is GRM-based with hardcoded market rents. Comp engine is geometric. No OpenAI / Anthropic / local model calls.
- **No paid API keys.** All data sources are public, free, no-auth-required: HomeHarvest (Realtor.com), FEMA ArcGIS, Redfin/Realtor.com via HomeHarvest. LoopNet is via manually-pasted cookies.
- **No production frontend framework.** UI is a single `index.html` with all CSS+JS inline. No React, no Vue, no build step. Dark theme by default.
- **Tests live in `tests/` and run via `pytest -q`.** Target: 98 tests, all green.
- **Transient fields popped before DB upsert.** `cap_rate_data`, `completeness`, `comp_acreage_matched` are in-memory only — pop, upsert, restore.
- **JSON fields round-trip via `_JSON_FIELDS` set in `db/database.py`.** Lists/dicts serialized on write, deserialized on read.
- **Scan session results are stored by `listing_id` (UNIQUE).** Re-scans UPSERT (update existing row, insert new).
- **Migrations are non-destructive.** `_run_migrations()` uses `PRAGMA table_info` to check before `ALTER TABLE ADD COLUMN`.
- **Tier assignment is `assign_tier(score)` from `scoring/utils.py`.** Uses `TIER_THRESHOLDS` (descending sort, first match wins). Default tier for score < 0 = `"SKIP"`.
- **Location input is colloquial-tolerant.** `utils/location_resolver.py` handles "South GA" → "Valdosta, GA", "NorCal" → "San Francisco, CA", bare "Georgia" → "Atlanta, GA". HomeHarvest TIMES OUT on bare state names.
- **Thread-safe scan status.** `_scan_status` is guarded by `_scan_status_lock`. Reads/writes inside the lock.
- **Cancel via `threading.Event`.** `_cancel_events[session_id].is_set()` polled at every iteration.

### Goals (what the app is trying to achieve)

- **G1 — Discover HOT leads cheaply.** Scraping + scoring + displaying in real-time must be free of API costs and run on a single codespace.
- **G2 — Three distinct scan experiences.** DEAL RADAR (default, find underpriced), LAVA SCAN (only 200%+ profit), FLIP RADAR (distress + ARV analysis). Mutually exclusive in the UI.
- **G3 — Streaming UX.** Properties appear as they're scored, not after the whole scan finishes. SSE is the transport.
- **G4 — Resilient to flaky scrapers.** Every external call has a retry or graceful-fail path. Whole scan does NOT abort on one bad listing.
- **G5 — Self-healing deployment.** Codespace idle-kills the Flask process after ~20 min. `regog_keepalive.sh` restarts it.
- **G6 — Zero-config data freshness.** Re-running a scan UPSERTs by listing_id, so the DB always reflects the most recent scrape.
- **G7 — User can save interesting properties.** `/api/saved` in-memory set, surfaced in the UI's "Saved" panel.

---

## 2. Application Overview

REGOG is a US nationwide real-estate intelligence scanner. It does the following, end-to-end:

1. **Scrapes** active listings from Realtor.com via the `homeharvest` library (free, no API key). Optionally supplements with Zillow, Redfin browser, and Craigslist.
2. **Fetches** sold comparable properties for the same market (also via HomeHarvest with `listing_type="sold"`).
3. **Classifies** each property via keyword matching (no LLM): distressed, teardown, fire-damage, vacant, luxury, standard, land-only.
4. **Filters out** auctions, bait prices, fire-damaged shells, condemned structures.
5. **Enriches** with FEMA flood zone (free ArcGIS API), permit signals (keyword inference), assessor values (already in HomeHarvest), and acreage fallbacks (4 sources).
6. **Computes comparable sales** using a **2D expansion search** (radius × time). For each listing: tries the smallest radius, expands outward, then expands the time window. Aims for ≥ 5 comps (configurable).
7. **Scores** each property 0-100+ against 5-6 signals (residential/land/commercial variants), with percentile-band pricing scoring, confidence caps, variance penalties, and a comp-fallback using `estimated_value` when no comps exist.
8. **Displays** results via:
   - **Web app** — Flask on port 8080, dark-themed single-page HTML, real-time SSE streaming, three scan modes, history, saved.
   - **CLI** — Rich console output with terminal tables, scan / leads / report / config / schedule subcommands.
9. **Three scan modes** selectable in the web UI:
   - **DEAL RADAR** 🎯 — default. Find underpriced properties. Single location, full pipeline, all tiers.
   - **LAVA SCAN** 🌋 — Only surfaces deals where `comp_median / list_price >= 2.0` (200% profit). Optional nationwide mode cycles top 20 US metros.
   - **FLIP RADAR** 🔨 — Distress-scored (DISTRESS_HIGH/MEDIUM/LOW keywords, 3/2/1 pts). ARV / repair / max-offer / profit / ROI / deal grade A/B/C/D. Property-type dropdown: single_family, multi_family, condos, commercial, townhomes, hotel, rv_park, mixed_use, all.
10. **LoopNet auth** — semicolon-separated cookie bundle import. User logs into LoopNet in their browser, pastes cookies, backend parses, saves to `loopnet_session.json`, scraper sends cookies on every request.

**Stack:** Python 3.11+ · SQLite · Flask 2.0+ · HomeHarvest · Playwright (optional) · Rich · Jinja2 · Flask-CORS.

**Zero API costs** — every data source is free.

---

## 3. Tech Stack & Runtime Requirements

| Component | Version | Required |
|-----------|---------|----------|
| Python | 3.11+ | **Required** (uses `dict[str, str]` PEP-585 syntax) |
| SQLite | 3.39+ | Built into Python — uses `journal_mode=WAL` |
| Flask | 2.0+ | Required for web app |
| Flask-CORS | 3.0+ | Required (CORS on `/api/*`) |
| HomeHarvest | 0.8+ | **Required** — only active listing source |
| BeautifulSoup4 | 4.12+ | Required (Craigslist scraper) |
| httpx | 0.25+ | Required (Craigslist, FEMA, assessor) |
| lxml | 4.9+ | Required (HomeHarvest dependency) |
| Rich | 13.0+ | Required (CLI output) |
| geopy | 2.3+ | Required (geocoding fallback) |
| APScheduler | 3.10+ | Optional (scheduled scans) |
| Jinja2 | 3.1+ | Required (HTML report generator) |
| Playwright | 1.40+ | Optional (Zillow, Redfin browser, LoopNet) |
| playwright-stealth | 1.0.6+ | Optional (Zillow bypass) |
| aiosqlite | 0.19+ | Optional (async DB) |
| sqlite-utils | 3.36+ | Optional (DB tools) |

The system is **Windows / macOS / Linux portable** but the keepalive script uses `bash` (Linux / WSL / macOS only).

### Linux-only assumptions
- `bash` shell, `setsid`, `nohup`, `disown`
- `pgrep`, `pkill`, `ss` or `netstat`
- `Xvfb` for non-headless Playwright (LoopNet login)
- `sqlite3` CLI for ad-hoc inspection (optional)

---

## 4. Current State & Git History

### Git State (HEAD = `5f2ca9d`)

- **Branch:** `main`
- **HEAD:** `5f2ca9d` — "chore: keepalive — fail-fast on missing dir, track child PID, stop on clean exit"
- **Ahead of `origin/main`:** 2-3 commits. **Not pushed.**
- **Untracked files:** `TEMP_HANDOFF.md`, `loopnet_session.json` (both gitignored, in `.gitignore`)

### Last 5 commits

1. `5f2ca9d` — chore: keepalive — fail-fast on missing dir, track child PID, stop on clean exit
2. `00481a6` — chore: LoopNet cookie bundle import + codespace keepalive (4 files: web/app.py, web/static/index.html, regog/scrapers/loopnet_auth.py, scripts/regog_keepalive.sh)
3. `788b162` — chore: also ignore *.pyo and *.pyd
4. (older) — chore: LoopNet cookie bundle import + codespace keepalive
5. (older) — v7: comprehensive REGOG_REBUILD_V6.md handoff document

### Test count
**98 tests passing.** Run `pytest -q` from project root.

### App status at the time of writing
**App was brought up via `nohup bash scripts/regog_keepalive.sh > /tmp/regog-app.log 2>&1 < /dev/null & disown`** and was responding HTTP 200 on `http://localhost:8080/` at HEAD `5f2ca9d`. DB had ~17,077 properties scored at avg 35.6.

---

## 5. Project Structure (file tree)

```
/workspaces/regogv8/
│
├── REGOG_REBUILD_V8.md          ← THIS FILE (single source of truth for rebuild)
├── README.md                    ← Minimal: "# REgog\nreal estate gog"
├── .gitignore                   ← Ignores: regog.db, regog_config.json, *.pyc, *.pyo, *.pyd,
│                                    __pycache__/, regog_report.html, loopnet_session.json,
│                                    TEMP_HANDOFF.md, .vscode/, .DS_Store, etc.
│
├── serve_report.py              ← ENTRY POINT: starts Flask web app on port 8080
├── start-regog.sh               ← Boot script (Xvfb + tmux + serve_report) — legacy
├── start-display.sh             ← Boot script (Xvfb + x11vnc + noVNC) — legacy
│
├── regog.db                     ← SQLite DB (auto-created, gitignored)
├── regog_config.json            ← Config overrides (auto-created, gitignored)
├── regog_report.html            ← Generated HTML report (gitignored)
├── loopnet_session.json         ← LoopNet cookies (UNTRACKED, gitignored — see §15/§37)
│
├── regog/                       ← Main Python package
│   ├── __init__.py              ← empty
│   ├── config.py                ← ALL settings, weights, thresholds, keywords
│   ├── main.py                  ← CLI entry point (argparse, 6 subcommands)
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.sql           ← CREATE TABLE statements + indexes
│   │   └── database.py          ← SQLite wrapper: init, CRUD, upsert, migrations, tier-fix
│   │
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── homeharvest_scraper.py   ← fetch_listings() + normalize_listing() (PRIMARY)
│   │   ├── redfin_scraper.py        ← fetch_sold_comps() + normalize_sold_listing()
│   │   ├── zillow_stealth.py        ← Playwright Zillow (optional, --use-zillow)
│   │   ├── redfin_playwright.py     ← Playwright Redfin browser (optional, --use-redfin)
│   │   ├── craigslist_scraper.py    ← HTTPX+BS Craigslist FSBO (optional, --use-craigslist)
│   │   ├── loopnet_auth.py          ← LoopNet cookie loader (Cookie header on all requests)
│   │   ├── fema_scraper.py          ← FEMA flood zone API (free ArcGIS)
│   │   ├── assessor_scraper.py      ← Assessor data + county registry
│   │   └── permit_scraper.py        ← Permit signal inference
│   │
│   ├── enrichment/
│   │   ├── __init__.py
│   │   ├── brain.py                 ← Keyword property classifier
│   │   ├── comp_engine.py           ← 2D expansion comp search (the deal-finding engine)
│   │   ├── enricher.py              ← Orchestrates: acreage → assessor → FEMA → permits
│   │   ├── listing_filter.py        ← Filters out auctions, bait, burned, demolition
│   │   ├── acreage_enricher.py      ← 4-source acreage fallback
│   │   └── geocoder.py              ← DEAD CODE — never called
│   │
│   ├── scoring/
│   │   ├── __init__.py
│   │   ├── utils.py                 ← Shared: tiers, fallback, confidence, variance, completeness
│   │   ├── residential_score.py     ← 0-100 scoring for homes (6 components)
│   │   ├── land_score.py            ← 0-100 scoring for land (7 components)
│   │   └── commercial_score.py      ← 0-100 scoring for commercial (5 components + GRM cap-rate)
│   │
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── scan_scheduler.py        ← APScheduler recurring scans
│   │
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── terminal.py              ← Rich console output (tables, panels, banners)
│   │   ├── report_generator.py      ← Jinja2 HTML report generator
│   │   └── templates/
│   │       └── report.html.j2       ← HTML report template
│   │
│   └── utils/
│       ├── __init__.py
│       ├── property_type.py         ← Style → category mapping (residential/land/commercial)
│       ├── density.py               ← ZIP → urban/suburban/rural
│       ├── rate_limiter.py          ← Per-source request throttling + exponential backoff
│       ├── config_store.py          ← JSON config file (regog_config.json)
│       ├── dedup.py                 ← Address-normalized dedup
│       └── location_resolver.py     ← Colloquial → "City, ST" resolution
│
├── web/
│   ├── __init__.py              ← "# REGOG Web App"
│   ├── app.py                   ← Flask backend: API + SSE + background scans + LoopNet endpoints
│   └── static/
│       └── index.html           ← Single-page dark UI (ALL CSS+JS inline) — 2400+ lines
│
├── scripts/
│   └── regog_keepalive.sh       ← while-true restart wrapper (see §34)
│
└── tests/
    ├── __init__.py              ← empty
    ├── conftest.py              ← 5 fixtures (standard, hot, skip, missing, distressed)
    ├── test_residential_score.py ← 50+ tests
    ├── test_land_score.py       ← Land scoring tests
    ├── test_scoring_fallback.py ← _fb_ fallback tests
    ├── test_utils.py            ← assign_tier + parse_flags tests
    └── test_permit_scraper.py   ← Permit inference tests
```

### What does NOT exist (gotchas)
- No `requirements.txt` — install from the dependency list (§7).
- No `geocoder.py` usage anywhere — it's dead code.
- No `redfin_scraper.py` calls to `fetch_sold_comps_near_coords()` — that function is defined twice and returns `[]` both times.
- No `homeharvest_scraper.fetch_sold_comps()` calls — that function is stale, returns `[]`. Use `redfin_scraper.fetch_sold_comps()`.

---

## 6. Quick Start (from zero)

```bash
# 1. Clone / create project at /workspaces/regogv8
cd /workspaces/regogv8

# 2. Create venv
python3 -m venv venv && source venv/bin/activate

# 3. Install dependencies (no requirements.txt — use the list in §7)
pip install homeharvest beautifulsoup4 httpx lxml rich geopy apscheduler jinja2 playwright flask flask-cors
playwright install chromium

# 4. Initialize the database (creates regog.db, runs migrations, fixes corrupted tiers)
python3 -c "from db.database import init_db; init_db()"

# 5. Run tests (98 expected passing)
pytest -q

# 6. Start the web app via the keepalive (USER'S LOCAL TERMINAL — see §34 for why)
nohup bash scripts/regog_keepalive.sh > /tmp/regog-app.log 2>&1 < /dev/null & disown
sleep 5
curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://localhost:8080/   # expect 200

# 7. Or use the CLI directly
python3 regog/main.py scan residential --location "Dallas, TX" --price-max 400000
python3 regog/main.py leads --tier HOT --limit 20

# 8. Stop the app
pkill -f regog_keepalive.sh
pkill -f serve_report.py
```

---

## 7. Dependencies (the real list)

```bash
pip install homeharvest>=0.8.0 \
            beautifulsoup4>=4.12.0 \
            httpx>=0.25.0 \
            lxml>=4.9.0 \
            rich>=13.0.0 \
            geopy>=2.3.0 \
            apscheduler>=3.10.0 \
            jinja2>=3.1.0 \
            playwright>=1.40.0 \
            flask>=2.0 \
            flask-cors>=3.0
# Optional (Zillow bypass, async DB, DB tooling)
pip install playwright-stealth>=1.0.6
pip install aiosqlite>=0.19.0 sqlite-utils>=3.36

# Playwright browser binaries (one-time)
playwright install chromium
```

**There is no `requirements.txt` file in the repo** — the user is supposed to know the list. If a future agent wants to add a `requirements.txt`, this is the canonical list.

---

## 8. Configuration (`regog/config.py`)

**All tunable parameters live in ONE file: `regog/config.py`.** It uses module-level constants and one function.

### Database path (CRITICAL — see §1 Law #1)

```python
from pathlib import Path
DB_PATH = str(Path(__file__).parent.parent / "regog.db")   # ABSOLUTE — never relative
```

### Scoring weights

```python
RESIDENTIAL_WEIGHTS = {
    "price_deviation":   0.40,   # how far below median comp price (percentile-band)
    "dom_signal":        0.15,   # days-on-market anomaly
    "assessor_gap":      0.20,   # listed vs assessed value gap
    "condition":         0.15,   # brain classification
    "flood_penalty":     0.10,   # FEMA zone deduction
}

LAND_WEIGHTS = {
    "price_per_acre_deviation": 0.40,
    "zoning_bonus":             0.20,
    "road_access_bonus":        0.10,
    "utilities_bonus":          0.10,
    "acreage_premium":          0.10,
    "flood_penalty":            0.10,
}

COMMERCIAL_WEIGHTS = {
    "price_deviation":    0.35,
    "assessor_gap":       0.25,
    "cap_rate_estimate":  0.20,
    "condition":          0.10,
    "flood_penalty":      0.10,
}
```

### Lead tiers (current V8 thresholds)

```python
TIER_THRESHOLDS = {
    "HOT":    100,   # score >= 100 (uncapped) qualifies as HOT
    "MEDIUM":  50,   # 50-99: solid leads
    "WARM":     0,   # 0-49: low-priority
}
# SKIP is implicit for any score < 0 (no explicit key)
# NOTE: RISKY tier was REMOVED in V6. Current thresholds are HOT/MEDIUM/WARM + implicit SKIP.
```

### Comp engine defaults

```python
COMP_DEFAULTS = {
    "radius_miles":      3,
    "min_comps_required": 3,
    "max_radius_miles":  10,
    "similar_sqft_pct":  0.30,   # ±30% sqft for residential
    "similar_acres_pct": 0.50,   # ±50% acres for land
    "similar_beds_range":  1,    # ±1 bedroom for residential
    "similar_baths_range": 1,   # ±1 bathroom for residential
    "sold_months":        12,    # look-back window
}

MIN_COMPS_REQUIRED = 5   # minimum comps before accepting a tier
COMP_LOOKBACK_TIERS = [180, 270, 365, 540, 730]  # 2 years max
COMP_STALENESS_PENALTY = 0.15   # 15% confidence reduction when lookback > 365d
COMP_CONFIDENCE_HIGH   = 0.80
COMP_CONFIDENCE_MEDIUM = 0.50
COMP_CONFIDENCE_LOW    = 0.00

# Comp search radii — 3 tiers per density per category
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

### Sold comp pool sizing (Part 4 fix)

```python
SOLD_COMPS_BASE = 300           # minimum pool size
SOLD_COMPS_PER_LISTING = 0.15   # 15% of active listing count
SOLD_COMPS_MAX = 2000           # hard cap

def get_comp_pool_size(active_listing_count: int) -> int:
    """Calculate the comp pool size for a scan. Scales with listing volume."""
    dynamic = int(active_listing_count * SOLD_COMPS_PER_LISTING)
    return max(SOLD_COMPS_BASE, min(dynamic, SOLD_COMPS_MAX))
```

### FEMA flood zone scoring (CRITICAL — see §1 Law #2)

```python
FLOOD_SCORES = {
    "X":       10,   # minimal risk — no penalty
    "AE":       3,   # high risk — 7pt penalty
    "A":        4,   # high risk
    "VE":       0,   # coastal extreme — full penalty
    "UNKNOWN":  0,   # no data — ZERO penalty. Never penalize for missing data.
    None:       0,   # null flood_zone yields 0, not 8.
}
# CRITICAL: FLOOD_SCORES[None] WAS 8. Changed to 0 (Law #2). The old default
# penalized every property 8 pts when flood zone was unknown. Since FEMA
# data is unreliable and often missing for rural areas, this was
# unfairly tanking scores.
```

### Other scoring maps

```python
CONDITION_SCORES = {
    "standard":     15, "luxury":  12, "vacant":       10,
    "distressed":    7, "teardown": 4, "fire_damage":   3,
}
PERMIT_SCORES = {"low": 3, "unknown": 0, "medium": -2, "high": -5}

DOM_SCORE_BRACKETS = [
    (30,         15),   # 0-30 days → 15 pts
    (90,         10),   # 31-90 days → 10 pts
    (180,         5),   # 91-180 days → 5 pts
    (365,         2),   # 181-365 days → 2 pts
    (float("inf"), 0),  # 365+ → 0 pts (was 2, now 0 to enable SKIP)
]

SCAN_DEFAULTS = {"past_days": 180}   # was 90 — increased to capture older inventory
HIGH_RISE_MIN_STORIES = 5           # CONDO with >=5 stories → reclassified as commercial
```

### Brain classifier keywords (no LLM)

```python
CLASSIFICATION_KEYWORDS = {
    "distressed":  ["distressed", "as-is", "needs work", "fixer-upper",
                    "deferred maintenance", "needs tlc", "handyman special",
                    "fixer upper", "repairs needed", "needs renovation",
                    "needs repair", "cosmetic issues"],
    "teardown":    ["teardown", "tear down", "land value", "land only",
                    "buildable lot", "scrape", "demolish", "knockdown",
                    "lot for sale"],
    "fire_damage": ["fire damage", "smoke damage", "water damage", "burnt",
                    "burned", "fire-damaged", "structure fire"],
    "vacant":      ["vacant", "abandoned", "unoccupied", "boarded up",
                    "vacant lot", "vacant property", "no occupants"],
    "luxury":      ["luxury", "high-end", "high end", "premium", "estate",
                    "gourmet kitchen", "marble", "custom built", "architect",
                    "panoramic view", "oceanfront", "waterfront"],
}

SELLER_MOTIVATION_KEYWORDS = {
    "high":   ["motivated seller", "priced to sell", "bring all offers",
               "must sell", "relocation", "divorce", "estate sale",
               "short sale", "pre-foreclosure", "bankruptcy",
               "price reduced", "price reduction"],
    "medium": ["open to offers", "flexible", "seller motivated",
               "offers encouraged"],
}

RED_FLAG_KEYWORDS = [
    "foundation issues", "structural", "mold", "termites", "roof leak",
    "electrical", "plumbing", "septic", "well water", "no heat",
    "no ac", "code violation", "unpermitted", "lien", "title issue",
]

GREEN_FLAG_KEYWORDS = [
    "renovated", "updated", "new roof", "new hvac", "new windows",
    "new kitchen", "new bath", "remodeled", "move-in ready",
    "turnkey", "investment opportunity", "positive cash flow",
    "tenant occupied", "rental", "income producing",
]
```

### Rate limits (per source)

```python
RATE_LIMITS = {
    "realtor":    {"delay_min": 2, "delay_max": 5, "max_per_hour": 200},
    "redfin":     {"delay_min": 1, "delay_max": 3, "max_per_hour": 300},
    "zillow":     {"delay_min": 4, "delay_max": 9, "max_per_hour":  60},
    "assessor":   {"delay_min": 3, "delay_max": 8, "max_per_hour": 100},
    "craigslist": {"delay_min": 3, "delay_max": 7, "max_per_hour":  80},
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
]
```

---

## 9. Database (`regog/db/`)

### `schema.sql` — 3 tables

#### `properties` — 65+ columns

**Identity / source:**
`id`, `listing_id` (UNIQUE), `source` ('realtor' | 'redfin' | 'zillow' | 'loopnet'), `scan_type` ('residential' | 'land' | 'commercial' | 'flip'), `commercial_subtype` ('multifamily' | 'hotel' | 'industrial' | 'office' | 'retail' | 'skyscraper' | null), `scan_session_id`

**Address / location:**
`address`, `city`, `state`, `zip`, `lat`, `lon`, `county`

**Listing facts:**
`list_price`, `price_per_sqft`, `price_per_acre`, `sqft`, `acres`, `beds`, `baths`, `year_built`, `lot_sqft`, `days_on_market`, `listing_status`, `listing_description`, `price_history` (JSON), `last_sold_price`, `last_sold_date`, `stories`, `primary_photo`, `property_url`, `style`

**Assessor:**
`assessed_value`, `estimated_value` (AVM, Zestimate-like), `assessed_year`, `zoning`

**Enrichment signals:**
`flood_zone` (FEMA), `permit_flags` (JSON: `{unpermitted_additions, recent_permits, code_violations, permit_risk}`)

**Brain classifier output:**
`brain_classification` (one of: luxury | standard | distressed | teardown | fire_damage | vacant | land_only), `brain_red_flags` (JSON list), `brain_green_flags` (JSON list), `brain_seller_motivation` ('high' | 'medium' | 'low')

**Comp engine output:**
`comp_median_price`, `comp_count`, `comp_radius_miles`, `comp_price_per_sqft_median`, `comp_price_per_acre_median`, `comp_confidence` (legacy, use `comp_confidence_label`), `comp_listings` (JSON: top 10 comps with full details), `comp_lookback_used`, `comp_confidence_label` ('HIGH' | 'MEDIUM' | 'LOW'), `comp_staleness_penalty_applied` (0/1), `comp_price_range`, `comp_price_stddev`, `comp_variance_high` (0/1)

**Scoring output:**
`score_total`, `score_price_deviation`, `score_dom_signal`, `score_assessor_gap`, `score_condition`, `score_acreage_value`, `score_flood_penalty`, `lead_tier`, `price_deviation_pct`, `data_confidence`

**Lava Search (V7+):**
`lava_profit_pct` (REAL), `lava_profit_ratio` (REAL), `lava_city` (TEXT)

**Filter output:**
`filter_reason`, `filter_type`

**Flip Radar (V7+):**
Stored dynamically in the `properties` row but no dedicated columns — fields like `flip_distress_score`, `flip_arv`, `flip_repair_cost`, `flip_max_offer`, `flip_projected_profit`, `flip_roi_pct`, `flip_deal_grade`, `flip_rehab_tier`, `flip_keywords` are part of the JSON-serialized payload.

**Timestamps:**
`first_seen`, `last_updated`

#### `scan_sessions`
`id` (8-char UUID PK), `started_at`, `completed_at`, `scan_type`, `search_params` (JSON: `{location, scan_type, price_min, price_max, lava_mode, lava_min_profit, lava_scope, lava_state, flip_property_type, search_location, location_resolution_method}`), `properties_found`, `hot_leads_found`

#### `price_history_tracking`
`id` (PK), `listing_id` (FK), `recorded_at`, `price`, `days_on_market`

### Indexes
```sql
idx_properties_listing_id, idx_properties_scan_session,
idx_properties_tier, idx_properties_score (DESC), idx_properties_location (city, state)
```

### JSON round-trip (`database.py`)

```python
_JSON_FIELDS = {
    "brain_red_flags",
    "brain_green_flags",
    "price_history",
    "permit_flags",
    "comp_listings",
}

def _serialize_value(key, value):
    if key in _JSON_FIELDS and isinstance(value, (list, dict)):
        return json.dumps(value)
    return value

def _deserialize_row(row):
    d = dict(row)
    for key in _JSON_FIELDS:
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d
```

### Key functions in `db/database.py`

| Function | Purpose |
|----------|---------|
| `init_db(db_path=None)` | Reads `schema.sql`, runs `_run_migrations()`, runs `_fix_corrupted_tiers()`. Prints status. |
| `_run_migrations(conn)` | `PRAGMA table_info` → `ALTER TABLE ADD COLUMN` for 22+ columns. **Non-destructive.** |
| `_fix_corrupted_tiers(conn)` | Strips `DISTRESSED_` prefix from any `lead_tier` like `DISTRESSED_HOT` (Law #3). |
| `create_scan_session(conn, scan_type, search_params)` | INSERT, returns 8-char UUID. |
| `complete_scan_session(conn, session_id, props_found, hot_leads)` | UPDATE completed_at + counts. |
| `upsert_property(conn, prop)` | INSERT OR UPDATE by `listing_id`. Returns True if new, False if updated. JSON-serializes `_JSON_FIELDS`. |
| `get_session_properties(conn, session_id)` | SELECT * for session, ORDER BY score_total DESC. |
| `get_leads_by_tier(conn, tier, limit=20)` | Top properties by tier. |
| `search_properties(conn, scan_type, tier, score_min, city, state, zip_code, price_min, price_max, limit=50)` | Filtered search. |
| `get_stats(conn)` | Returns `{total_properties, hot_leads, warm_leads, scan_sessions, avg_score}`. |
| `_deserialize_row(row)` | Parses JSON fields on read. |

### Transient fields popped before upsert

These fields are in-memory only — `pop` before `upsert_property()`, then `restore` for the SSE stream:

- `property_url` (now in schema via migration, but still popped for safety)
- `style` (now in schema via migration, but still popped for safety)
- `cap_rate_data` — commercial GRM estimator output, not in schema
- `completeness` — score completeness dict, not in schema
- `comp_acreage_matched` — bool, not in schema

**All three callers** (`regog/main.py`, `web/app.py` for both scan modes, scheduled scans) pop/restore identically:

```python
cap_rate_data = prop.pop("cap_rate_data", None)
completeness_data = prop.pop("completeness", None)
comp_acreage_matched = prop.pop("comp_acreage_matched", None)

upsert_property(conn, prop)

if cap_rate_data:    prop["cap_rate_data"]    = cap_rate_data
if completeness_data: prop["completeness"]    = completeness_data
if comp_acreage_matched is not None: prop["comp_acreage_matched"] = comp_acreage_matched
```

---

## 10. Entry Points & Import Paths

### The five entry points

| File | Purpose | Command |
|------|---------|---------|
| `serve_report.py` | **Web app** (Flask, port 8080) | `python3 serve_report.py` |
| `regog/main.py` | **CLI** (argparse subcommands) | `python3 regog/main.py <command>` |
| `regog/scheduler/scan_scheduler.py` | **Scheduled scans** (APScheduler) | Imported by `main.py schedule` |
| `regog/scrapers/loopnet_auth.py` | **LoopNet auth + scrape** (Playwright) | `python3 -m scrapers.loopnet_auth login` |
| `scripts/regog_keepalive.sh` | **Keepalive wrapper** (bash) | `nohup bash scripts/regog_keepalive.sh &` |

### `serve_report.py` — THE web app entry point

```python
#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.dirname(__file__))                # project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "regog"))  # regog/ package

from db.database import init_db
init_db()      # RUNS MIGRATIONS — CRITICAL for new columns (Law #1)

from web.app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
```

### Import path setup (CRITICAL)

Every entry point must add the project root AND `regog/` to `sys.path` BEFORE any REGOG imports, because the package uses **deferred imports inside functions**.

| Entry point | `sys.path.insert(0, ...)` calls |
|------------|----------------------------------|
| `serve_report.py` | `os.path.dirname(__file__)`, `os.path.join(os.path.dirname(__file__), "regog")` |
| `regog/main.py` | `str(Path(__file__).parent)` |
| `web/app.py` | `str(Path(__file__).parent.parent / "regog")`, `str(Path(__file__).parent.parent)` |
| `tests/conftest.py` (implicit) | Tests add `str(Path(__file__).parent.parent / "regog")` |

### Deferred imports pattern (CRITICAL — Law #6)

Both `regog/main.py` and `web/app.py` import heavy modules **inside functions**, never at module level:

```python
def cmd_scan(args):
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
    # ... rest of function
```

**Why:** `sys.path` is modified at module level BEFORE any function is called. Top-level imports would execute before `sys.path` is ready → `ModuleNotFoundError: No module named 'db'`.

### All `__init__.py` files must exist

Empty files are fine. Every subdirectory needs one: `scrapers/`, `db/`, `enrichment/`, `scoring/`, `ui/`, `utils/`, `scheduler/`, `tests/`, `web/`. This is what makes them Python packages.

---

## 11. Scan Pipeline (the core loop)

Both CLI and web app follow this same pipeline, with mode-specific branches. The DEAL RADAR web path is the canonical reference.

```
┌────────────────────────────────────────────────────────────────────────┐
│  1. Resolve loose location                                             │
│     • utils.location_resolver.resolve_with_details()                   │
│     • "South GA" → "Valdosta, GA"                                      │
│     • Persist resolved location into scan_sessions.search_params        │
└────────────────────────────────────────────────────────────────────────┘
                                ↓
┌────────────────────────────────────────────────────────────────────────┐
│  2. Fetch SOLD comps                                                   │
│     • redfin_scraper.fetch_sold_comps(location, scan_type, past_days)  │
│     • Dynamic pool size: get_comp_pool_size(listing_count)             │
│       min 300, max 2000, scales 0.15 × active count                    │
└────────────────────────────────────────────────────────────────────────┘
                                ↓
┌────────────────────────────────────────────────────────────────────────┐
│  3. Fetch ACTIVE listings (primary source)                             │
│     • homeharvest_scraper.fetch_listings(location, "for_sale")         │
└────────────────────────────────────────────────────────────────────────┘
                                ↓
┌────────────────────────────────────────────────────────────────────────┐
│  4. (Optional) Fetch secondary sources                                 │
│     • --use-zillow     → zillow_stealth.fetch_zillow_listings()        │
│     • --use-redfin     → redfin_playwright.scrape_redfin_listings()    │
│     • --use-craigslist → craigslist_scraper.scrape_craigslist_housing│
│     • merge_and_deduplicate() if secondary sources used                │
└────────────────────────────────────────────────────────────────────────┘
                                ↓
┌────────────────────────────────────────────────────────────────────────┐
│  5. For EACH listing:                                                  │
│     a. normalize_listing(raw_dict → property schema)                   │
│     b. Price filter (skip if outside min/max)                          │
│     c. classify_property() — brain (keyword-based)                     │
│     d. filter_listing() — skip auctions, bait, burned, demolition      │
│     e. enrich_property() — acreage → assessor → FEMA → permits        │
│     f. calculate_comps() — 2D expansion (radius × time)               │
│     g. score_residential/land/commercial() → scores dict + total + tier│
│        + apply_comp_fallback / confidence_cap / variance_penalty       │
│     h. upsert_property(conn, prop) → DB                                │
│     i. (web app only) progress_q.put(dict(prop)) → SSE stream          │
└────────────────────────────────────────────────────────────────────────┘
                                ↓
┌────────────────────────────────────────────────────────────────────────┐
│  6. (Mode-specific overlays, applied before upsert)                    │
│     • LAVA: filter comp_median/list_price >= lava_min_profit           │
│     • FLIP: score_distress() >= 2, compute_flip_metrics(), _flip_tier  │
│     • DEAL: nothing — all properties emitted with their tier           │
└────────────────────────────────────────────────────────────────────────┘
                                ↓
┌────────────────────────────────────────────────────────────────────────┐
│  7. complete_scan_session()                                            │
│     • UPDATE scan_sessions SET completed_at, properties_found,         │
│       hot_leads_found                                                  │
│     • Final status push to SSE: event: complete                        │
└────────────────────────────────────────────────────────────────────────┘
```

### Property type mapping (for HomeHarvest)

```python
property_types = {
    "residential": ["single_family", "mobile"],
    "land":        ["land"],
    "commercial":  ["multi_family", "apartment", "condos", "townhomes", "duplex_triplex", "farm"],
}.get(scan_type)
```

### Cancel & status (web app only)

```python
# Check before processing each property
if _cancel_events.get(session_id, threading.Event()).is_set():
    # Update status, complete session, return
    ...

# Update status every 10 properties (or every iteration for fast scans)
if i % 10 == 0:
    with _scan_status_lock:
        _scan_status[session_id] = {
            "status": "scanning",
            "progress": i,
            "hot_count": hot_count,
            "total": total,
            ...
        }
```

---

## 12. HomeHarvest Scraper — Active Listings

**File:** `regog/scrapers/homeharvest_scraper.py`

### `fetch_listings(location, listing_type="for_sale", past_days=90, property_type=None) → list[dict]`

```python
# Uses homeharvest library:
from homeharvest import scrape_property
df = scrape_property(location=..., listing_type=..., past_days=..., property_type=...)
properties = df.to_dict(orient="records")
```

- Returns `[]` gracefully if `homeharvest` not installed.
- Logs scrape attempt and result count.
- Past_days default is 90 (CLI flag `--past-days` overrides).

### `normalize_listing(raw, source="realtor", scan_session_id=None, scan_type="residential") → dict`

**THE MOST CRITICAL NORMALIZATION FUNCTION.** Maps HomeHarvest's varied column names to REGOG's schema.

Uses the `g(*keys)` helper pattern:

```python
def g(*keys):
    for k in keys:
        v = raw.get(k)
        if v is not None:
            return v
    return None
```

#### Field mapping (tries 3-10 column names per field)

| REGOG Field | HomeHarvest Keys Tried (in order) |
|------------|----------------------------------|
| `listing_id` | `property_id`, `listing_id`, `mls_id`, `id` → fallback: `f"{source}_{hash(address+price)}"` |
| `style` | `style`, `property_type`, `home_type` — **CRITICAL for comp matching** |
| `address` | `full_street_line`, `street`, `address`, `full_address`, `formatted_address` |
| `city` | `city`, `municipality` |
| `state` | `state`, `province` |
| `zip` | `zip`, `zip_code`, `postal_code` |
| `list_price` | `list_price`, `price`, `current_price`, `sold_price` |
| `price_per_sqft` | `price_per_sqft`, `ppsf`, `price_sqft` — also computed from `price/sqft` |
| `sqft` | `sqft`, `square_feet`, `sq_ft`, `living_area`, `building_area` |
| `acres` | `acres`, `acreage`, `lot_size_acres`, `lot_acres`, `total_acres`, `parcel_acres`, `land_area`, `land_acres`, `area_acres`, `gross_acres`, `net_acres`, `lot_area_acres` |
| `beds` | `beds`, `bedrooms`, `baths_full`, `bathrooms_full` |
| `baths` | `full_baths`, `baths`, `bathrooms`, `bathrooms_total` |
| `year_built` | `year_built` |
| `lot_sqft` | `lot_sqft`, `lot_size_sqft`, `lot_area`, `land_sqft`, `parcel_sqft`, `lot_size`, `lot_area_sqft`, `land_area_sqft`, `lot_square_feet` |
| `days_on_market` | `days_on_market`, `dom`, `days_on_mls`, `listing_age` |
| `property_url` | `property_url`, `rdc_web_url`, `href`, `url` |
| `last_sold_price` | `last_sold_price`, `sold_price` |
| `last_sold_date` | `last_sold_date`, `sold_date` |
| `estimated_value` | `estimated_value`, `value`, `zestimate`, `avm_value` |
| `assessed_value` | `assessed_value`, `tax_assessment`, `assessed_valuation` |
| `listing_description` | `description`, `listing_description`, `text`, `remarks`, `public_remarks` |
| `primary_photo` | `primary_photo`, `photo`, `image_url`, `thumbnail_url` |
| `stories` | `stories`, `num_stories`, `floors`, `total_stories` |
| `county` | `county`, `parish` |
| `listing_status` | `status`, `listing_status`, `property_status`, `sale_type` |

**Acres fallback chain:** if acres is still None, derive from `lot_sqft / 43560` (Source 1 in `acreage_enricher`).
**Sqft fallback for land:** if no sqft but has acres, `sqft = acres * 43560`.
**Price per acre:** computed from `price / acres` if not directly available.
**Helpers `num(v)` and `flt(v)`** are defined **INSIDE** `normalize_listing`, BEFORE use.

### STALE function (do not call)

```python
def fetch_sold_comps(lat, lon, radius_miles=3, scan_type="residential") -> list[dict]:
    """STALE — Do NOT use. See scrapers/redfin_scraper.py for the real implementation."""
    return []
```

The real sold comps function is in `redfin_scraper.py`.

---

## 13. Redfin Scraper — Sold Comps

**File:** `regog/scrapers/redfin_scraper.py`

Despite the name, this scraper uses **HomeHarvest under the hood** (which fetches Realtor.com data — Redfin and Realtor share sold listings data). Named "redfin" for historical reasons.

### `fetch_sold_comps(location, scan_type="residential", past_days=180, limit=200) → list[dict]`

```python
df = scrape_property(
    location=location,
    listing_type="sold",
    past_days=past_days,
    property_type=property_types,
    limit=limit,
)
```

Property type mapping (same as active):
```python
property_types = {
    "residential": ["single_family", "mobile"],
    "land":        ["land"],
    "commercial":  ["multi_family", "apartment", "condos", "townhomes", "duplex_triplex", "farm"],
}.get(scan_type)
```

Each raw row is normalized via `normalize_sold_listing(raw, scan_type)`. Returns `[]` gracefully if `homeharvest` not installed.

### `normalize_sold_listing(raw, scan_type="residential") → dict | None`

**Explicitly handles sold-specific column names** (the for-sale normalizer is a separate function with a different key set):

| REGOG Field | Sold Column Names Tried |
|------------|------------------------|
| `list_price` | `sold_price`, `last_sold_price`, `close_price`, `sale_price`, `price`, `list_price` |
| `last_sold_date` | `last_sold_date`, `sold_date`, `close_date`, `closing_date` |
| `listing_status` | Force-set to `"sold"` |

**Returns `None` if no `sold_price`** (critical field). The comp engine then has zero comps to work with — `apply_comp_fallback` may use `estimated_value` as a proxy.

Same acres/sqft derivation logic as `normalize_listing`. Same `g()` / `num()` / `flt()` helpers defined inside.

### `fetch_sold_comps_near_coords()` — DEAD CODE (defined twice, both return `[]`)

```python
def fetch_sold_comps_near_coords(lat, lon, radius_miles=3, scan_type="residential", limit=50):
    """Coordinate-based sold comps not yet available. Use city-level fetch."""
    return []

# ↑ DEFINED TWICE IN THE FILE — both return []. HomeHarvest doesn't support
# coordinate-based queries. CLEANUP: delete both definitions.
```

---

## 14. Optional Scrapers

### Zillow (`scrapers/zillow_stealth.py`) — `--use-zillow`

Playwright-based Zillow scraper with anti-bot measures. Optional. Activated via CLI flag or web API flag.

**Anti-bot stack:**
1. `playwright-stealth` patches browser fingerprint vectors
2. Viewport randomization (5 sizes: 1280×720 to 1920×1080)
3. User agent rotation (5 modern Chrome/Firefox UAs from `config.USER_AGENTS`)
4. Locale/timezone randomization (en-US, en, en-GB; America/New_York timezone)
5. Human-like scrolling: 300-800px with 0.5-2s random pauses, sometimes scrolls back up
6. `--disable-blink-features=AutomationControlled` removes `navigator.webdriver=true`

**Data extraction (3 methods, in order):**
1. Next.js/Apollo JSON — extracts embedded JSON from Zillow's page state
2. DOM parsing fallback — queries `[data-test="property-card"]`
3. Returns deduplicated listings (~40 per page, `max_pages` configurable)

**Unique import pattern:**
```python
from utils.rate_limiter import rate_limit as _shared_rate_limit, report_success as _report_success, report_error as _report_error
```
This aliasing pattern is unique to `zillow_stealth.py` and not used in any other scraper.

### Redfin Playwright (`scrapers/redfin_playwright.py`) — `--use-redfin`

Playwright-based Redfin browser scraper. Two extraction methods:
1. Embedded JSON — extracts `homeData` from React server props
2. DOM fallback — parses `[data-rf-test-id="abp-homecard"]` elements

Returns `[]` if Playwright not installed.

### Craigslist (`scrapers/craigslist_scraper.py`) — `--use-craigslist`

HTTPX + BeautifulSoup scraper for FSBO/motivated seller listings. No API key needed.

- Maps 20+ city names to Craigslist subdomains via `CL_CITY_MAP`.
- Scrapes 3 subcategories: `reo` (real estate by owner), `rea` (land), `reb` (commercial).
- Parses title, price, beds/baths/sqft from CL post listings.
- Returns 0 results if city not in the map.
- **Rate limited** via shared rate limiter (3-7s delay, 80/hour).

### Deduplication (`utils/dedup.py`)

When multiple sources are used, `merge_and_deduplicate()` normalizes addresses and removes duplicates. Primary source (HomeHarvest) wins on conflicts.

---

## 15. LoopNet Auth (cookie bundle import)

**Files:** `regog/scrapers/loopnet_auth.py` + endpoints in `web/app.py`

### The old vs new flow

**OLD (deprecated, broken):** Playwright login popup, then save the `storage_state` to a file. Fragile, hard to maintain, and broke when Akamai protected the auth flow.

**NEW (current, since `00481a6`):** User pastes a semicolon-separated cookie bundle from DevTools → backend parses → saved to `loopnet_session.json` → scraper sends cookies on every request via `Cookie` header.

### Endpoints (in `web/app.py`)

#### `POST /api/loopnet/save-cookie`

Accepts `{"cookies": "SessionFarm_GUID=...; UserPreferences=...; UserInfo_AssociateID=..."}`. Parses and saves to `loopnet_session.json`.

The parser is `_parse_cookie_bundle(bundle: str) -> dict` and returns:
```python
{
    "cookies":          {name: value, ...},
    "cookie_string":    "name1=value1; name2=value2; ...",   # rebuilt, normalized
    "saved_at":         "ISO-8601 with Z suffix",
    "missing_expected": ["TDID", "UserPreferences", ...],   # which expected cookies are absent
    "expected_cookies": ["SessionFarm_GUID", "UserPreferences", "UserInfo_AssociateID"],
}
```

**Validation:** raises `ValueError` on:
- Empty bundle (`if not bundle or not bundle.strip()`)
- Entry missing `=`
- Empty cookie name
- Empty cookie value

The endpoint passes `data.get("cookies") or ""` to the parser — an empty string is handled correctly.

**Length cap:** max 8192 chars (rejected with 400 if longer).

#### `GET /api/loopnet/session/status`

Returns:
```python
{
    "exists": bool,
    "path": str,
    "age_minutes": float | None,
    "cookie_count": int,
    "missing_expected": list[str],
}
```

**Guarded against old `storage_state` format** via `isinstance(_cookies, dict)` check — the old shape stored cookies as a Playwright list, not a dict.

### Expected cookies (3, not 5)

```python
EXPECTED_LOOPNET_COOKIES = [
    "SessionFarm_GUID",
    "UserPreferences",
    "UserInfo_AssociateID",
]
# TDID and TDCPM (The Trade Desk / ad-tracking) intentionally EXCLUDED.
# Browsers are phasing them out and they aren't needed for LoopNet auth.
# Surfaced back to the UI so the user knows when their DevTools export was incomplete.
```

### UI flow (in `web/static/index.html`)

1. User logs into LoopNet in their browser (Chrome, Firefox, etc.)
2. Opens DevTools → Application tab → Cookies → `https://www.loopnet.com`
3. Copies the 3 expected cookies (or all 3+ if more present) as `name=value; name=value; ...`
4. Pastes into the LoopNet cookie bar in the REGOG UI
5. `saveLoopnetCookie()` (JS function) POSTs to `/api/loopnet/save-cookie`
6. The dot indicator refreshes via `refreshLoopnetSessionDot()` (also shows cookie count)

### Scraper use (`loopnet_auth.py`)

`_load_session(session_path) -> dict` reads `loopnet_session.json`. Returns `{}` on missing/invalid/empty.

`_session_to_cookies(session, domain=".loopnet.com") -> list[dict]` converts to Playwright's `add_cookies` format. 10-year `expires` timestamp.

In `phase_scrape(target_url)`:
```python
context = await browser.new_context(...)
context.set_extra_http_headers({"Cookie": cookie_string})  # for HTTP requests
context.add_cookies(_session_to_cookies(session))        # for document.cookie
```

### Storage file

`/workspaces/regogv8/loopnet_session.json` — **UNTRACKED in git** (in `.gitignore`). Contains real/test cookies. Never commit. Will be regenerated each time the user pastes a fresh bundle.

### Known problem: codespace IP is denylisted by Akamai

**The codespace's egress IP is on Akamai's denylist.** Every request to `www.loopnet.com` from this environment returns `HTTP 403 Access Denied`, regardless of cookies. Baseline request with no cookies is also blocked, so it's the source IP, not the session. This is an infra problem, not a code problem.

**Workarounds:**
1. Paste cookies from a browser on a residential connection
2. Use a residential proxy
3. Run REGOG from a small VM with a clean IP
4. Accept that LoopNet isn't reachable from this codespace and lean on Realtor/Zillow/Redfin (which the FLIP RADAR pipeline already falls back to)

---

## 16. FEMA Flood Zone Scraper

**File:** `regog/scrapers/fema_scraper.py`

Free, no API key required. Queries FEMA's National Flood Hazard Layer (NFHL) ArcGIS REST API.

### `get_flood_zone(lat, lon) -> str | None`

**Endpoint:**
```
https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query
```

**Query params:**
```python
params = {
    "geometry":      f"{lon},{lat}",
    "geometryType":  "esriGeometryPoint",
    "spatialRel":    "esriSpatialRelIntersects",
    "outFields":     "FLD_ZONE,ZONE_SUBTY,SFHA_TF",
    "returnGeometry": "false",
    "f":             "json",
}
```

**Features:**
- Cached in-memory by `(round(lat, 4), round(lon, 4))` — 4 decimal places ≈ 10m resolution
- 0.5s minimum delay between requests
- 2 retries with 1s backoff
- 10-second timeout per request
- Returns zone code: `X` (minimal risk), `AE`/`A` (high risk), `VE` (coastal extreme), `"UNKNOWN"` (no data)

**KNOWN PROBLEM (FIXED in §35 #4):** The original NFHL API used a different JSON geometry format that caused all queries to fail. Rewritten with the simpler `esriGeometryPoint` format. Also, `FLOOD_SCORES[None]` was changed from 8 to 0.

### `get_flood_zone_batch(coords) -> dict[tuple, str]`

Convenience wrapper for batch lookups.

### `clear_cache()`

Clears the in-memory flood zone cache.

---

## 17. Brain Classifier (keyword-based)

**File:** `regog/enrichment/brain.py`

No LLM. Scans `listing_description` (and address) for signal keywords.

### `classify_property(address, scan_type, list_price, sqft, year_built, days_on_market, description) -> dict`

**Returns:**
```python
{
    "classification":     str,    # one of: fire_damage | teardown | distressed | vacant | luxury | standard | land_only
    "confidence":         float,  # 0.0-1.0, increments by 0.2-0.3 per matched keyword
    "red_flags":          list[str],
    "green_flags":        list[str],
    "seller_motivation":  str,    # high | medium | low
    "motivation_signals": list[str],  # matched keyword phrases
    "estimated_condition":str,    # maps classification
    "is_luxury":          bool,
    "notes":              str,    # human-readable summary
}
```

### Classification priority order

```
fire_damage > teardown > distressed > vacant > luxury > standard > land_only
```

The first matched tier wins (multiple matches in lower tiers won't override higher-priority hits).

### Special case: Land override

If `scan_type == "land"`, classification is forced to `"land_only"` regardless of description.

### Confidence scoring

- Starts at 0.5
- +0.3 per fire_damage match
- +0.3 per teardown match
- +0.25 per distressed match
- +0.2 per vacant match
- +0.2 per luxury match
- Capped at 1.0

### Seller motivation

- `high` if any `SELLER_MOTIVATION_KEYWORDS["high"]` matches
- `medium` if any `SELLER_MOTIVATION_KEYWORDS["medium"]` matches
- `low` otherwise

### Red/Green flags

- `red_flags` = list of `RED_FLAG_KEYWORDS` present in description
- `green_flags` = list of `GREEN_FLAG_KEYWORDS` present in description

---

## 18. Listing Filter (junk-out detection)

**File:** `regog/enrichment/listing_filter.py`

Filters out junk listings BEFORE scoring. Runs AFTER brain classification. **Order matters — first match wins.**

### `filter_listing(description, list_price, sqft, style, brain_classification) -> dict | None`

**Returns:**
```python
None                          # listing is clean
{                             # listing is flagged
    "action":      "skip" | "flag",
    "reason":      str,       # human-readable
    "filter_type": "auction" | "bait" | "burned" | "demolition" | "land_masquerade"
}
```

### Filter chain

1. **`check_auction`** → `skip`
   - Keywords: "foreclosure auction", "opening bid", "online auction", "auction ends", "starting bid", "minimum bid", "bankruptcy sale", "trustee sale", "sheriff sale", "foreclosure sale", "public auction", "sells at auction", "sold at auction", "court ordered", "lender auction"
   - Also: price < $5K + "auction" in description
   - Always: "opening bid" alone is enough

2. **`check_bait_price`** → `skip`
   - Price < $1,000 → always bait
   - Price < $10,000 + residential style + no sqft → bait
   - Keywords: "for investment only", "call for price", "coming soon listing", "do not disturb", etc.

3. **`check_burned`** → `flag` (kept but marked)
   - Keywords: "burnt", "burned down", "fire damaged", "structure fire", "total fire loss", etc.
   - Also triggered by `brain_classification == "fire_damage"`

4. **`check_demolition`** → `flag`
   - Keywords: "must demolish", "condemned", "uninhabitable", "beyond repair", etc.
   - Also triggered by `brain_classification == "teardown"`

5. **`check_land_masquerade`** → `flag`
   - Catches SINGLE_FAMILY/CONDOS/TOWNHOMES listings that are actually lots/land
   - Keywords: "buildable lot", "land only", "vacant lot", "raw land", etc.
   - Also: no sqft + description mentions "lot"/"land"/"acre"/"building site"

**`skip` action** removes the listing from results entirely. **`flag` action** keeps the listing but adds `filter_reason` and `filter_type` columns.

---

## 19. Acreage Enricher

**File:** `regog/enrichment/acreage_enricher.py`

Fills missing acreage from 4 fallback sources (in order):

1. **Compute from `lot_sqft` / `lot_size_sqft`** (1 acre = 43,560 sqft)
2. **Parse from `listing_description`** via regex: `"1.5 acres"`, `"0.25 AC"`, `"±3.2 acres"`, `"approx 1.5 acres"`, `"43,560 sq ft"` (converted from sqft)
3. **Parse from title/address text** (same regex patterns)
4. **Estimate from price-based heuristic** (for land-only listings)
   - `price < $50K` → 0.15 acres
   - `price < $150K` → 0.25 acres
   - `price < $500K` → 1.0 acres
   - else → 5.0 acres

**When acreage is estimated (not measured), sets `acres_estimated = True`** and the land scoring applies a **30% penalty** to the price-per-acre deviation. The acreage source is also tracked in `acres_source` (e.g., `"lot_sqft"`, `"description_parse"`, `"title_parse"`, `"price_estimate"`).

---

## 20. Comp Engine (2D Expansion Search)

**File:** `regog/enrichment/comp_engine.py` — **THE CORE DEAL-FINDING LOGIC**

### `calculate_comps(property_dict, sold_properties, radius_miles=None, scan_type=None) -> dict`

For each active listing, finds comparable sold properties using a **two-dimensional expansion search**: tries the smallest radius first, expands outward, then expands the time window.

### Algorithm (in order)

#### Step 1: Style filter — apples-to-apples

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

#### Step 1b: Land acreage pre-filter

For land, filters by `±50% acres` BEFORE expansion. If the acreage-filtered pool has ≥ 5 comps, only searches within that pool. Otherwise falls back to all-acreage pool. (Sets `comp_acreage_matched = True` if pre-filter succeeded.)

#### Step 2: 2D expansion search

`find_comps_with_expansion(style_filtered, target_lat, target_lon, radii)`

Outer loop = time windows `[180, 270, 365, 540, 730]` days
Inner loop = radius tiers `[r1, r2, r3, r3×2, r3×4, ... up to 100mi]`

```
Example for suburban residential: r1=0.5, r2=1.0, r3=1.5
Search order:
  180d/0.5mi → 180d/1.0mi → 180d/1.5mi → 180d/3mi → 180d/4.5mi → ...
  270d/0.5mi → 270d/1.0mi → 270d/1.5mi → ...
  365d/0.5mi → ...
  540d/0.5mi → ...
  730d/0.5mi → 730d/1.0mi → 730d/1.5mi → ... (2 years max lookback)
```

Requires `MIN_COMPS_REQUIRED` (5) comps before accepting. If 5+ comps found at any combination, returns immediately. If all combinations exhausted, falls back to 730d / 100mi with `tier_used = 99` and `staleness = True`.

#### Step 3: Similarity filters (if 5+ comps remain)

- **Sqft**: ±30% for residential/commercial
- **Beds/baths**: ±1 for residential
- **Acres**: ±50% for land
- If filtering reduces comps below 5, uses unfiltered set

#### Step 4: Calculate medians

```python
comp_median_price = statistics.median(prices)
comp_ppsf_median = statistics.median(price_per_sqft_list)
comp_ppa_median = statistics.median(price_per_acre_list)
```

#### Step 5: Price deviation

```python
price_deviation_pct = ((target_price - comp_median) / comp_median) * 100
# NEGATIVE = below median = GOOD DEAL
```

#### Step 6: Variance metrics

```python
comp_price_range = max(prices) - min(prices)
comp_price_stddev = statistics.stdev(prices)
comp_variance_high = (comp_price_range / comp_median) > 0.50  # range > 50% of median
```

#### Step 7: Confidence calculation

`calculate_comp_confidence(comp_count, tier_used, lookback_used) -> (float, label)`

Starts at 1.0, subtracts for:
- 1 comp: -0.40, 2 comps: -0.35
- tier 2: -0.10, tier 3: -0.20, tier 4+: -0.25
- lookback > 365d: -0.15, > 180d: -0.05

Results: ≥ 0.80 → HIGH, ≥ 0.50 → MEDIUM, < 0.50 → LOW

#### Step 8: Top 10 comps

Sorted by price proximity to target. Each has full details: address, price, sqft, acres, beds, baths, style, days_on_market, property_url, primary_photo, distance, last_sold_date (formatted as "Mar 2024").

### Return dict fields

```python
{
    "comp_median_price": int,
    "comp_count": int,
    "comp_radius_miles": float,
    "comp_radius_used": float,
    "comp_tier_used": int,
    "comp_lookback_used": int,
    "comp_category": str,                # residential | land | commercial
    "comp_density": str,                 # urban | suburban | rural
    "comp_price_per_sqft_median": float,
    "comp_price_per_acre_median": float,
    "price_deviation_pct": float,        # negative = below median = good
    "comp_confidence": float,            # 0.0-1.0
    "comp_confidence_label": str,        # HIGH | MEDIUM | LOW
    "comp_staleness_penalty_applied": bool,
    "comp_price_range": float,
    "comp_price_stddev": float,
    "comp_variance_high": bool,
    "comp_acreage_matched": bool,
    "comp_listings": list[dict],         # top 10 comps
}
```

### Helper functions

- `haversine_miles(lat1, lon1, lat2, lon2) -> float` — great-circle distance
- `_parse_date(date_str)` — tries 5 date formats
- `_days_since_sold(comp)` — days since `last_sold_date`
- `_in_range(value, target, max_diff)` — handles None gracefully
- `_median(values)` — Python `statistics.median` wrapper
- `split_into_quadrants(properties)` — for large scans (>500 listings), split into NW/NE/SW/SE quadrants
- `get_quadrant_for_coords(lat, lon, all_listings)` — find which quadrant a property belongs to
- `get_comp_radii(prop)` — returns `[r1, r2, r3]` based on density + category
- `_filter_by_distance(properties, center_lat, center_lon, radius_miles)` — haversine filter
- `_filter_by_style(properties, target_style, scan_type)` — apples-to-apples
- `_filter_by_lookback(properties, max_days)` — time window

---

## 21. Scoring Modules

All three scoring modules follow the same pattern: compute component scores → apply post-processing utilities (`apply_comp_fallback`, `apply_confidence_cap`, `apply_variance_penalty`) → sum (filtering `_fb_` prefix) → assign tier.

### Residential Score (`scoring/residential_score.py`)

**6 components:**

1. **price_deviation** (40 pts max, -10 to 40 range): Percentile-band scoring
   - ≤ -60% → 40, ≤ -50% → 36, ≤ -40% → 32, ≤ -30% → 26, ≤ -20% → 20
   - ≤ -10% → 13, ≤ -5% → 7, ≤ 0% → 3, ≤ +10% → 0, > +10% → -5
   - LOW confidence → ×0.5, MEDIUM → ×0.75

2. **dom_signal** (15 pts max): `DOM_SCORE_BRACKETS`
   - 0-30d=15, 31-90d=10, 91-180d=5, 181-365d=2, 365+=0

3. **assessor_gap** (20 pts max): `max(0, min(20, (gap_pct/30)*20))`. Missing=5

4. **condition** (15 pts max): `CONDITION_SCORES[classification]`
   - standard=15, luxury=12, vacant=10, distressed=7, teardown=4, fire_damage=3

5. **flood_penalty** (0-10): `FLOOD_SCORES[flood_zone]`
   - X=10, AE=3, A=4, VE=0, UNKNOWN/None=0 (no penalty for missing)

6. **permit_risk** (-5 to +3): `PERMIT_SCORES[permit_risk]`
   - low=+3, unknown=0, medium=-2, high=-5

**Post-processing (from `scoring/utils.py`):**
- `apply_comp_fallback` (comp_count=0 → use `estimated_value` as proxy)
- `apply_confidence_cap` (LOW→cap 10, MEDIUM→cap 20)
- `apply_variance_penalty` (comps<5 + variance_high → 25% reduction)

**Tier:** ≥ 100 = HOT, ≥ 50 = MEDIUM, ≥ 0 = WARM, < 0 = SKIP (implicit).

NOTE: No `DISTRESSED_` prefix on tiers. Removed in §35 #6.

### Land Score (`scoring/land_score.py`)

**7 components:**

1. **price_per_acre_deviation** (40 pts max): Same percentile bands as residential, but against $/acre
   - If acres=NULL/0: returns 0 (DO NOT use total price as proxy — was a bug, now fixed)
   - If comps are significantly different size (< 50% or > 200% of target): 50% reduction
   - If `acres_estimated`: 30% penalty

2. **zoning_bonus** (20 pts max): Buildable (R1-R4, C, C1, C2, I, M1, M2, PUD) = 20, Non-buildable (AG, A, CONSERVED, FLOODWAY, OS) = 2, Unknown = 10

3. **road_access_bonus** (10 pts max): From `brain_green_flags` keywords ("road access", "frontage", "paved road", "county road"). No signal = 0.

4. **utilities_bonus** (10 pts max): From `brain_green_flags` keywords ("utilities", "power", "water", "sewer", "gas", "electric"). No signal = 0.

5. **acreage_premium** (10 pts max): Smaller parcels worth more per acre
   - ≤ 1ac = 10, ≤ 5ac = 8, ≤ 10ac = 6, ≤ 40ac = 4, > 40ac = 2
   - Only applies if acres data is actually present

6. **flood_penalty** (0-10): Same as residential. UNKNOWN/None = 0.

7. **(Plus redistributed signals when acres=NULL to keep total < 70)** — see `score_land()` for the redistribution logic.

**Fallback when acres=NULL:** Redistributes the 50% weight (price_per_acre 40% + acreage_premium 10%) across available signals (zoning 20→33, road 10→17, utilities 10→17, flood 10→17). This keeps total < 70 so no HOT leads without acreage data. Sets `data_confidence = "LOW"`.

**Fallback when acres exist but no comp_price_per_acre:** Uses `price_deviation_pct` (total price comparison) as fallback. Sets `data_confidence = "MEDIUM"`.

### Commercial Score (`scoring/commercial_score.py`)

**5 components:**

1. **price_deviation** (35 pts max): Scaled from 40→35 (uses `score_price_deviation` then ×35/40)
2. **assessor_gap** (25 pts max): For skyscrapers, `(gap/20) * 25` instead of `(gap/30) * 25`. Missing = 8.
3. **cap_rate_estimate** (20 pts max): GRM-based estimator (see below)
4. **condition** (10 pts max): Scaled from `CONDITION_SCORES` (×10/15)
5. **flood_penalty** (0-10): Same as residential

### Cap Rate Estimator (GRM method)

`estimate_cap_rate(property_dict) -> dict`:

1. Looks up market rent in `MARKET_RENTS_PSF` dict by `(state, style)`:
   ```python
   MARKET_RENTS_PSF = {
       ("CA", "MULTI_FAMILY"): 2.50,
       ("NY", "MULTI_FAMILY"): 3.00,
       ("IL", "MULTI_FAMILY"): 1.50,
       ("TX", "MULTI_FAMILY"): 1.20,
       ("FL", "MULTI_FAMILY"): 1.40,
       ("GA", "MULTI_FAMILY"): 1.10,
       ("DEFAULT", "MULTI_FAMILY"): 1.25,
       ("DEFAULT", "RETAIL"): 1.50,
       ("DEFAULT", "OFFICE"): 1.75,
       ("DEFAULT", "INDUSTRIAL"): 0.75,
       ("DEFAULT", "MIXED_USE"): 1.40,
       ("DEFAULT", "CONDOS"): 1.50,
       ("DEFAULT", "TOWNHOMES"): 1.30,
       ("DEFAULT", "MOBILE"): 0.60,
       ("DEFAULT", "APARTMENT"): 1.25,
   }
   ```
2. Estimates sqft from price if missing (rough: $200/sqft)
3. Calculates monthly_gross = sqft × rent_psf
4. annual_gross = monthly × 12
5. effective_gross = annual_gross × 0.90 (10% vacancy)
6. expense_ratio = 0.40
7. NOI = effective_gross × (1 - expense_ratio)
8. cap_rate = (NOI / price) × 100
9. GRM = price / annual_gross

**Returns:**
```python
{
    "estimated_noi": float,
    "estimated_annual_gross": float,
    "estimated_cap_rate": float,
    "estimated_grm": float,
    "rent_psf_used": float,
    "sqft_used": int,
    "is_estimated": True,
}
```

**Scoring cap rate → score** (`score_commercial_cap_rate`):
- ≥ 10% → 20, ≥ 8% → 16, ≥ 6% → 12, ≥ 4% → 7, ≥ 2% → 3, < 2% → 0

**Stored in `prop["cap_rate_data"]`** (popped before upsert, restored for SSE).

### Score-component → DB-column mapping for UI display

In `web/app.py`'s `_run_scan_background`, the score components are mapped to the universal `score_*` columns for display:

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

This way the UI's segmented score bar works for all 3 scan types using the same column names.

---

## 22. Scoring Utilities (`scoring/utils.py`)

### `assign_tier(score) -> str`

Looks up score in `TIER_THRESHOLDS` (sorted descending, first match wins). Returns `"SKIP"` if no threshold matches (score < 0).

### `parse_flags(flags_value) -> list`

Parses `brain_red_flags` or `brain_green_flags` from JSON string OR Python list. Handles DB (JSON string) and in-memory (Python list) formats uniformly.

### `score_price_deviation(list_price, comp_median, comp_confidence="HIGH") -> float`

Percentile-band scoring from -10 to 40. Applies confidence penalty (LOW → ×0.5, MEDIUM → ×0.75).

### `apply_comp_fallback(property_dict, scores) -> dict`

When `comp_count == 0`:
- If `estimated_value` exists: uses `((list_price - estimated) / estimated) * 100` as proxy deviation
- If no `estimated_value`: sets `_fb_cap_at_risky = True`
- **CRITICAL (Law #4):** Uses `_fb_` prefix for metadata keys. Filter: `sum(v for k, v in scores.items() if not k.startswith("_fb_"))`

### `apply_confidence_cap(property_dict, scores) -> dict`

- LOW confidence: caps `price_deviation` / `price_per_acre_deviation` at 10
- MEDIUM confidence: caps at 20

### `apply_variance_penalty(property_dict, scores) -> dict`

comps < 5 + `comp_variance_high` → 25% reduction on `price_deviation` and `price_per_acre_deviation`. Sets `_fb_variance_penalty = True`.

### `cap_score_if_no_comps(total, scores) -> (float, str | None)`

When `_fb_cap_at_risky` is set, max total = 30 (below MEDIUM threshold 50). Returns `(capped_total, "capped")` or `(total, None)`.

### `get_score_completeness(property_dict) -> dict`

Returns factors_with_data / total_factors for UI badge:
- `completeness_pct`: int (0-100)
- `missing_factors`: list[str]
- `factors_with_data`: int
- `total_factors`: int

The 5 factors checked: `price_deviation` (comp_median_price), `assessor_gap` (assessed_value), `days_on_market`, `condition` (year_built), `flood_zone` (not None/UNKNOWN).

---

## 23. Three Scan Modes — Overview & Comparison

| Mode | Default? | UI Element | Filter | Pipeline | Use Case |
|------|----------|------------|--------|----------|----------|
| **DEAL RADAR** 🎯 | ✅ Yes (boots pre-checked) | Top box with location + category + price | None — all properties emitted | `_run_scan_background` (single city, full pipeline) | Find underpriced properties in a single city |
| **LAVA SCAN** 🌋 | No | Middle box with state dropdown + min profit slider | `comp_median / list_price >= 2.0` (200%, slider-adjustable) | `_run_nationwide_lava_scan` (cycles TOP_20_METROS) OR `_run_scan_background` with `lava_mode=True` (single city) | Only extreme deals — "I want 100%+ profit" |
| **FLIP RADAR** 🔨 | No | Bottom box with property-type dropdown | `distress_score >= 2` | `_run_flip_scan` (separate scan type `"flip"`) | Distressed properties worth fixing & flipping |

### How the three differ at the code level

| Aspect | DEAL RADAR | LAVA SCAN | FLIP RADAR |
|--------|------------|-----------|------------|
| `scan_type` POST | `residential` \| `land` \| `commercial` | same | `"flip"` (new) |
| `lava_mode` POST | `false` | `true` | `false` |
| `flip_property_type` POST | unused | unused | one of 9 values |
| Function called | `_run_scan_background` | `_run_nationwide_lava_scan` (if `lava_scope=nationwide`) or `_run_scan_background` with lava filter | `_run_flip_scan` |
| Properties emitted | All (filtered by tier) | Only `profit_ratio >= min_ratio` | Only `distress_score >= 2` |
| Distress scoring | No | No | Yes (DISTRESS_HIGH/MEDIUM/LOW keywords, 3/2/1 pts) |
| ARV/rehab/profit/ROI/grade | No | No | Yes |
| Tier mapping | `assign_tier(score_total)` | Same | `_flip_tier()` → LAVA / HOT / WARM / NEUTRAL / SKIP |
| Property-type sources | Realtor only | Realtor only | Realtor + Zillow + LoopNet (per `_flip_property_types()`) |

### Mutual exclusion in UI

`toggleMode(this)` (JS, line 1519) enforces that only one of the three checkboxes can be checked at a time. If all three are unchecked, DEAL RADAR auto-defaults (line 1535).

```javascript
function toggleMode(checkbox) {
    const regular = document.getElementById('regular-mode');
    const lava    = document.getElementById('lava-mode');
    const flip    = document.getElementById('flip-mode');

    if (checkbox.checked) {
        // Uncheck the other two
        [regular, lava, flip].forEach(cb => {
            if (cb !== checkbox) cb.checked = false;
        });
    }

    // Auto-default to DEAL RADAR if all unchecked
    if (!regular.checked && !lava.checked && !flip.checked) {
        regular.checked = true;
    }

    updateModeBoxes();
}
```

---

## 24. DEAL RADAR Mode (default)

**Deal Radar** 🎯 (renamed from "Regular Scan" in V7) is the **default scan mode** — the web app boots with the DEAL RADAR box pre-checked (`regular-mode` checkbox, `checked` attribute in the HTML). It's the bread-and-butter underpriced-property finder: fetch listings → score against 6 signals → tier them HOT/MEDIUM/WARM/SKIP.

### When to use

- "Find underpriced homes in a specific city" (e.g., Dallas under $400K)
- "Show me all HOT leads in Chicago" — score_total >= 100
- Any case where you want the full 0-100+ scoring against the standard tier thresholds, with **all** properties emitted (no minimum profit filter, no distress filter)

### DEAL RADAR pipeline

Drives `_run_scan_background()` in `web/app.py` with `scan_type ∈ {"residential", "land", "commercial"}`, `lava_mode=False`, `flip_property_type` unused. Same pipeline as §11.

### Parameters (from the 🎯 DEAL RADAR box in the UI)

- **Location** (required) — "City, ST", ZIP, or colloquial term
- **Category dropdown** — `Single Family Homes` / `Land` / `Commercial` — sets `scan_type`
- **Min/Max price** — applied per-listing after `normalize_listing()`

### Tier thresholds (DEAL RADAR's output)

```python
TIER_THRESHOLDS = {"HOT": 100, "MEDIUM": 50, "WARM": 0}  # <0 implicit SKIP
```

A DEAL RADAR HOT lead needs a score ≥ 100 (uncapped percentile-band total). Most properties score 0-80, so HOTs are rare and precious. MEDIUM (50-99) and WARM (0-49) are the workhorses.

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

## 25. LAVA SEARCH Mode

**Lava Search** is a special scan mode that only surfaces extreme deals — properties where the comp median is at least 200% of list price (the **default** threshold; user-adjustable via the `lava_min_profit` slider in the web UI). The filter is `comp_median / list_price >= (lava_min_profit / 100.0)`.

### Two scope modes

1. **Single city** — `lava_scope="city"` (default) — runs `_run_scan_background` with `lava_mode=True`. LAVA filter applied per-property. Properties without comps are SKIPPED.
2. **Nationwide** — `lava_scope="nationwide"` — runs `_run_nationwide_lava_scan` which cycles through `TOP_20_METROS`. Each city runs the full pipeline. LAVA filter applied. Lava-quality properties stream to SSE.

### TOP_20_METROS

**Used by Lava Search's nationwide path only** (`_run_nationwide_lava_scan`). DEAL RADAR and FLIP RADAR do not iterate this list — they take a single user-provided location.

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

When `lava_state` is set, metros are filtered: `[c for c in TOP_20_METROS if c.endswith(f", {lava_state}")]`. If no metros match the state, falls back to all 20.

### Lava filter logic

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
            continue   # Skip — not lava quality
    else:
        continue       # No comp data — skip
```

### Lava columns (V7+)

Three columns added to `properties` table:
- `lava_profit_pct` (REAL) — profit percentage = `(profit_ratio - 1) * 100`
- `lava_profit_ratio` (REAL) — `comp_median / list_price`
- `lava_city` (TEXT) — which metro the property was found in (nationwide mode)

### Status events (nationwide mode)

```python
status = {
    "status": "scanning",
    "current_city": "New York, NY",
    "cities_completed": 5,
    "total_cities": 20,
    "properties_found": 23,
    "hot_leads": 4,
    "lava_scope": "nationwide",
    "lava_state": "TX" | "all",
    ...
}
```

### Code references

- **`web/app.py` `_run_nationwide_lava_scan()`** — function for nationwide lava cycling
- **`web/app.py` `_run_scan_background()`** — handles single-city lava via the `lava_mode` branch
- **`web/static/index.html`** lines ~1220-1260 — LAVA SCAN box with state dropdown and LAVA SCAN button

---

## 26. FLIP RADAR Mode

A separate scan pipeline (`_run_flip_scan` in `web/app.py`). Distress-scored properties with ARV/rehab/profit/ROI analysis.

### Distress scoring

```python
DISTRESS_HIGH = [
    "as-is", "as is", "needs work", "needs repair", "fixer", "fixer-upper",
    "investor special", "cash only", "handyman", "handyman special",
    "tear down", "teardown", "major repairs", "uninhabitable",
    "fire damage", "flood damage", "foundation",
]
DISTRESS_MEDIUM = [
    "estate sale", "motivated seller", "price reduced", "below market",
    "opportunity", "potential", "tlc", "updating needed", "cosmetic",
    "original condition", "original owner",
]
DISTRESS_LOW = [
    "sold as is", "older home", "bring offers", "priced to sell", "make offer",
]

def score_distress(text: str) -> tuple[int, list[str]]:
    """3 pts per HIGH match, 2 per MEDIUM, 1 per LOW."""
```

Properties with `distress_score < 2` are filtered out (the threshold of 2 was chosen so a single MEDIUM or two LOW matches pass, filtering out totally unflagged listings).

### Repair cost estimation

```python
def estimate_repair_cost(distress_score: int, sqft: int | None) -> tuple[int, str]:
    if distress_score >= 8: cost_per_sqft, tier, flat_fallback = 45, "heavy", 85000
    elif distress_score >= 5: cost_per_sqft, tier, flat_fallback = 28, "medium", 45000
    else: cost_per_sqft, tier, flat_fallback = 15, "light", 20000
    if sqft and sqft > 0:
        return int(cost_per_sqft * sqft), tier
    return flat_fallback, tier
```

### Flip metrics

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
    # ... assign to prop
```

### Flip tier mapping

```python
def _flip_tier(prop: dict) -> str:
    profit = prop.get("flip_projected_profit") or 0
    roi    = prop.get("flip_roi_pct") or 0
    grade  = prop.get("flip_deal_grade") or "D"
    if profit <= 0:  return "SKIP"
    if grade == "A" and roi >= 40: return "LAVA"
    if grade == "A" or (grade == "B" and roi >= 25): return "HOT"
    if grade in ("B", "C"): return "WARM"
    return "NEUTRAL"
```

### Property-type routing

`_flip_property_types(selection)` maps the FLIP RADAR dropdown to listing sources. **Each selection now maps to its OWN category** — no shared commercial-type fallback for hotel / rv_park / mixed_use.

| Selection | Source | Property types / category |
|-----------|--------|--------------------------|
| `single_family` | Realtor | `["single_family", "mobile"]` |
| `multi_family` | Realtor | `["multi_family", "duplex_triplex"]` (excludes condos) |
| `condos` | Realtor | `["condos", "apartment"]` (own category, doesn't leak) |
| `commercial` | Realtor | `["townhomes", "farm"]` (excludes multi-family/condos) |
| `townhomes` | Realtor | `["townhomes"]` |
| `hotel` | Zillow | category="hotel" (LoopNet is Cloudflare-blocked) |
| `rv_park` | Zillow | category="rv_park" (Zillow carries RV/mobile/manufactured) |
| `mixed_use` | LoopNet | category="mixed-use-properties" |
| `all` | All three | merge |

### FLIP RADAR pipeline

1. Fetch listings from all mapped sources (parallel-ish — sequential in current code)
2. For each listing:
   - Normalize
   - Price filter
   - `score_distress(description + remarks + status)` → skip if < 2
   - Brain classify (residential-only for FLIP)
   - Listing filter (skip auctions, etc.)
   - Enrich
   - Calculate comps
   - `compute_flip_metrics(prop)` → ARV, repair, max offer, profit, ROI, grade
   - `_flip_tier(prop)` → LAVA / HOT / WARM / NEUTRAL / SKIP
   - Upsert
   - Push to SSE

### FLIP status events

```python
status = {
    "status": "scanning",
    "flip_property_type": "single_family",
    "flip_sources": ["realtor"],
    "listings_found": 234,
    "comp_limit": 300,
    "comps_found": 287,
    "hot_count": 4,
    "lava_count": 1,
    "a_deals": 3,
    "b_deals": 8,
    "avg_roi": 28.5,
    "filtered_out": 47,
    ...
}
```

### Code references

- **`web/app.py` `_run_flip_scan()`** — main flip pipeline
- **`web/app.py` `score_distress()`** — keyword scoring
- **`web/app.py` `estimate_repair_cost()`** — rehab cost estimator
- **`web/app.py` `compute_flip_metrics()`** — ARV/profit/ROI/grade
- **`web/app.py` `_flip_tier()`** — REGOG lead_tier mapping
- **`web/app.py` `_flip_property_types()`** — dropdown → sources mapping
- **`web/static/index.html`** lines ~1260-1290 — FLIP RADAR box with property-type dropdown and FLIP SCAN button

---

## 27. Web App Backend (`web/app.py`)

Flask app with REST API + SSE streaming + background scan threads + LoopNet cookie endpoints.

### Endpoints

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Serves `index.html` |
| `/api/config` | GET | Weights, thresholds, comp defaults (from `config.py`) |
| `/api/stats` | GET | DB aggregate stats (`{total_properties, hot_leads, warm_leads, scan_sessions, avg_score}`) |
| `/api/scans` | GET | Recent 20 scan sessions (with parsed `search_params`) |
| `/api/scan` | POST | Start a new scan → `{session_id, stream_url}` |
| `/api/scan/<id>/results` | GET | Paginated results (params: `page`, `per_page`, `tier`) |
| `/api/scan/<id>/status` | GET | Current scan status (for polling after SSE closes) |
| `/api/scan/<id>/cancel` | POST | Set cancel event for running scan |
| `/api/scan/<id>/stream` | GET | **SSE endpoint** streaming properties |
| `/api/saved` | GET | List saved properties |
| `/api/saved/<listing_id>` | POST | Toggle save/unsave |
| `/api/saved/<listing_id>/status` | GET | Check if saved |
| `/api/property/<listing_id>` | GET | Single property detail |
| `/api/loopnet/save-cookie` | POST | Save LoopNet cookie bundle (see §15) |
| `/api/loopnet/session/status` | GET | LoopNet session status |

### SSE events (in order)

```
1. event: connected\ndata: {session_id}\n\n
2. event: property\ndata: {json serialized property}\n\n   (one per scored property)
3. event: complete\ndata: {status json}\n\n
4. event: keepalive\ndata: {}\n\n                          (every 30s if no data)
```

### In-memory state (lost on restart)

```python
_scan_progress: dict[str, queue.Queue] = {}    # session_id -> Queue of property dicts
_scan_status:   dict[str, dict] = {}           # session_id -> status metadata
_scan_status_lock: threading.Lock              # protects _scan_status
_cancel_events: dict[str, threading.Event] = {} # session_id -> Event, set when cancel requested
_saved_properties: set[str] = set()            # in-memory set of saved listing_ids
```

**Note:** `_saved_properties` is NOT persisted to the database. It resets on app restart. (Future: persist to a `saved_properties` table.)

### Logging

```python
logging.basicConfig(level=logging.DEBUG, force=True,
                    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
```

`force=True` was added so the web app's logging isn't swallowed by Flask's defaults. All errors include full tracebacks via `import traceback; logger.error(traceback.format_exc())`.

### Threading model

- **Main thread:** Flask request handling
- **Background threads:** One per running scan (`_run_scan_background`, `_run_flip_scan`, `_run_nationwide_lava_scan`)
- **SSE consumers:** One per client connected to `/api/scan/<id>/stream`. Reads from `_scan_progress[session_id]`.
- **Thread-safe status updates:** All writes to `_scan_status` go through `_scan_status_lock`
- **Cancel via `threading.Event`:** Polled at every iteration in scan loops

### Flask debug mode

`web/app.py`'s `__main__` block runs Flask on port 5000 in debug mode. `serve_report.py` runs on port 8080 in non-debug mode with threading.

**Always use `serve_report.py` in production** — debug=True spawns a reloader child that `pkill -f` will leave orphaned.

### `_run_scan_background` arguments

```python
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
    lava_min_profit: int = 300,    # NOTE: 300 default (300% = 3x), but UI uses 200 (2x)
    lava_scope: str = "city",
    lava_state: str = "",
    flip_property_type: str = "all",
):
```

### Top 20 US Metros (`TOP_20_METROS`)

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

### Serialization helpers

```python
def _serialize_prop(prop: dict) -> dict:
    """Serialize a property dict for JSON response."""
    serialized = {}
    for k, v in prop.items():
        if isinstance(v, (int, float, str, bool)) or v is None:
            serialized[k] = v
        elif isinstance(v, (list, dict)):
            serialized[k] = v
        else:
            serialized[k] = str(v)
    return serialized
```

---

## 28. Web Frontend (`web/static/index.html`)

Single HTML file with ALL CSS + JS inline. **No build step, no framework, no external dependencies.** Dark theme by default. ~2400 lines.

### CSS Design System

```css
--bg:           #0a0a0a;
--bg-surface:   #111111;
--bg-card:      #111118;
--accent:       #ff2233;
--lava:         #ff8800;
--lava-glow:    rgba(255, 136, 0, 0.5);
--text:         #ffffff;
--text-muted:   #ddddee;
--text-dim:     rgba(255,255,255,0.7);
--green:        #44ff66;
--amber:        #ffaa00;
--magenta:      #ff44aa;
--border:       rgba(255,255,255,0.1);
--radius:       12px;
--radius-sm:    8px;
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
├────────────────────────────────────────────────────┤
│ LoopNet Session: ● (cookie count)                  │
│ [paste cookies here...] [💾 Save]                  │
├────────────────────────────────────────────────────┤
│ Stats: [Total] [HOT] [MEDIUM] [WARM] [Avg] [Live]  │
├────────────────────────────────────────────────────┤
│ [Property card]  [Property card]  [Property card]  │
│ [Property card]  [Property card]  [Property card]  │
│ ... (infinite scroll, sort by price/profit/score)  │
└────────────────────────────────────────────────────┘
```

### Key CSS Classes

- `.mode-box` — Each scan mode section (border, padding, background)
- `.mode-box.mode-disabled` — Dimmed state (opacity 0.25, grayscale 0.8, pointer-events: none)
- `.mode-box-header` — Checkbox + label row (has `pointer-events: auto !important` to override)
- `.mode-box-body` — Contains fields + scan button
- `.property-card` — Individual property result (clickable, expandable)
- `.property-card.expanded` — Detail grid visible
- `.score-bar`, `.score-bar-segment` — Segmented score visualization
- `.lava-banner` — Orange gradient banner for LAVA-mode properties
- `.hot-badge` — Red glow badge for HOT tier
- `.filter-pill` — Colored pill for filter flags (red/green)

### Key JS Functions

| Function | Purpose |
|----------|---------|
| `toggleMode(checkbox)` | Mutual exclusion between the THREE mode checkboxes. Auto-defaults to DEAL RADAR if all unchecked. |
| `startScan(mode)` | Takes `'regular'`, `'lava'`, or `'flip'`, POSTs to `/api/scan`, opens SSE stream |
| `stopScan()` | Cancels current session, resets buttons |
| `addProperty(prop)` | Creates card DOM element, inserts in sort order |
| `toggleExpand(listingId)` | Toggles detail view |
| `toggleSave(listingId, btn)` | Save/unsave via API |
| `filterTier(tier)` | Filter by HOT/MEDIUM/WARM/ALL |
| `setSort(mode)` | Re-sort by price/profit/score |
| `getListingUrl(prop)` | Build URL: Realtor.com > Zillow > Google Maps |
| `getListingLabel(prop)` | Label for the view button |
| `renderCompListings(prop)` | Builds clickable comp cards |
| `getCompUrl(comp, parentProp)` | Builds Zillow address URL |
| `buildCompWarning(prop)` | Shows warning for low comps / high variance |
| `pollStatus()` | Polls `/api/scan/<id>/status` every 2s as SSE fallback |
| `saveLoopnetCookie()` | POSTs cookie bundle to `/api/loopnet/save-cookie` |
| `refreshLoopnetSessionDot()` | Refreshes LoopNet session indicator + cookie count |

### Property Card

- Clickable → expands detail grid
- **Badges:** HOT (red glow), LAVA (orange gradient)
- **Score:** Color-coded (green ≥ 100, amber ≥ 50, red < 50)
- **Card row:** Price, Lava Profit%, vs Median%, DOM, Beds/Baths, Stories, Sqft, Comps
- **Flags:** Brain classification, filter flags, red/green flag pills
- **Expanded detail:** Full grid, lava banner, segmented score bar, brain output, comp listings
- **Score completeness badge:** COMPLETE / PARTIAL / LIMITED DATA (from `get_score_completeness`)

### Segmented Score Bar (5 segments)

```html
<div class="score-bar">
  <div class="segment" style="width:${(price_deviation)/100*100}%;background:var(--green);"    title="Price Deviation"></div>
  <div class="segment" style="width:${(assessor_gap)/100*100}%;background:#44aaff;"            title="Assessor Gap"></div>
  <div class="segment" style="width:${(dom_signal)/100*100}%;background:var(--amber);"         title="DOM Signal"></div>
  <div class="segment" style="width:${(condition)/100*100}%;background:#aa44ff;"               title="Condition"></div>
  <div class="segment" style="width:${(flood_penalty)/100*100}%;background:#ff4466;"           title="Flood"></div>
</div>
```

### Comp Cards (horizontal scroll)

Each comp card shows: thumbnail, address (35 char max), price (green), beds/baths/sqft/acres/distance, sold/active label with date. Clickable → opens Realtor.com or Zillow.

---

## 29. CLI (`regog/main.py`)

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

### Scan arguments (CLI)

`--location` (required), `--price-min/--price-max`, `--radius`, `--beds-min`, `--sqft-min`, `--acres-min/--acres-max`, `--type` (commercial subtype), `--dom-max`, `--skip-flood`, `--use-zillow` (with `--zillow-pages`), `--past-days` (default 180), `--limit` (default 50), `--use-redfin`, `--use-craigslist`, `--fresh`

### Pipeline (same as DEAL RADAR web-app path, see §24)

1. Resolve location (`utils.location_resolver.resolve_with_details`)
2. Fetch sold comps (dynamic pool size)
3. Fetch active listings
4. Optionally fetch secondary sources
5. For each property: normalize → brain → filter → enrich → comps → score → upsert
6. Show results in Rich terminal table

**Note:** The CLI exposes only the **DEAL RADAR** standard pipeline (`residential` / `land` / `commercial`). Lava Search and Flip Radar are **web-app only** — there is no `regog scan lava` or `regog scan flip` subcommand. (The `scan` subcommand's `scan_type` choices are `["residential", "land", "commercial"]` only — see `regog/main.py` line 61.)

### Detailed output

`_print_property_details(properties)` shows top 10 HOT/WARM:
- Cap rate (commercial, from in-memory `cap_rate_data`)
- Score completeness (badge + missing factors)
- Acreage warning for land (estimated vs measured)

### Schedule subcommand

```bash
regog schedule --location "Los Angeles, CA" --interval 24
```

Uses APScheduler (optional dependency). Runs the same pipeline with `skip_flood=True` for speed. Blocks the terminal (Ctrl+C to stop). All work happens in the scheduler's background thread.

---

## 30. Utility Modules (`regog/utils/`)

### `property_type.py` — Style → category mapping

```python
_RESIDENTIAL_STYLES = {"SINGLE_FAMILY", "MANUFACTURED", "MOBILE"}
_LAND_STYLES        = {"LAND", "LOT", "LOTS_LAND", "FARM", "RANCH", "ACREAGE", "VACANT"}
_COMMERCIAL_STYLES  = {"CONDOS", "CONDO", "TOWNHOMES", "TOWNHOUSE",
                       "MULTI_FAMILY", "APARTMENT", "DUPLEX", "TRIPLEX", "QUADPLEX",
                       "COMMERCIAL", "OFFICE", "RETAIL", "INDUSTRIAL", "WAREHOUSE",
                       "MIXED_USE", "SPECIAL_PURPOSE", "HOTEL", "MOTEL"}
```

`get_property_category(style, property_type=None, stories=None)` returns one of `residential | land | commercial`. **High-rise detection:** CONDO with `stories >= HIGH_RISE_MIN_STORIES` (5) → reclassified as commercial.

### `density.py` — ZIP → urban/suburban/rural

Static lookup based on ZIP prefix (first 3 digits). 150+ urban prefixes (NYC, LA, Chicago, SF, Miami, Boston, Seattle, Houston, Atlanta, Phoenix, Philly, Portland, Vegas, Austin, Dallas, Cleveland, Detroit, Minneapolis, Oakland, Brooklyn, Queens, Bronx, Staten Island, Nassau, etc.) and 200+ rural prefixes (MT, WY, ID, SD, ND, NV, WV, MS delta, NM, IA, AR, KY, AK, HI, NE panhandle). Default = `suburban`.

### `rate_limiter.py` — Per-source throttling

```python
rate_limit(source)            # enforces min delay + random jitter + hourly cap
report_success(source)        # resets error counter
report_error(source)          # increments error counter for exponential backoff
```

Exponential backoff: `base * 2^(errors-1)` capped at 60s.

### `config_store.py` — JSON config overrides

Persistent JSON config (`regog_config.json` next to DB). Functions: `set_config(key, value)`, `get_config(key, default)`, `list_config()`, `load_config()`, `delete_config(key)`.

### `dedup.py` — Address-normalized dedup

`merge_and_deduplicate(primary_listings, secondary_listings)` — when multiple sources are used, normalizes addresses and removes duplicates. Primary source (HomeHarvest) wins on conflicts.

### `location_resolver.py` — Colloquial → "City, ST"

**CRITICAL utility.** Converts loose terms to HomeHarvest-compatible search strings. HomeHarvest TIMES OUT on bare state queries like "Georgia".

**Resolution order:**
1. Already valid format ("City, ST", "ZIP", or single city) → pass through
2. Exact match in `COLLOQUIAL_REGIONS` (e.g., "North GA" → "Atlanta, GA")
3. State abbreviation → state name → anchor city (`STATE_TO_ANCHOR`)
4. "City, ST" with full state name → normalize state code
5. Full string is a state name → anchor city
6. Directional prefix + name → strip prefix, then resolve
7. Strip fuzzy words ("area", "region", "county")
8. Nothing worked → return original
9. Bare state name → anchor city (HomeHarvest timeout prevention)

`resolve_with_details(raw_location) -> dict` returns `{original, resolved, method, changed}`.

**Public API:**
```python
from utils.location_resolver import resolve_with_details
loc_info = resolve_with_details("South GA")
# → {"original": "South GA", "resolved": "Valdosta, GA",
#    "method": "colloquial_match", "changed": True}
```

If the resolved location differs, the new location is persisted into the scan session's `search_params` JSON for traceability.

---

## 31. Scheduler (`regog/scheduler/`)

**File:** `regog/scheduler/scan_scheduler.py`

Wraps APScheduler for recurring scans. Optional — requires `apscheduler` package.

```python
from scheduler.scan_scheduler import create_scheduler, schedule_scan
scheduler = create_scheduler()
schedule_scan(scheduler, scan_func, location="Dallas, TX", scan_type="residential", interval_hours=24)
scheduler.start()
```

Runs in background thread. Configurable interval (default 24h). Same pipeline as CLI/web scans with `skip_flood=True` (FEMA skipped for speed).

If APScheduler not installed, `create_scheduler()` returns `None` and the CLI prints a helpful error.

---

## 32. Terminal UI (`regog/ui/`)

**File:** `regog/ui/terminal.py`

Rich console output for the CLI. Functions:

| Function | Purpose |
|----------|---------|
| `print_banner()` | Prints the REGOG ASCII art banner |
| `render_leads_table(properties, title)` | Renders a Rich Table of properties |
| `render_stats_panel(stats)` | Stats panel (total, hot, warm, avg) |
| `render_session_summary(session_id, scan_type, location, processed, hot_count)` | Session summary |
| `render_error(message)` | Red error message |
| `render_info(message)` | Blue info message |
| `render_success(message)` | Green success message |
| `confirm_action(message)` | Yes/no prompt |

**File:** `regog/ui/report_generator.py` + `regog/ui/templates/report.html.j2`

Jinja2 HTML report generator. CLI command: `regog report --session-id <id> --output report.html`. Outputs a self-contained HTML report with all properties, scores, comps, brain flags.

---

## 33. Tests (`tests/`)

**98 tests total.** Run with:
```bash
cd /workspaces/regogv8
pytest -q
```

### Test files

- **`test_residential_score.py`** — 50+ tests: 6 signals, tiers, edge cases, boundary conditions, data types
- **`test_land_score.py`** — Land scoring tests (zoning, acreage premium, empty dict, estimated acreage penalty)
- **`test_scoring_fallback.py`** — `_fb_` metadata filter fix (comp_count=0 + estimated_value paths)
- **`test_utils.py`** — Tier thresholds, boundary tests, parse_flags (list/JSON/None/invalid), get_score_completeness
- **`test_permit_scraper.py`** — Permit inference (unpermitted, code violations, mixed signals)

### Fixtures (`conftest.py`)

- `standard_residential`: Baseline with all fields
- `hot_deal_residential`: Deep discount (-60%), large assessor gap, low permit risk. Must score >= 100 for HOT tier.
- `skip_residential`: Overpriced (+15%), high flood risk, high permit risk
- `missing_data_residential`: All None values
- `distressed_residential`: Fire damage classification

### Known test gaps

- No test coverage for Lava Search mode
- No test coverage for Flip Radar mode
- No test for `comp_count=0` + `estimated_value` path that triggered the original `_fb_` filter crash (now fixed but no regression test)
- No test for LoopNet cookie parser

---

## 34. Codespace Keepalive (`scripts/regog_keepalive.sh`)

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
# Wrapping in `while true` makes the app self-healing regardless of cause.

cd /workspaces/regogv8 || { echo "fatal: project dir not found" >&2; exit 1; }
echo $$ > /tmp/regog-keepalive.pid
# Track the child PID so pkill -f regog_keepalive.sh doesn't orphan serve_report.py.
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

### Known bug in the keepalive

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
curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://localhost:8080/   # expect: 200
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

## 35. ALL KNOWN PROBLEMS & FIXES (chronological)

This section catalogs every significant bug or issue encountered during development, with the root cause and the fix applied.

### 🔴 CRITICAL BUGS (Fixed)

| # | Problem | Root Cause | Fix Applied |
|---|---------|-----------|-------------|
| 1 | **Dual database files** | Relative `DB_PATH = "regog.db"` resolved differently for CLI vs web app | Absolute path: `str(Path(__file__).parent.parent / "regog.db")` (Law #1) |
| 2 | **Zero results in web app** | Web app's DB missing schema columns (`style`, `property_url`) — all `upsert_property()` calls silently failed | Added `init_db()` to `serve_report.py` startup so migrations run before Flask |
| 3 | **`sum(scores.values())` TypeError** | `apply_comp_fallback()` added string `_fb_source` key to scores dict, then residential/commercial scorers crashed on `sum()` | Filter `_fb_` prefix: `sum(v for k, v in scores.items() if not k.startswith("_fb_"))` (Law #4) |
| 4 | **FEMA flood zone always returning UNKNOWN** | Used wrong geometry format in ArcGIS query (JSON geometry instead of `esriGeometryPoint`) | Rewrote with simple `geometry={lon},{lat}` + `geometryType=esriGeometryPoint` |
| 5 | **FEMA penalty unfairly tanking all scores** | `FLOOD_SCORES[None] = 8` penalized every property 8 points when flood data was missing | Changed to `FLOOD_SCORES[None] = 0` — never penalize for missing data (Law #2) |
| 6 | **DISTRESSED_ tier prefix corruption** | Tier labels concatenated brain classification with tier name: `"DISTRESSED_" + tier` → corrupted 102 records | Removed concatenation. Added DB migration `_fix_corrupted_tiers()` (Law #3) |
| 7 | **Residential price deviation ceiling** | Binary scoring (below/above median) gave max 40 pts to every Manhattan listing | Percentile-band scoring: -60%→40, -50%→36, ..., >10%→-5 |
| 8 | **Land scoring flatlining at 76.0** | No per-acre deviation scoring, automatic bonuses creating artificial floor | Added `score_price_per_acre_deviation()`, `score_land_assessor_gap()` with PPA heuristic |
| 9 | **Commercial cap rate was dead code** | `_estimate_cap_rate()` returned 0 for all properties | GRM-based estimator with market rent estimates per state/style |
| 10 | **Land acreage NULL for most parcels** | HomeHarvest's acres column is inconsistent for land | Created `acreage_enricher.py` with 4 fallback sources (lot_sqft, description parsing, title parsing, price heuristic) |
| 11 | **Mode checkboxes trapped in disabled boxes** | `.mode-box.mode-disabled` set `pointer-events: none` on entire box, including its own checkbox | Added `pointer-events: auto !important` override on `.mode-box-header` |
| 12 | **LoopNet Playwright login flow broken** | Cloudflare/Akami-protected auth popup wouldn't capture storage_state reliably | Replaced with cookie bundle import (semicolon-separated HTTP cookies) — see §15 |
| 13 | **Codespace idle-kill** | ~20 min of inactivity reaps the process with no log/error | `scripts/regog_keepalive.sh` while-true restart loop (see §34) |
| 14 | **LoopNet scrape from codespace** | Akamai denylists the codespace's egress IP — every request returns 403 | **NOT FIXABLE in code.** Requires residential IP or different infrastructure. Cookie flow works once that path is unblocked. |

### 🟡 MINOR FIXES (Applied)

| # | Problem | Fix |
|---|---------|-----|
| 15 | **Comp scrollbar snapping to edges** | Removed `scroll-snap-type: x mandatory` from comp scroll CSS |
| 16 | **Error logging invisible in Flask** | Added `force=True` to `logging.basicConfig`, `import traceback`, `logger.error(traceback.format_exc())` |
| 17 | **Score key name mismatch for land** | `web/app.py` maps land's `price_per_acre_deviation` → `score_price_deviation` for UI display |
| 18 | **Lava checkbox unclickable when another mode active** | Same as #11 — checkbox pointer-events override |
| 19 | **lava_profit_pct column missing from schema** | Added `lava_profit_pct`, `lava_profit_ratio`, `lava_city` columns + migration |
| 20 | **Saved properties not persisting** | (Known issue — in-memory set only, not yet DB-backed) |
| 21 | **Top-20 metros cycling slow on first call** | Skips cities with zero listings or zero comps |

### 🟠 ATTEMPTED SOLUTIONS THAT DIDN'T WORK

These were tried and rolled back. Documenting so a future agent doesn't retry them.

1. **Starting the keepalive from inside an AI agent's basher subshell.** Tried `setsid`, `nohup`, `disown`, Python `os.fork()`. All detached processes are reaped when the basher subshell exits. The keepalive MUST be started by the user directly in their terminal.

2. **Connecting to LoopNet from the codespace.** Tried with cookies, without cookies, with full browser fingerprint, with `playwright-stealth`. All return HTTP 403 from Akamai. The codespace's egress IP is on a denylist. There is no in-code fix.

3. **Fetching sold comps by coordinates.** HomeHarvest does not support coordinate-based queries. The `fetch_sold_comps_near_coords()` function is defined twice in `redfin_scraper.py`, both returning `[]`. Cleanup: delete both definitions.

4. **Using `geocoder.py` for any purpose.** The file exists but is never imported. Dead code. Cleanup: delete it.

---

## 36. Outstanding Issues / TODOs

### 🟠 DATA QUALITY ISSUES

| # | Problem | Impact | Workaround |
|---|---------|--------|------------|
| 1 | **Sold comps fetched city-wide, not by radius** | HomeHarvest doesn't support coordinate-based queries | Comps fetched for entire city → filtered by distance in comp engine. Sparse areas get fewer comps. |
| 2 | **`assessed_value` rarely available from HomeHarvest** | `estimated_value` (AVM) used as proxy. Land AVM values are notoriously unreliable. | Assessor gap falls back to PPA heuristic for land. |
| 3 | **FEMA API is intermittently unreliable** | Government ArcGIS endpoint frequently returns errors under load | Retry logic (2 attempts) and caching. `--skip-flood` recommended for fast scans. |
| 4 | **Realtor.com hides sold prices** | Comp card links use Zillow address URLs instead of Realtor.com | `getCompUrl()` builds Zillow address search URL. |
| 5 | **County portal scraping limited** | Most Accela portals require interactive JS sessions | Falls back to keyword-based permit inference. |
| 6 | **HomeHarvest column names change** | Libraries change column names between versions | `g(*keys)` pattern handles this with multiple fallback names. |
| 7 | **LoopNet unreachable from codespace** | Akamai denylist | See §15 — must use residential IP or alternative source |

### 🟡 SCORING / UI ISSUES

| # | Problem | Impact |
|---|---------|--------|
| 8 | **Score distribution skews low for land** | Zero HOT/WARM leads in rural land scans — may be accurate or thresholds too aggressive |
| 9 | **Land score breakdown shows wrong component names in UI** | `score_price_deviation` maps to price per acre, `score_assessor_gap` maps to zoning |
| 10 | **No test coverage for `comp_count=0` + `estimated_value` path** | Critical edge case only caught in production |
| 11 | **No test coverage for Lava Search or Flip Radar modes** | |
| 12 | **Keepalive script missing signal trap** | `pkill -f regog_keepalive.sh` leaves `serve_report.py` orphaned |
| 13 | **LoopNet auth requires manual cookie paste** | User must log in to LoopNet, copy cookies, paste back — every time cookies expire |

### 🔵 ARCHITECTURE GAPS

| # | Problem | Priority |
|---|---------|----------|
| 14 | **Single point of failure on HomeHarvest** | If Realtor.com blocks HomeHarvest, the entire app stops working |
| 15 | **No sold comps for rural areas** | For loose geography scans, sold comp pool is too small (e.g., 24 comps for North Georgia) |
| 16 | **`fetch_sold_comps_near_coords()` defined twice in `redfin_scraper.py`** | Both return `[]` — dead code. **Cleanup:** delete both definitions. |
| 17 | **Stale `fetch_sold_comps()` in `homeharvest_scraper.py`** | Returns `[]` — the real one is in `redfin_scraper.py`. **Cleanup:** delete the stale function. |
| 18 | **`geocoder.py` is dead code** | Never called by any pipeline module |
| 19 | **`requirements.txt` does not exist** | Dependencies listed in this doc only (see §7) |
| 20 | **No `saved_properties` DB table** | Saves are in-memory only, lost on restart |

---

## 37. Secrets, Keys, Cookies, Storage Files

### Storage files (all in project root, all gitignored)

| File | Path | Contents | Gitignored? | Never commit? |
|------|------|----------|-------------|---------------|
| `regog.db` | `/workspaces/regogv8/regog.db` | SQLite database | ✅ Yes | **No — but it contains personal data** |
| `regog_config.json` | `/workspaces/regogv8/regog_config.json` | Persistent config overrides | ✅ Yes | No |
| `regog_report.html` | `/workspaces/regogv8/regog_report.html` | Generated HTML report | ✅ Yes | No |
| `loopnet_session.json` | `/workspaces/regogv8/loopnet_session.json` | LoopNet auth cookies | ✅ Yes | **YES — contains real/test cookies** |
| `TEMP_HANDOFF.md` | `/workspaces/regogv8/TEMP_HANDOFF.md` | Short handoff for previous agent | ✅ Yes | No |
| `/tmp/regog-app.log` | `/tmp/regog-app.log` | Flask app + keepalive log | n/a (in /tmp) | No |
| `/tmp/regog-keepalive.pid` | `/tmp/regog-keepalive.pid` | Keepalive PID | n/a (in /tmp) | No |

### API keys / credentials

**The app uses ZERO API keys.** All data sources are public and free.

| Source | Auth | Quota |
|--------|------|-------|
| HomeHarvest (Realtor.com) | None | Limited by Realtor.com rate limits |
| FEMA NFHL ArcGIS | None | Public ArcGIS |
| Redfin (via HomeHarvest) | None | Same as HomeHarvest |
| Zillow (stealth) | None (but Akamai-defended) | Frequent blocks |
| Craigslist | None | Limited by city map (~20 cities) |
| LoopNet | **User-pasted cookies** | None once cookies are valid |

### Cookies

**LoopNet only.** Three expected cookies:
- `SessionFarm_GUID` — required
- `UserPreferences` — required
- `UserInfo_AssociateID` — required

Excluded by design: `TDID`, `TDCPM` (The Trade Desk / ad-tracking — phasing out, not needed for auth).

Cookies are pasted by the user into the REGOG UI's LoopNet cookie bar, POSTed to `/api/loopnet/save-cookie`, parsed by `_parse_cookie_bundle()`, and saved to `loopnet_session.json`. The scraper reads this file and uses the cookies on every request.

**Codespace caveat:** even with valid cookies, the codespace's egress IP is on Akamai's denylist, so LoopNet is unreachable from this environment.

### .gitignore (canonical content)

```gitignore
# Python
__pycache__/
*.pyc
*.pyo
*.pyd

# Database and config
regog.db
regog.db-journal
regog.db-shm
regog.db-wal
regog_config.json

# Reports
regog_report.html

# Secrets
loopnet_session.json

# Temp handoff
TEMP_HANDOFF.md

# OS
.DS_Store
.vscode/

# Build artifacts
.venv/
venv/
build/
dist/
*.egg-info/
```

---

## 38. Build Doc References (sibling files)

The repo root contains a number of historical build / debug / analysis docs. **DO NOT USE these for a new build — this V8 doc is the single source of truth.** They are preserved for historical reference only.

1. **`REGOG_REBUILD_V8.md`** — this file (current handoff)
2. `REGOG_REBUILD_V6.md` — predecessor, now SUPERSEDED (see §39)
3. `REGOG_V5_REBUILD.md` — earlier V5 doc, now SUPERSEDED (see §39)
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
18. `REGOG_Deal_Audit.md` — referenced in old docs, does not exist

---

## 39. DEPRECATION NOTICE — V5 & V6 are now SUPERSEDED

**This REGOG REBUILD V8 doc supersedes all previous REGOG build docs.** Specifically:

- **`REGOG_REBUILD_V6.md`** — was the previous "single source of truth" but is now incomplete (V8 contains more files, more modes, more fixes, full file walkthroughs, deprecation of dead code)
- **`REGOG_V5_REBUILD.md`** — was the build guide used through the V5 scoring-fix series, now thoroughly obsolete

**Banner added to those docs at the same time as this V8 doc was published.** The banner reads:

> # ⚠️ SUPERSEDED — DO NOT USE FOR NEW WORK ⚠️
>
> **Superseded as of `5f2ca9d` (June 2026).** Use **[`REGOG_REBUILD_V8.md`](REGOG_REBUILD_V8.md)** as the single source of truth for rebuilding REGOG. This older doc is missing:
>
> - Frontend file walkthrough (only V8 has line-level detail on `web/static/index.html`)
> - Full secrets/keys/cookies section
> - Comprehensive mission/laws/rules/goals (§1)
> - The full chronology of fixes and attempted solutions (§35)
> - Clear deprecation markers on the dead code (`geocoder.py`, duplicate `fetch_sold_comps_near_coords`, stale `fetch_sold_comps` in `homeharvest_scraper.py`)
> - The full test coverage map (§33)
> - A dedicated outstanding-issues table with priority levels (§36)
> - LoopNet cookie bundle import detail (§15)
> - FLIP RADAR source routing table (§26)
> - Code-component → DB-column mapping for land display (§21)

**If you're a new CLI agent: read V8 only. If V8 contradicts a sibling doc, V8 wins.**

---

## Quick Reference: Most Important Commands

```bash
# Verify environment
git log -1 --format='%H %s'         # expect: 5f2ca9d ... keepalive ...
git status --short                   # expect: only ?? loopnet_session.json and/or ?? TEMP_HANDOFF.md
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

# Check LoopNet session status
curl -s http://localhost:8080/api/loopnet/session/status | python3 -m json.tool

# Start a DEAL RADAR scan via the API
curl -X POST http://localhost:8080/api/scan \
  -H "Content-Type: application/json" \
  -d '{"location": "Dallas, TX", "scan_type": "residential", "price_max": 400000}'

# Start a LAVA SCAN nationwide
curl -X POST http://localhost:8080/api/scan \
  -H "Content-Type: application/json" \
  -d '{"location": "All", "scan_type": "residential", "lava_mode": true, "lava_scope": "nationwide", "lava_state": "TX"}'

# Start a FLIP RADAR scan
curl -X POST http://localhost:8080/api/scan \
  -H "Content-Type: application/json" \
  -d '{"location": "Detroit, MI", "scan_type": "flip", "flip_property_type": "single_family"}'
```

---

*REGOG REBUILD V8 — current as of `5f2ca9d` (June 2026)*
*98 passing tests · SQLite · Flask SSE · Style-filtered comps · Dark UI · LoopNet cookie bundle · Codespace keepalive*
*Three scan modes: DEAL RADAR 🎯 · LAVA SCAN 🌋 · FLIP RADAR 🔨*
*All data sources: public, free, no API keys required*
*All laws, rules, goals, keys, cookies, and fixes documented above*
*Supersedes REGOG_REBUILD_V6.md and REGOG_V5_REBUILD.md*
