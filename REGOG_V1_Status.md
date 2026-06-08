# REGOG V1 — Project Status & Known Issues

> **Real Estate Go/No-Go Scanner** | Built with Codebuff AI (Claude) | 3 Phases Complete

---

## Architecture Overview

```
regog/
├── main.py                       # CLI entry: scan, leads, report, config
├── config.py                     # All weights, thresholds, settings
├── requirements.txt              # Python deps (homeharvest, rich, httpx, jinja2, etc.)
├── db/
│   ├── schema.sql                # SQLite schema (properties, scan_sessions, price_history)
│   └── database.py               # Connection, init, upsert, search with JSON serialization
├── scrapers/
│   ├── homeharvest_scraper.py    # ✅ Active — pulls for_sale listings from Realtor.com
│   ├── redfin_scraper.py         # ✅ Active — fetches sold comps via HomeHarvest
│   ├── assessor_scraper.py       # ✅ Active — estimated_value proxy + county registry
│   ├── fema_scraper.py           # ✅ Active — FEMA flood zone via ArcGIS API
│   ├── zillow_stealth.py         # 🔧 Stub — for future Playwright-based scraping
│   └── permit_scraper.py         # 🔧 Stub — for future building permit lookups
├── enrichment/
│   ├── brain.py                  # ✅ Keyword-based property classifier (no LLM)
│   ├── comp_engine.py            # ✅ Median price comps with radius expansion
│   ├── enricher.py               # ✅ Orchestrates assessor + FEMA enrichment
│   └── geocoder.py               # ✅ Nominatim geocoding with rate limits
├── scoring/
│   ├── residential_score.py      # ✅ 5-signal scoring (deviation, DOM, assessor, condition, flood)
│   ├── land_score.py             # ✅ Acreage + zoning + utilities scoring
│   ├── commercial_score.py       # ✅ Subtype-routed (multifamily, hotel, etc.)
│   └── utils.py                  # Shared assign_tier + parse_flags
├── ui/
│   ├── terminal.py               # ✅ Rich dashboard — dark theme, red accents
│   ├── report_generator.py       # ✅ Jinja2-powered HTML report generation
│   └── templates/report.html.j2  # ✅ Depth-layered dark UI with floating cards
└── scheduler/
    └── scan_scheduler.py         # 🔧 Stub — APScheduler for recurring scans
```

---

## Phase 1: Foundation (✅ Complete)

**What was built:**
- Project scaffolding, directory structure, all modules
- SQLite DB with full schema (properties, scan_sessions, price_history)
- HomeHarvest scraper — fetches for_sale listings from Realtor.com via the `homeharvest` library
- Keyword-based Brain classifier — scans descriptions for distressed, teardown, fire damage, vacant, luxury signals
- Comp engine — median price calculation with radius expansion (3→5→7→10mi)
- Residential, land, and commercial scoring modules
- Rich terminal UI with color-coded tiers (🔥 HOT, 🌡 WARM, ⚪ NEUTRAL, ⚠️ RISKY, 💀 SKIP)
- HTML report template with depth-layering dark theme

**Test result:** First Dallas scan returned 3,689 properties, all NEUTRAL (comps were empty, so price_deviation scored 0).

**Known issue resolved:** Property type values in `main.py` had to be changed from `["condo", "townhouse"]` to `["condos", "condo_townhome"]` to match HomeHarvest's `SearchPropertyType` enum.

---

## Phase 2: Sold Comps (✅ Complete)

**What was built:**
- `redfin_scraper.py` — fetches sold listings via HomeHarvest (`listing_type="sold"`, past 180 days, up to 200 comps)
- Reuses `normalize_listing` from `homeharvest_scraper` for consistent schema
- Wired into `cmd_scan`: sold comps fetched once per scan location, passed to `calculate_comps(prop, sold_comps, ...)`
- Also wired into scheduled scan (`cmd_schedule`)

**Test result:** Dallas scan with real comps:
- 200 sold comps loaded
- 3,689 properties processed
- **385–428 HOT leads** identified (properties priced significantly below median comp prices)

---

## Phase 3: Assessor & FEMA Enrichment (✅ Complete)

### Assessor Enrichment

**Implementation:**
- `homeharvest_scraper.py`: `normalize_listing` now captures `estimated_value`, `assessed_value`, `county` from HomeHarvest output
- `assessor_scraper.py`: 
  - When `assessed_value` is None but `estimated_value` exists (HomeHarvest provides AVM estimates for for_sale listings), uses `estimated_value` as proxy
  - Built-in county registry for 50+ major US metro areas (Texas, CA, AZ, FL, NY, IL, etc.)
  - Caching to avoid redundant lookups

**Scoring impact:** The `assessor_gap` signal (20% of residential score) now has real data. Properties listed below estimated market value score higher.

### FEMA Flood Zone Integration

**Implementation:**
- `fema_scraper.py`: Queries `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query`
- Endpoint: ArcGIS REST, layer 28 (Flood Hazard Zones), ~5.5M features indexed
- Query format: JSON `geometry` param with lat/lon and WGS84 spatial reference
- Caching: 100m resolution (3 decimal places), in-memory dict
- Retry logic: up to 2 retries with 2s delay for transient failures
- Rate limiting: 1s minimum between requests

**Known issue — FEMA API reliability:**
The FEMA ArcGIS API is **intermittently unreliable**. It works in direct testing (returns Zone X for Dallas) but frequently returns `"Failed to execute query"` errors when called in rapid succession from the scan loop. This appears to be rate limiting from the free government endpoint.

**Mitigation:**
- `--skip-flood` flag added to `scan` command — skips FEMA lookups entirely for fast scans
- Scheduled scans default to `skip_flood=True`
- When flood zone is unavailable, scoring falls back to neutral 8 pts (out of 10 possible on the flood_penalty signal)
- Retry logic handles transient failures

### Score Bar Visualization

The HTML report and terminal UI now show color-coded score bars:
- Green (≥ 70): 🔥 HOT
- Yellow (≥ 50): 🌡 WARM  
- Red (< 50): Lower tiers

### DB Migrations

- `database.py` has `_run_migrations()` that auto-adds `estimated_value`, `county`, `flood_zone` columns to existing databases
- Idempotent — checks `PRAGMA table_info` before adding

---

## Test Scan Results (Dallas, TX — price ≤ $400k)

| Metric | Phase 1 (no comps) | Phase 2 (with comps) | Phase 3 (with enrichment) |
|--------|-------------------|---------------------|--------------------------|
| Listings found | 3,689 | 3,689 | 3,689 |
| Sold comps | 0 | 200 | 200 |
| 🔥 HOT leads | 0 | ~400 | ~385 |
| Assessed values | N/A | N/A | HomeHarvest AVM estimates |
| Flood zones | N/A | N/A | FEMA API (intermittent) |

---

## Known Problems & Limitations

### 1. FEMA API Unreliable (P1)
- **Symptom:** `FEMA API error: Failed to execute query` on most requests during a scan
- **Root cause:** Likely rate limiting on the free government ArcGIS endpoint
- **Workaround:** Use `--skip-flood` flag (recommended for normal usage)
- **Future fix:** Consider caching flood zone data at the ZIP/city level rather than per-property; or use cached tile data instead of real-time queries

### 2. Assessed Values Are AVM Estimates (P3)
- **Current behavior:** Uses HomeHarvest's `estimated_value` (a Zestimate-like AVM) as a proxy for county tax assessment
- **Limitation:** AVM estimates are not actual county tax rolls. The `assessor_gap` signal compares list price to market estimate, not tax assessment
- **Future:** Add direct county assessor website scraping (varies by county, complex)

### 3. County Lookup Limited to Major Metros (P3)
- **Current behavior:** Built-in registry covers ~50 major US cities
- **Limitation:** Smaller cities/suburbs not mapped → county remains None
- **Future:** Use geocoder (Nominatim reverse geocode) for dynamic county resolution

### 4. No Production Database Locking (P3)
- **Symptom:** `sqlite3.OperationalError: database is locked` when scans are interrupted
- **Root cause:** SQLite WAL mode + concurrent access
- **Fix:** Re-run `regog init` to clear locks, or delete the .db-shm/.db-wal files

### 5. Comp Radius Is Bounding Box, Not Great-Circle (P2)
- **Current behavior:** Simple bounding box filter (1° lat ≈ 69mi, 1° lon ≈ 54mi)
- **Accuracy:** Good enough for dense urban areas, inaccurate at high latitudes or for large radii
- **Future:** Replace with haversine formula or spatialite extension

### 6. HomeHarvest Single-Threaded (P1)
- **Limitation:** HomeHarvest fetches are synchronous — 3,689 listings take ~2-3 minutes
- **Future:** Could parallelize but HomeHarvest may rate-limit

### 7. No Unit Tests (Across all phases)
- **Current:** Zero tests beyond manual integration scans
- **Risk:** Changes could break scoring/scraping without detection
- **Recommendation:** Add pytest tests for scoring modules and comp engine

### 8. Land & Commercial Scan Types Untested (P1)
- **Current:** `land` and `commercial` scoring modules exist but have never been validated with real HomeHarvest data
- **Limitation:** HomeHarvest's `SearchPropertyType` has limited coverage (`["multi_family"]` is the only valid type for commercial; `["land"]` for land)
- **Recommendation:** Test with actual land/commercial locations to validate scoring

### 9. Config Persistence Not Implemented (P1)
- **Current:** `config --set` prints a notice to edit config.py directly
- **Limitation:** No way to persist config changes between sessions

---

## CLI Usage

```bash
# Initialize DB (also runs migrations)
python regog/main.py init

# Full scan with all enrichment (FEMA may be slow)
python regog/main.py scan residential --location "Dallas, TX" --price-max 400000

# Fast scan (skip FEMA flood lookups)
python regog/main.py scan residential --location "Dallas, TX" --price-max 400000 --skip-flood

# Other scan types (stubs — land/commercial property types limited)
python regog/main.py scan land --location "Texas" --acres-min 5
python regog/main.py scan commercial --location "Chicago, IL" --type multifamily

# View leads
python regog/main.py leads --tier HOT --limit 20
python regog/main.py leads --score-min 70

# Generate HTML report
python regog/main.py report --session-id <id>
python regog/main.py report  # uses latest session

# View configuration
python regog/main.py config --show
```

---

## Scoring Signal Breakdown (Residential)

| Signal | Weight | Max Pts | Data Source | Phase |
|--------|--------|---------|-------------|-------|
| Price Deviation | 40% | 40 | Sold comp median vs list price | P2 |
| Assessor Gap | 20% | 20 | Estimated value vs list price | P3 |
| Days on Market | 15% | 15 | HomeHarvest listing data | P1 |
| Condition | 15% | 15 | Brain keyword classifier | P1 |
| Flood Penalty | 10% | 10 | FEMA API (intermittent) | P3 |

**Tier thresholds:** HOT ≥ 70, WARM ≥ 50, NEUTRAL ≥ 35, RISKY ≥ 20, SKIP < 20

---

## Recommendations for Next Phase

1. **FEMA caching:** Pre-compute flood zones at ZIP code level (batch query, store results, no per-property API calls)
2. **County assessor scraping:** Add qPublic platform scraper for county-level tax assessment data
3. **Unit tests:** Add pytest for `score_residential()`, `calculate_comps()`, `classify_property()`
4. **Config persistence:** Save/load config via JSON file
5. **Parallel scraping:** Use `concurrent.futures` for faster multi-city scans
