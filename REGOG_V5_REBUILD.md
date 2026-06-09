# REGOG V5 — Complete Rebuild Guide

> **Purpose:** Real Estate Go/No-Go Scanner. Scrapes Realtor.com (via HomeHarvest) for active + sold listings, classifies properties via keyword matching, finds comparable sales via 2D expansion search (radius + time), scores each property 0-100 across 5-6 signals, and serves results via a dark-themed Flask web app with streaming SSE updates.

---

## 1. Project Structure

```
REGOG_V5_REBUILD.md          <-- This file
serve_report.py              <-- Entry point: runs Flask web app on port 8080
regog.db                     <-- SQLite database (auto-created)
regog/
  requirements.txt
  config.py                  <-- ALL thresholds, weights, settings in one place
  main.py                    <-- CLI entry point (argparse, subcommands)
  db/
    schema.sql               <-- Full CREATE TABLE statements
    database.py              <-- SQLite connection, init, migrations, CRUD
  scrapers/
    __init__.py
    homeharvest_scraper.py   <-- Fetches active listings via HomeHarvest library
    redfin_scraper.py        <-- Fetches SOLD comps via HomeHarvest (listing_type="sold")
    zillow_stealth.py        <-- (Optional) Zillow scraper via Playwright
    fema_scraper.py          <-- FEMA flood zone lookup by lat/lon
    assessor_scraper.py      <-- Assessor/valuation enrichment
    permit_scraper.py        <-- Permit risk signals from listing description
  enrichment/
    __init__.py
    brain.py                 <-- Keyword-based property classifier
    comp_engine.py           <-- Comparable sales engine (2D expansion)
    enricher.py              <-- Orchestrates enrichments (FEMA, assessor, permits)
    listing_filter.py        <-- Filters out auction bait, burned, demolition
    geocoder.py              <-- DEAD CODE — Nominatim geocoder, never called
  scoring/
    __init__.py
    utils.py                 <-- Shared: tier assignment, comp fallback, confidence cap, variance penalty
    residential_score.py     <-- 0-100 scoring for single-family homes
    land_score.py            <-- 0-100 scoring for vacant land
    commercial_score.py      <-- 0-100 scoring for commercial properties
  scheduler/
    __init__.py
    scan_scheduler.py        <-- APScheduler wrapper for recurring scans
  ui/
    __init__.py
    terminal.py              <-- Rich console output (tables, panels)
    report_generator.py      <-- Jinja2 HTML report generator
    templates/
      report.html.j2         <-- HTML report template
  utils/
    __init__.py
    property_type.py         <-- Maps styles to residential/land/commercial categories
    density.py               <-- ZIP-based urban/suburban/rural classification
    rate_limiter.py          <-- Rate limiting for scrapers
    config_store.py          <-- Persistent config overrides
web/
  __init__.py
  app.py                     <-- Flask app with REST API + SSE streaming + background scan thread
  static/
    index.html               <-- Single-page dark theme UI (all CSS + JS inline)
tests/
  __init__.py
  conftest.py                <-- Shared pytest fixtures
  test_residential_score.py  <-- 88 tests covering all scoring components
  test_land_score.py
  test_utils.py
  test_permit_scraper.py
README.md                    <-- Project README
```

---

## 2. Setup & Installation

```bash
# Python 3.11+ required
cd /workspaces/REgog
pip install -r regog/requirements.txt

# Install Playwright for optional Zillow scraping
playwright install chromium

# Run database init (creates regog.db with schema + migrations)
python3 -c "from db.database import init_db; init_db()"

# Start the web app
python3 serve_report.py
# Opens on http://localhost:8080
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
```

---

## 3. Configuration (regog/config.py)

All tunable parameters live in ONE file. Key constants:

### Scoring Weights
```python
RESIDENTIAL_WEIGHTS = {
    "price_deviation": 0.40,   # How far below median comp price
    "dom_signal": 0.15,        # Days on market anomaly
    "assessor_gap": 0.20,      # Listed vs assessed value gap
    "condition": 0.15,         # Brain classification
    "flood_penalty": 0.10,     # FEMA zone deduction
}
LAND_WEIGHTS = { "price_per_acre_deviation": 0.40, "zoning_bonus": 0.20, ... }
COMMERCIAL_WEIGHTS = { "price_deviation": 0.35, "assessor_gap": 0.25, ... }
```

### Lead Tiers
```python
TIER_THRESHOLDS = {
    "HOT": 70, "WARM": 50, "NEUTRAL": 35, "RISKY": 20, "SKIP": 0
}
```

### Comp Engine
```python
MIN_COMPS_REQUIRED = 5  # Search expands until 5+ comps found
COMP_LOOKBACK_TIERS = [180, 270, 365, 540, 730]  # Lookback windows (days)
COMP_CONFIDENCE_HIGH = 0.80
COMP_CONFIDENCE_MEDIUM = 0.50
COMP_CONFIDENCE_LOW = 0.00
COMP_STALENESS_PENALTY = 0.15  # Applied when lookback > 365d
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

### Brain Classifier Keywords
```python
CLASSIFICATION_KEYWORDS = {
    "distressed": ["distressed", "as-is", "needs work", "fixer-upper", ...],
    "teardown":   ["teardown", "land value", "buildable lot", "demolish", ...],
    "fire_damage":["fire damage", "burnt", "burned", "smoke damage", ...],
    "vacant":     ["vacant", "abandoned", "boarded up", ...],
    "luxury":     ["luxury", "high-end", "gourmet kitchen", "waterfront", ...],
}
```

### FEMA Flood Scores
```python
FLOOD_SCORES = {
    "X": 10,     # Minimal risk — no penalty
    "AE": 3,     # High risk — 7pt penalty
    "A": 4,      # High risk
    "VE": 0,     # Coastal extreme — full penalty
    None: 8,     # Unknown — slight penalty
}
```

### Condition Scores
```python
CONDITION_SCORES = {
    "standard": 15, "luxury": 12, "vacant": 10,
    "distressed": 7, "teardown": 4, "fire_damage": 3,
}
```

---

## 4. Database (regog/db/)

### schema.sql
Creates 3 tables:
- **properties**: All listing data with 50+ columns covering address, price, comps, scores, brain output, filter flags
- **scan_sessions**: Tracks scans (id, started_at, scan_type, search_params JSON, counts)
- **price_history_tracking**: Price change history (not actively used)

Key columns on `properties`:
```
listing_id TEXT PRIMARY KEY, source, scan_type, style, address, city, state, zip,
lat, lon, list_price, price_per_sqft, sqft, acres, beds, baths, year_built,
days_on_market, listing_status, listing_description, last_sold_price, last_sold_date,
assessed_value, estimated_value, flood_zone, brain_classification, brain_red_flags (JSON),
brain_green_flags (JSON), comp_median_price, comp_count, comp_radius_miles, comp_listings (JSON),
comp_confidence_label, comp_variance_high, score_total, score_price_deviation, score_dom_signal,
score_assessor_gap, score_condition, score_flood_penalty, lead_tier, price_deviation_pct,
data_confidence, filter_reason, filter_type, ...
```

### database.py — Key Functions
- `init_db()`: Reads schema.sql, runs migrations (adds columns for new features)
- `_run_migrations()`: ALTER TABLE ADD COLUMN for each new field (non-destructive)
- `create_scan_session()`: Inserts row, returns session_id (8-char UUID)
- `complete_scan_session()`: Updates completed_at + counts
- `upsert_property()`: INSERT OR UPDATE based on listing_id. Serializes JSON fields
- `get_session_properties()`: SELECT * for a session, ordered by score DESC
- `get_stats()`: Aggregate counts (total, hot, warm, sessions, avg_score)
- `_serialize_value()`: Lists/dicts → JSON strings for DB
- `_deserialize_row()`: JSON strings → Python objects on read

---

## 5. Scan Pipeline (web/app.py + regog/main.py)

Both the CLI (`main.py`) and the web app (`web/app.py`) follow the same pipeline. The web app runs it in a background thread with SSE streaming.

### Pipeline Steps (in order):

```
1. Fetch SOLD comps ────────── redfin_scraper.fetch_sold_comps(location, listing_type="sold")
2. Fetch ACTIVE listings ───── homeharvest_scraper.fetch_listings(location, listing_type="for_sale")
3. (Optional) Fetch Zillow ─── zillow_stealth.fetch_zillow_listings()
4. For each listing:
   a. Normalize ──────────── homeharvest_scraper.normalize_listing(raw_dict → property schema)
   b. Price filter ────────── Skip if outside price_min/price_max
   c. Brain classify ──────── enrichment.brain.classify_property(description → classification)
   d. Listing filter ──────── enrichment.listing_filter.filter_listing(skip/flag auctions, bait, burned)
   e. Enrich ──────────────── enrichment.enricher.enrich_property(FEMA, assessor, permits)
   f. Calculate comps ─────── enrichment.comp_engine.calculate_comps(active vs sold, 2D expansion)
   g. Score ──────────────── scoring/*.score_*(property → scores dict + total + tier)
   h. Upsert to DB ────────── database.upsert_property()
   i. Push to SSE stream ──── (web app only) queue → SSE → frontend
5. Complete session ───────── database.complete_scan_session()
```

### Property Types (HomeHarvest API):
```python
property_types = {
    "residential": ["single_family", "mobile"],  # Mobile homes included here
    "land":        ["land"],
    "commercial":  ["multi_family", "apartment", "condos", "townhomes", "duplex_triplex", "farm"],
}.get(scan_type)
```

---

## 6. HomeHarvest Scraper (regog/scrapers/homeharvest_scraper.py)

Uses the `homeharvest` library which scrapes Realtor.com (free, no API key).

### fetch_listings()
- Params: location (str), listing_type (for_sale/sold/pending), past_days, property_type (list or None)
- Calls `scrape_property()` which returns a pandas DataFrame
- Converts to list of dicts via `df.to_dict(orient="records")`

### normalize_listing()
Maps HomeHarvest's varied column names to REGOG's schema using helper `g(*keys)`:
- **address**: full_street_line, street, address, full_address, formatted_address
- **price**: list_price, price, current_price, sold_price
- **sqft**: sqft, square_feet, sq_ft, living_area, building_area
- **acres**: acres, acreage, lot_size_acres, lot_acres, total_acres, parcel_acres, land_area...
- **acres fallback**: If acres not found, derive from lot_sqft / 43560
- **sqft fallback for land**: If no sqft but has acres, sqft = acres * 43560
- **style**: style, property_type, home_type (e.g. SINGLE_FAMILY, CONDOS, LAND)
- **lat/lon**: latitude/lat, longitude/lon/lng
- **property_url**: property_url, rdc_web_url, href, url
- **primary_photo**: primary_photo, photo, image_url, thumbnail_url
- **price_per_sqft**: Calculated if not provided (price / sqft)
- **price_per_acre**: Calculated if not provided (price / acres)

---

## 7. Redfin Scraper / Sold Comps (regog/scrapers/redfin_scraper.py)

Actually uses HomeHarvest under the hood with `listing_type="sold"`. Named "redfin" for historical reasons.

### fetch_sold_comps()
- Fetches sold properties for the entire location (city-level)
- Returns max 200 sold comps
- Each normalized via `normalize_sold_listing()`

### normalize_sold_listing()
- Explicitly handles sold-specific column names:
  - `sold_price` → `list_price` (for comp engine compatibility)
  - `last_sold_date`, `sold_date`, `close_date`, `closing_date` → `last_sold_date`
- Sets `listing_status = "sold"` explicitly
- Returns None if no sold_price (critical field)
- Same acres/sqft derivation logic as normalizer

---

## 8. Brain Classifier (regog/enrichment/brain.py)

Keyword-based (no LLM). Scans `listing_description` for signal keywords.

### classify_property()
Returns dict with:
- `classification`: Priority order — fire_damage > teardown > distressed > vacant > luxury > standard
- `confidence`: Float 0-1, increments by 0.2-0.3 per matched keyword
- `red_flags`: List of matched RED_FLAG_KEYWORDS (15 keywords: foundation issues, mold, termites...)
- `green_flags`: List of matched GREEN_FLAG_KEYWORDS (12 keywords: renovated, move-in ready...)
- `seller_motivation`: high/medium/low from SELLER_MOTIVATION_KEYWORDS
- `estimated_condition`: Maps classification to condition string
- `is_luxury`: Boolean flag
- `notes`: Human-readable summary

### Special case: Land override
If `scan_type == "land"`, classification is forced to `"land_only"` regardless of description.

---

## 9. Listing Filter (regog/enrichment/listing_filter.py)

Filters out junk listings before scoring. Runs AFTER brain classification (so brain results are available).

### Filter Chain (order matters — first match wins):

1. **check_auction** → `skip` action
   - Keywords: "foreclosure auction", "opening bid", "online auction", "sheriff sale", etc.
   - Also triggers if price < $5K + description mentions auction

2. **check_bait_price** → `skip` action
   - Price < $1,000 → always bait
   - Price < $10,000 + residential style + no sqft → bait
   - Keywords: "call for price", "for investment only", "coming soon listing"

3. **check_burned** → `flag` action (kept but tagged)
   - Keywords: "burnt", "burned down", "fire damaged", "gutted by fire", "structure fire"
   - Also triggers on brain_classification == "fire_damage"

4. **check_demolition** → `flag` action
   - Keywords: "must demolish", "condemned", "uninhabitable", "structural damage"
   - Also triggers on brain_classification == "teardown"

5. **check_land_masquerade** → `flag` action
   - Catches SINGLE_FAMILY listings that are actually lots/land
   - Keywords: "buildable lot", "land only", "vacant lot", "raw land"

### Filter output:
```python
{"action": "skip" | "flag", "reason": "human-readable string", "filter_type": "auction"|"bait"|"burned"|"demolition"|"land_masquerade"}
```

---

## 10. Comp Engine (regog/enrichment/comp_engine.py)

The core comparable sales engine. Finds sold properties similar to each active listing.

### Key Functions:

#### get_comp_radii(prop) → [r1, r2, r3]
Looks up density (urban/suburban/rural) + category (residential/land/commercial) → returns 3-tier radius list from config.

#### _filter_by_style(properties, target_style, scan_type)
Style matching map:
```
SINGLE_FAMILY → [SINGLE_FAMILY, MANUFACTURED, MOBILE]
LAND          → [LAND]
FARM          → [FARM, LAND]
CONDOS        → [CONDOS]
...etc
```

#### _filter_by_distance(properties, center_lat, center_lon, radius_miles)
Haversine distance filter. Only includes properties with valid lat/lon.

#### _filter_by_lookback(properties, max_days)
Filters by last_sold_date vs today. Properties without dates are included conservatively.

#### find_comps_with_expansion(style_filtered, target_lat, target_lon, radii) → (comps, radius, tier, lookback, staleness)

**THE CRITICAL FUNCTION — 2D Expansion Search**

Expansion order (outer loop = time, inner loop = radius):
```
180d/r1 → 180d/r2 → 180d/r3 → 180d/r3×2 → 180d/r3×4 → ... (up to 100mi)
270d/r1 → 270d/r2 → 270d/r3 → 270d/r3×2 → ...
365d/r1 → ... 
540d/r1 → ...
730d/r1 → ... (2 years max lookback)
```

- Requires MIN_COMPS_REQUIRED (5) comps before accepting
- If 5+ comps found at any radius/lookback combination, returns immediately
- If all combinations exhausted, falls back to 730d / 100mi — returns whatever found
- tier_used: 1 (r1), 2 (r2), 3 (r3), 5+ (expanded multipliers), 99 (fallback)

#### calculate_comps(property_dict, sold_properties, scan_type) → comp_result dict

1. Get radii from ZIP density + category
2. Style-filter sold properties
3. Run 2D expansion search
4. Apply similarity filters (if 5+ comps):
   - Sqft filter: ±30% for residential/commercial
   - Bed/bath filter: ±1 for residential
   - Acres filter: ±50% for land
5. Calculate medians (price, $/sqft, $/acre)
6. Calculate price_deviation_pct = (target - median) / median * 100
7. Calculate variance metrics:
   - comp_price_range = max(prices) - min(prices)
   - comp_price_stddev = standard deviation
   - comp_variance_high = range/median > 50%
8. Calculate confidence (see below)
9. Build top_comps list (top 10 nearest-price comps with address, price, sqft, acres, beds, baths, photo, URL, distance, sold_date)

#### calculate_comp_confidence(comp_count, tier_used, lookback_used) → (confidence_float, label)

Starts at 1.0, subtracts:
- 1 comp: -0.40, 2 comps: -0.35
- tier 2: -0.10, tier 3: -0.20, tier 4+: -0.25
- lookback > 365d: -0.15, > 180d: -0.05

Results:
- ≥ 0.80 → HIGH
- ≥ 0.50 → MEDIUM
- < 0.50 → LOW

---

## 11. Scoring Modules

### Residential (regog/scoring/residential_score.py)

6 score components:
1. **price_deviation** (40 pts max): Below median = positive, above = negative penalty
2. **dom_signal** (15 pts): Bracketed by days on market (≤30d=15, ≤90d=10, ≤180d=5, ≤365d=2, >365d=0)
3. **assessor_gap** (20 pts): (assessed - listed) / assessed * 100, scaled to 20. Missing = 5
4. **condition** (15 pts): From brain classification (standard=15, distressed=7, fire_damage=3, etc.)
5. **flood_penalty** (0-10): From FLOOD_SCORES map
6. **permit_risk** (-5 to +3): From permit_flags
7. (After) **comp_fallback**: If comp_count=0, use estimated_value as proxy
8. (After) **confidence_cap**: LOW caps price at 10, MEDIUM caps at 20
9. (After) **variance_penalty**: If comps<5 and variance_high, reduce price by 25%

Special: fire_damage/teardown get "DISTRESSED_" prefix on tier.

### Land (regog/scoring/land_score.py)

6 score components:
1. **price_per_acre_deviation** (40 pts): List $/acre vs comp median $/acre. Needs acres + comp data
2. **zoning_bonus** (20 pts): Buildable zones=20, non-buildable=2, unknown=10
3. **road_access_bonus** (10 pts): From brain_green_flags keywords
4. **utilities_bonus** (10 pts): From brain_green_flags keywords
5. **acreage_premium** (10 pts): ≤1ac=10, ≤5ac=8, ≤10ac=6, ≤40ac=4, >40ac=2
6. **flood_penalty** (0-10): Same FLOOD_SCORES logic

**CRITICAL: Fallback logic when comp_price_per_acre is missing but price_deviation_pct exists:**
- Stores fallback_price_score in `scores["price_deviation"]` so the recalculation includes it
- Without this fix, the total recalculates from scores and drops the fallback

### Commercial (regog/scoring/commercial_score.py)

5 score components:
1. **price_deviation** (35 pts)
2. **assessor_gap** (25 pts)
3. **cap_rate_estimate** (20 pts): From description keyword analysis
4. **condition** (10 pts): Scaled from CONDITION_SCORES
5. **flood_penalty** (0-10)

### Scoring Utilities (regog/scoring/utils.py)

- `assign_tier(score)`: Looks up score in TIER_THRESHOLDS (highest matching)
- `parse_flags(value)`: List or JSON string → Python list
- `apply_comp_fallback()`: When comp_count=0, use estimated_value as price proxy
- `apply_confidence_cap()`: LOW → cap price at 10, MEDIUM → cap at 20
- `apply_variance_penalty()`: comps<5 + high_variance → reduce price by 25%
- `cap_score_if_no_comps()`: If no comps + no estimated_value, max total = 30 (RISKY)

---

## 12. Enricher (regog/enrichment/enricher.py)

- **Assessor data**: Calls `assessor_scraper.enrich_with_assessor_data()` (extracts assessed_value, estimated_value, county)
- **FEMA flood zone**: Calls `fema_scraper.get_flood_zone(lat, lon)` — skip if `skip_flood=True`
- **Permit signals**: Calls `permit_scraper.fetch_permits(address, zip, county, description)` — keyword-based permit risk

---

## 13. Web App (web/app.py)

Flask app with:
- `GET /`: Serves `static/index.html`
- `POST /api/scan`: Starts background scan thread, returns session_id + stream_url
- `GET /api/scan/<id>/stream`: SSE endpoint streaming properties as they're scored
- `GET /api/scan/<id>/status`: Polling endpoint for scan progress
- `POST /api/scan/<id>/cancel`: Sets cancel event to stop running scan
- `GET /api/scan/<id>/results`: Paginated results (params: page, per_page, tier)
- `GET /api/stats`: DB aggregate stats
- `GET /api/scans`: Recent 20 scan sessions
- `POST /api/saved/<id>`: Toggle save/unsave property
- `GET /api/saved`: List saved properties
- `GET /api/config`: Return REGOG config

### Background Scan Thread (`_run_scan_background`)
Same pipeline as CLI, with additions:
- Thread-safe status updates via lock
- SSE queue pushes each property as it's scored
- Cancel event checked every iteration
- Filtered-out counter tracked in status

### Score Mapping (critical for land)
```python
if scan_type == "land":
    prop["score_price_deviation"] = scores.get("price_deviation", scores.get("price_per_acre_deviation", 0))
    prop["score_assessor_gap"] = scores.get("assessor_gap", scores.get("zoning_bonus", 0))
    prop["score_condition"] = scores.get("condition", scores.get("acreage_premium", 0))
else:
    prop["score_price_deviation"] = scores.get("price_deviation", 0)
    prop["score_dom_signal"] = scores.get("dom_signal", 0)
    prop["score_assessor_gap"] = scores.get("assessor_gap", 0)
    prop["score_condition"] = scores.get("condition", 0)
prop["score_flood_penalty"] = scores.get("flood_penalty", 0)
```

### Server Entry (serve_report.py)
```python
from db.database import init_db
init_db()  # Run migrations on every startup
from web.app import app
app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
```

---

## 14. Frontend (web/static/index.html)

Single HTML file with 900+ lines of inline CSS + JS. Dark theme with REGOG styling.

### CSS Theme Variables:
```css
--bg: #0a0a0a;           --bg-surface: #111111;
--bg-card: #111118;      --accent: #ff2233;
--accent-glow: rgba(255,34,51,0.4);
--text: #e8e8f0;         --green: #44ff66;
--amber: #ffaa00;        --magenta: #ff44aa;
```

### Key UI Elements:
- **Scan bar**: Location input, type dropdown, price range, SCAN/STOP buttons
- **Stats bar**: Total, HOT, WARM, avg score, live counter
- **Property cards**: Clickable cards with address, price, badges, score bar, flags
- **Expanded detail**: Scrollable comp cards with Zillow links, score breakdown bar, brain output
- **History panel**: Grouped by scan type with dates
- **Saved panel**: Starred properties

### Key JS Functions:
- `startScan()`: POSTs to /api/scan, opens SSE stream, calls addProperty for each
- `addProperty(prop)`: Creates card DOM element with all fields, inserts in sort order
- `toggleExpand(listingId)`: Toggles `.expanded` class on card
- `renderCompListings(prop)`: Builds clickable comp cards with thumbnail, beds, baths, sqft, acres, distance
- `getCompUrl(comp, parentProp)`: Builds Zillow address URL directly (skips Realtor.com URL which hides sold prices)
- `buildCompWarning(prop)`: Shows appropriate warning for low comps / high variance
- `getListingUrl(prop)`: Main listing URL (Realtor.com > Zillow > Google Maps)
- `filterTier(tier)`: Filters visible cards by HOT/WARM/ALL
- `setSort(mode)`: Re-sorts by price $↑/$↓, profit %↑/%↓, score ↓

### Score Breakdown Bar (segmented):
```html
<!-- 5 segments: Price (green), Assessor (blue), DOM (amber), Cond (purple), Flood (red) -->
<div class="segment" style="width:${(score_price_deviation)/100*100}%;background:var(--green);" ...>
<div class="segment" style="width:${(score_assessor_gap)/100*100}%;background:#44aaff;" ...>
<div class="segment" style="width:${(score_dom_signal)/100*100}%;background:var(--amber);" ...>
<div class="segment" style="width:${(score_condition)/100*100}%;background:#aa44ff;" ...>
<div class="segment" style="width:${(score_flood_penalty)/100*100}%;background:#ff4466;" ...>
```

### Scrollbar (Custom):
```css
::-webkit-scrollbar { width: 16px; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.5); border-radius: 8px; border: 3px solid transparent; background-clip: padding-box; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.75); }
* { scrollbar-width: auto; scrollbar-color: rgba(255,255,255,0.5) rgba(0,0,0,0.3); }
```

---

## 15. Property Type Detection (regog/utils/property_type.py)

Maps style strings to categories for comp radius selection.

```python
_RESIDENTIAL_STYLES = {"SINGLE_FAMILY", "MANUFACTURED", "MOBILE"}
_LAND_STYLES = {"LAND", "LOT", "FARM", "RANCH", "ACREAGE", "VACANT"}
_COMMERCIAL_STYLES = {"CONDOS", "TOWNHOMES", "MULTI_FAMILY", "APARTMENT", "DUPLEX", ...}
```

**High-rise detection**: CONDO/CONDOS with stories >= 5 → reclassified as commercial.

---

## 16. Market Density (regog/utils/density.py)

ZIP-prefix-based density classification. Static lookup — no API calls.

- **Urban prefixes**: Major metro cores (100 NYC, 900 LA, 606 Chicago, 941 SF, 752 Dallas, 850 Phoenix...)
- **Rural prefixes**: MT, WY, ID, SD, ND, NV rural areas, WV, MS delta, NM, etc.
- **Default**: suburban

---

## 17. Known Issues & Edge Cases

1. **Sold comps fetched city-wide, not by radius**: HomeHarvest doesn't support coordinate-based queries, so comps are fetched for the entire city then filtered by distance in the comp engine. This means sparse areas get fewer comps.

2. **2 comps with wide variance**: Even with MIN_COMPS_REQUIRED=5, some areas simply don't have 5 sold comps. System falls back to whatever it can find with LOW confidence + variance penalty.

3. **$/sqft for land derived from acres**: sqft = acres * 43560. This is a rough estimate since land sqft doesn't equal building sqft.

4. **Score breakdown for land**: Frontend expects 5 score components, but land has different keys (zoning_bonus instead of assessor_gap, acreage_premium instead of condition). Mapping is in web/app.py.

5. **Realtor.com hides sold prices**: Comp card links use Zillow address URLs (not Realtor.com) since Realtor.com hides sold prices on listing pages.

6. **No coordinate-based sold comps**: fetch_sold_comps_near_coords() returns empty — use city-level fetch instead.

---

## 18. Tests

88 tests total. Run with:
```bash
cd /workspaces/REgog
python -m pytest tests/ -v --tb=short
```

Test files:
- `test_residential_score.py`: 10 test classes covering all 6 signals + tiers + edge cases + data types
- `test_land_score.py`: Basic land scoring tests
- `test_utils.py`: Tier assignment + flag parsing tests
- `test_permit_scraper.py`: Permit signal tests

Fixtures in `conftest.py`:
- `standard_residential`: Baseline property
- `hot_deal_residential`: Deep discount + long DOM
- `skip_residential`: Overpriced with red flags
- `missing_data_residential`: All None values
- `distressed_residential`: Fire damage classification

---

## 19. Quick Start (From Scratch)

```bash
# 1. Clone or create project structure as above
# 2. Install dependencies
pip install homeharvest beautifulsoup4 httpx lxml aiosqlite sqlite-utils rich geopy apscheduler jinja2 playwright playwright-stealth
playwright install chromium

# 3. Init database
cd /workspaces/REgog
python3 -c "from db.database import init_db; init_db()"

# 4. Start web server
python3 serve_report.py

# 5. Open browser → http://localhost:8080 → enter city → SCAN

# Or use CLI:
python3 regog/main.py scan residential --location "Dallas, TX" --price-max 400000
python3 regog/main.py leads --tier HOT
```

---

## 20. Architecture Diagram (Data Flow)

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐
│ Realtor.com │────▶│ HomeHarvest      │────▶│ normalize_   │
│  (Scraped)  │     │ scrape_property()│     │ listing()    │
└─────────────┘     └──────────────────┘     └──────┬───────┘
                                                    │
┌─────────────┐     ┌──────────────────┐            ▼
│ SOLD data   │────▶│ fetch_sold_comps │────▶ normalize_sold_listing()
│ (same city) │     │ (listing_type=    │            │
│             │     │  "sold")          │            │
└─────────────┘     └──────────────────┘            │
                                                    ▼
┌──────────────────────────────────────────────────────┐
│              Pipeline (per listing)                   │
│                                                        │
│  raw_dict ─▶ normalize_listing() ─▶ property_dict      │
│                                        │                │
│                                        ▼                │
│                              brain.classify_property()  │
│                                        │                │
│                                        ▼                │
│                            listing_filter.filter_listing│
│                            (skip: auction/bait)         │
│                            (flag: burned/demolition)    │
│                                        │                │
│                                        ▼                │
│                              enricher.enrich_property() │
│                              (assessor, FEMA, permits)  │
│                                        │                │
│                                        ▼                │
│                   comp_engine.calculate_comps()         │
│                   (style filter → 2D expansion →        │
│                    similarity filter → medians →       │
│                    variance → confidence)               │
│                                        │                │
│                                        ▼                │
│                   score_*(property_dict)                │
│                   (residential/land/commercial)         │
│                                        │                │
│                                        ▼                │
│                             upsert_property(DB)         │
│                             + push to SSE (web app)    │
└──────────────────────────────────────────────────────┘
```
