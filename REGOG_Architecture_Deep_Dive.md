# REGOG Architecture Deep Dive

> How REGOG finds, analyzes, and scores real estate deals — every data point, every method, every formula.

---

## Table of Contents

1. [Data Sources Overview](#1-data-sources-overview)
2. [Listing Scrapers](#2-listing-scrapers)
3. [Comp Data](#3-comp-data)
4. [Enrichment Pipeline](#4-enrichment-pipeline)
5. [Brain Classifier](#5-brain-classifier)
6. [Comp Engine](#6-comp-engine)
7. [Scoring Formula](#7-scoring-formula)
8. [Config & Weights](#8-config--weights)
9. [Data Pipeline Summary](#9-data-pipeline-summary)

---

## 1. Data Sources Overview

| Source | Method | Data Type | Status | Key Limitation |
|--------|--------|-----------|--------|----------------|
| **Realtor.com** (via HomeHarvest) | Python library → HTTP scraping | Active listings, sold comps | ✅ Fully working | No API key needed but rate-limited |
| **Zillow** (via Playwright) | Headless browser + stealth | Active listings | ✅ Works (optional `--use-zillow`) | Playwright must be installed; ~40 listings/page; bot detection possible |
| **Redfin** (via HomeHarvest) | Python library (Realtor.com data) | Sold comps | ✅ Fully working | Same as HomeHarvest |
| **FEMA NFHL** (ArcGIS REST API) | HTTP query with retry logic | Flood hazard zones | ✅ Fully working | Requires lat/lon; rate-limited 1 req/s; free, no key |
| **County Assessor** (built-in registry) | Hardcoded lookup table | County name | ✅ For 50+ major metros | Hardcoded; new cities won't match |
| **County Permit Portals** (Accela, etc.) | HTTP + BeautifulSoup | Permit records | ⚠️ V1 limited | Most portals require interactive JS (CAPTCHA, forms) |
| **Auction platforms** (Auction.com, Hubzu, etc.) | Not yet implemented | Auction listings | ❌ Planned for V2 | ToS prohibit scraping; Playwright needed |

### What each source actually provides

```
Realtor.com ────┬── for_sale listings ──→ normalize_listing() ──→ property dict
                └── sold listings ───────→ normalize_listing() ──→ comp dict

Zillow ───────── for_sale listings ────→ _normalize_zillow_item() → property dict
                                          (or DOM fallback)

FEMA NFHL ────── flood zone for lat/lon → get_flood_zone() ─────→ flood_zone string

HomeHarvest ──── estimated_value, assessed_value ───────────────→ assessor enrichment
```

---

## 2. Listing Scrapers

### 2a. HomeHarvest Scraper (`scrapers/homeharvest_scraper.py`)

**Method:** Uses the open-source `homeharvest` Python library, which scrapes Realtor.com's public search results pages (no API key needed). Returns a Pandas DataFrame.

**Called via:**
```python
from homeharvest import scrape_property
df = scrape_property(
    location="Dallas, TX",       # City, "City, State", or ZIP
    listing_type="for_sale",     # or "sold", "for_rent", "pending"
    past_days=90,                # look back window
    property_type=["single_family", "multi_family", "condos", "condo_townhome"],
)
```

**Data fields HomeHarvest returns** (the raw DataFrame columns):

| Raw Column | Maps To | Type | Always Fetched? |
|------------|---------|------|----------------|
| `property_id` / `listing_id` / `mls_id` | `listing_id` | string | ✅ Usually |
| `street` / `address` / `full_address` | `address` | string | ✅ Always |
| `city` / `municipality` | `city` | string | ✅ Always |
| `state` / `province` | `state` | string | ✅ Always |
| `zip` / `zip_code` / `postal_code` | `zip` | string | ✅ Usually |
| `latitude` / `lat` | `lat` | float | ✅ Always |
| `longitude` / `lon` / `lng` | `lon` | float | ✅ Always |
| `list_price` / `price` / `current_price` | `list_price` | int | ✅ Always |
| `sold_price` / `last_sold_price` | `last_sold_price` | int | ✅ (for sold listings) |
| `beds` / `bedrooms` | `beds` | int | ✅ Usually |
| `baths` / `bathrooms` / `full_baths` | `baths` | float | ✅ Usually |
| `sqft` / `square_feet` / `living_area` | `sqft` | int | ✅ Usually |
| `lot_sqft` / `lot_square_feet` | `lot_sqft` | int | ⚠️ Sometimes missing |
| `acres` / `acreage` / `lot_size_acres` | `acres` | float | ✅ Usually |
| `year_built` | `year_built` | int | ✅ Usually |
| `days_on_market` / `dom` / `listing_age` | `days_on_market` | int | ✅ Usually |
| `status` / `listing_status` | `listing_status` | string | ✅ Always |
| `description` / `listing_description` | `listing_description` | string | ✅ Usually |
| `price_per_sqft` | `price_per_sqft` | float | ⚠️ Calculated if missing |
| `estimated_value` / `zestimate` / `avm_value` | `estimated_value` | int | ⚠️ Not always available |
| `assessed_value` / `tax_assessment` | `assessed_value` | int | ⚠️ Not always available |
| `county` / `parish` | `county` | string | ⚠️ Sometimes |
| `last_sold_date` / `sold_date` | `last_sold_date` | string | ✅ (for sold) |
| `price_per_acre` | `price_per_acre` | float | ⚠️ Calculated if missing |
| `price_history` | `price_history` | list[dict] | ❌ Not available from HomeHarvest |

**Status:** ✅ Fully working. This is the PRIMARY listing source. The `normalize_listing()` function maps all these column name variations to REGOG's standard property schema.

**Why it works:** HomeHarvest simulates a browser-like HTTP session against Realtor.com. It's not an official API, but Realtor.com's public pages don't enforce CAPTCHAs for programmatic access at moderate volumes. The library handles pagination automatically (up to ~5,000 results per query).

**Rate limiting:** Configured in `config.py` under `RATE_LIMITS["realtor"]` — 2-5s delay between requests, max 200/hour.

---

### 2b. Zillow Stealth Scraper (`scrapers/zillow_stealth.py`)

**Method:** Playwright (headless Chromium) with anti-bot evasion. This is the second listing source, used only when `--use-zillow` is passed.

**Anti-bot stack:**
1. **`playwright-stealth`** — patches browser fingerprint vectors (WebGL, navigator.plugins, Chrome runtime, etc.)
2. **Viewport randomization** — randomly picks from 5 viewport sizes (1280×720 to 1920×1080)
3. **User agent rotation** — picks from 5 modern Chrome/Firefox UAs
4. **Locale/timezone randomization** — en-US, en, en-GB; fixed to America/New_York timezone
5. **Human-like scrolling** — scrolls 300-800px with random pauses (0.5-2s), sometimes scrolls back up
6. **Realistic HTTP headers** — Accept-Language, Accept, etc.
7. **`--disable-blink-features=AutomationControlled`** — removes the `navigator.webdriver=true` flag

**Data extraction (3 methods, in order of preference):**

1. **JSON/Next.js cache** — Extracts embedded JSON from Zillow's Next.js page state (`__NEXT_DATA__`, `__NUXT__`). This gives the most complete data with all fields.
2. **Apollo/GraphQL cache** — Tries to read `window.__APOLLO_STATE__` for the raw GraphQL query results.
3. **DOM parsing** — Fallback: queries DOM elements for `[data-test="property-card"]`, extracts text content from CSS selectors. Gives partial data (no lat/lon, no estimated_value).

**Data fields Zillow provides (JSON method):**

| Field | Maps To | Always Available? |
|-------|---------|-------------------|
| `zpid` / `id` | `listing_id` | ✅ Always |
| `address` / `addressStreet` | `address` | ✅ Always |
| `city` | `city` | ✅ Always |
| `state` | `state` | ✅ Always |
| `zipcode` | `zip` | ✅ Usually |
| `latLong.latitude` / `latitude` | `lat` | ✅ Usually |
| `latLong.longitude` / `longitude` | `lon` | ✅ Usually |
| `price` | `list_price` | ✅ Always |
| `beds` | `beds` | ✅ Usually |
| `baths` | `baths` | ✅ Usually |
| `area` / `sqft` | `sqft` | ✅ Usually |
| `daysOnZillow` / `daysOnMarket` | `days_on_market` | ✅ Usually |
| `statusType` | `listing_status` | ✅ Always |
| `description` | `listing_description` | ⚠️ Sometimes |
| `zestimate` | `estimated_value` | ✅ Usually (Zillow's Zestimate) |
| `imgSrc` | `img_url` | ✅ Usually |
| `detailUrl` | `detail_url` | ✅ Always → links to actual Zillow listing |
| `price_per_sqft` | `price_per_sqft` | ⚠️ Calculated if missing |

**Status:** ✅ Works but optional. Typical yield: ~40 listings per page, 2 pages = ~80 listings. Much smaller volume than HomeHarvest but catches listings Realtor.com misses.

**Rate limiting:** 4-9s random delays between requests, max 60/hour.

**Key limitation:** Zillow's bot detection is aggressive. The stealth measures work most of the time, but Zillow may serve CAPTCHAs or return empty results. The scraper has no CAPTCHA-solving capability.

---

## 3. Comp Data

### Sold Comps via Redfin Scraper (`scrapers/redfin_scraper.py`)

**Method:** Uses the same HomeHarvest library, but with `listing_type="sold"`. Despite the filename "redfin", the actual data comes from Realtor.com's sold listings (HomeHarvest labels the source as "redfin" as a convention).

```python
sold_comps = fetch_sold_comps(
    location="Dallas, TX",    # City-level query
    scan_type="residential",  # Maps to property type list
    past_days=180,            # Look back 6 months
    limit=200,                # Max 200 comps
)
```

**What it fetches:** Sold properties of the same type (single_family, multi_family, condos, condo_townhome, or land) that closed in the last 180 days, up to 200 properties.

**How comps are matched to listings:** Individual listing matching happens in the Comp Engine (see Section 6), not at the scraper level. The scraper fetches a broad pool of sold properties for the entire city/area.

**Same fields as HomeHarvest** — normalized via `normalize_listing()` with `source="redfin"`. The key field is `list_price` (which is the actual sold price for sold listings).

**Status:** ✅ Fully working. 200 comps per scan location.

---

## 4. Enrichment Pipeline

Every property that comes back from the scrapers goes through the enrichment pipeline (orchestrated by `enrichment/enricher.py`):

```
Raw Listing
    │
    ▼
normalize_listing()  →  Standard property dict with ~30 fields
    │
    ▼
enrich_property()
    ├── 1. enrich_with_assessor_data()  →  estimated_value, assessed_value, county
    ├── 2. get_flood_zone()             →  flood_zone (or skipped if --skip-flood)
    └── 3. fetch_permits()             →  permit_risk, unpermitted_additions, etc.
```

### 4a. Assessor Enrichment (`scrapers/assessor_scraper.py`)

**V1 method:** Extracts `estimated_value` and `assessed_value` directly from HomeHarvest results. If only `estimated_value` is available, it's used as a proxy for `assessed_value`.

**County name resolution:** Uses a **hardcoded lookup table** of ~50 major US metro → county name mappings (e.g., "Dallas, TX" → "Dallas County"). This is used for permit portal lookups and display purposes.

**Future V2 plan:** Geocode address → Nominatim → county assessor website → qPublic platform scraper for deeper tax/valuation data.

**Status:** ✅ Works for V1. Estimated value comes through HomeHarvest when available. County lookup limited to 50 major metros.

### 4b. FEMA Flood Zone (`scrapers/fema_scraper.py`)

**Method:** Queries the FEMA National Flood Hazard Layer (NFHL) ArcGIS REST API — **free, no API key required**.

```python
endpoint = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
params = {
    "geometry": '{"x":-96.7969,"y":32.7767,"spatialReference":{"wkid":4326}}',
    "geometryType": "esriGeometryPoint",
    "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA,FLOODWAY",
}
```

**Returns:** Flood zone code — `"X"` (minimal risk), `"AE"` (high risk, 100-year), `"A"` (high risk), `"VE"` (coastal extreme), or `None` (unknown/no data).

**Features:**
- In-memory cache (rounded to 3 decimal places ≈ 100m resolution) to avoid redundant queries
- Rate limiting: 1 second minimum between requests
- Retry logic: 2 retries on timeout/failure with 2s backoff
- Up to `--skip-flood` flag to skip entirely for faster scans

**Status:** ✅ Fully working. Free, no key required, reliable.

### 4c. Permit Signal Analysis (`scrapers/permit_scraper.py`)

**Two-tier approach:**

**Tier 1 (V1 — Works now):** Keyword-based inference from the listing description. Scans for:
- **Unpermitted signals:** "unpermitted", "no permit", "illegal addition", "unpermitted work"
- **Code violation signals:** "code violation", "red tag", "condemned", "stop work"
- **Renovation/permit signals:** "permit", "permitted", "approved plans", "permit filed"

Returns: `permit_risk` = `"high"` / `"low"` / `"unknown"`

**Tier 2 (V1 limited — County portal scraping):** Has a registry of 4 major counties (Dallas, Harris, Maricopa, Tarrant) with known public permit portals. Most use **Accela** which requires interactive browser sessions (CAPTCHA, JavaScript forms) that simple HTTP scraping can't handle. For V1, this returns a "requires browser" status and the permit analysis relies on the keyword inference.

**Status:** ✅ Keyword inference works. ⚠️ County portal scraping is limited for V1.

---

## 5. Brain Classifier (`enrichment/brain.py`)

**What it is:** A keyword/regex-based property classifier — no LLM required. It scans the listing description and address for signal words to classify the property's condition and potential.

### Classification Logic (priority-ordered):

| Priority | Classification | Keywords | Impact |
|----------|---------------|----------|--------|
| 1 | `fire_damage` | "fire damage", "smoke damage", "water damage", "burnt", "burned" | → Estimated condition: uninhabitable |
| 2 | `teardown` | "teardown", "land value", "land only", "demolish", "scrape" | → Estimated condition: uninhabitable |
| 3 | `distressed` | "distressed", "as-is", "needs work", "fixer-upper", "handyman special" | → Estimated condition: poor |
| 4 | `vacant` | "vacant", "abandoned", "unoccupied", "boarded up" | → Estimated condition: fair |
| 5 | `luxury` | "luxury", "high-end", "estate", "gourmet kitchen", "marble", "waterfront" | → Estimated condition: excellent |
| 6 | `standard` | (default, no match) | → Estimated condition: good |

Land scans always get `land_only` classification.

### Seller Motivation Detection:

- **High motivation:** "motivated seller", "must sell", "relocation", "divorce", "estate sale", "short sale", "pre-foreclosure", "price reduced"
- **Medium motivation:** "open to offers", "flexible", "offers encouraged"

### Red Flags (penalty signals):
"foundation issues", "structural", "mold", "termites", "roof leak", "electrical", "plumbing", "septic", "code violation", "unpermitted", "lien", "title issue"

### Green Flags (bonus signals):
"renovated", "updated", "new roof", "new hvac", "new windows", "remodeled", "move-in ready", "turnkey", "investment opportunity", "positive cash flow", "tenant occupied"

**Status:** ✅ Fully working. Reliable for the keywords it knows. Misses properties with unusual descriptions.

---

## 6. Comp Engine (`enrichment/comp_engine.py`)

**Purpose:** For every active listing, find comparable sold properties and calculate price deviation.

### Algorithm (per listing):

```
For each active listing:
  1. Start with 3-mile radius filter (bounding box)
  2. Filter by sqft similarity (±30% for residential)
     OR filter by acres similarity (±50% for land)
  3. Calculate median sold price from matching comps
  4. If < 3 comps found → expand radius to 5mi, then 7mi, then 10mi
  5. Calculate:

     price_deviation_pct = ((listing_price - comp_median_price) / comp_median_price) × 100

     Negative value = listing is BELOW median comp price = GOOD DEAL
     Positive value = listing is ABOVE median comp price = OVERPRICED

  Also calculates:
  - comp_median_price_per_sqft
  - comp_median_price_per_acre (for land)
  - comp_count
  - comp_radius_miles (what radius was actually used)
```

**Radius filtering:** Uses a simple bounding box approximation (not great-circle distance):
- 1° latitude ≈ 69 miles
- 1° longitude ≈ 54 miles (at mid-US latitude)
- Good enough for V1; future versions will use Haversine distance

**Status:** ✅ Fully working. The core of the deal-finding logic.

---

## 7. Scoring Formula

Each property receives a **0–100 score** that determines its **lead tier**. Higher score = better deal.

### 7a. Residential Scoring (`scoring/residential_score.py`)

| Signal | Max Points | Weight | How It's Calculated |
|--------|-----------|--------|---------------------|
| **Price Deviation** | 40 pts | 40% | `max(0, min(40, (-deviation_pct / 50) × 40))` — at -50% below median you get 40/40, at +10% you get 0 |
| **Assessor Gap** | 20 pts | 20% | `max(0, min(20, (gap_pct / 30) × 20))` — if listed price is 30% below assessed value, you get 20/20 |
| **Days on Market** | 15 pts | 15% | ≤30 days = 15pts, ≤90 days = 10pts, ≤180 days = 5pts, 180+ = 2pts |
| **Condition** | 15 pts | 15% | Luxury=12, Standard=15, Vacant=10, Distressed=7, Teardown=4, Fire=3 |
| **Flood Penalty** | 10 pts | 10% | Zone X=10 (no penalty), AE=3 (7pt penalty), Unknown=8 (slight penalty) |
| **Permit Risk** | ±3/-5 | modifier | Low=+3, Unknown=0, Medium=-2, High=-5 |

**Example calculation for a HOT lead:**
```
Property: $245,000 | Comp Median: $395,000 | DOM: 45 | Assessed: $350,000 | Zone X | Standard condition

Price Deviation:  (-38% → 40 × (38/50)  = 30.4/40)
Assessor Gap:    ($350k-$245k)/$350k = 30% → 20/20 × (30/30) = 20/20)
DOM Signal:      (45 days → 10/15)
Condition:       (standard → 15/15)
Flood Penalty:   (Zone X → 10/10)
Permit:          (unknown → 0)

Total: 30.4 + 20 + 10 + 15 + 10 + 0 = 85.4 → 🔥 HOT
```

### 7b. Land Scoring (`scoring/land_score.py`)

| Signal | Max Points | How It's Calculated |
|--------|-----------|---------------------|
| **Price/Acre Deviation** | 40 pts | Same formula as residential but against price-per-acre medians |
| **Zoning Bonus** | 20 pts | Buildable zone (R1,R2,C,etc.) = 20, Non-buildable (AG,CONSERVED) = 2, Unknown = 10 |
| **Road Access** | 10 pts | Brain flags mention road access = 10, otherwise = 5 |
| **Utilities** | 10 pts | Brain flags mention utilities = 10, otherwise = 3 |
| **Acreage Premium** | 10 pts | ≤1 acre = 10, ≤5 = 8, ≤10 = 6, ≤40 = 4, 40+ = 2 |
| **Flood Penalty** | 10 pts | Same as residential |

### 7c. Commercial Scoring (`scoring/commercial_score.py`)

| Signal | Max Points | Notes |
|--------|-----------|-------|
| **Price Deviation** | 35 pts | Standard formula |
| **Assessor Gap** | 25 pts | Weighted higher for skyscrapers (gap/20 instead of gap/30) |
| **Cap Rate Estimate** | 20 pts | Keyword-based: 8 base + 2 per signal (rent, NOI, tenant, cash flow), max 20 |
| **Condition** | 10 pts | Scaled down from residential (×10/15) |
| **Flood Penalty** | 10 pts | Same |

### 7d. Lead Tiers

| Tier | Score Range | Display | Meaning |
|------|------------|---------|---------|
| 🔥 **HOT** | 70+ | Red badge, glow effect | Strong deal signal — below comp median + other positive signals |
| 🌡 **WARM** | 50–69.9 | Amber badge | Moderate potential — investigate further |
| ➖ **NEUTRAL** | 35–49.9 | Default | Priced at/near market — no strong edge |
| ⚠ **RISKY** | 20–34.9 | Dim | Below-average signals — likely overpriced or has issues |
| 🚫 **SKIP** | <20 | Hidden | Not worth pursuing |

**Special tier override:** If Brain classifies as `fire_damage` or `teardown`, the tier gets prefixed with `DISTRESSED_` (e.g., `DISTRESSED_HOT`).

**Config (`config.py`):**
```python
TIER_THRESHOLDS = {
    "HOT": 70,
    "WARM": 50,
    "NEUTRAL": 35,
    "RISKY": 20,
    "SKIP": 0,
}
```

---

## 8. Config & Weights

All weights, thresholds, and constants are centralized in `regog/config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `RESIDENTIAL_WEIGHTS` | `{price_deviation: 0.40, dom_signal: 0.15, assessor_gap: 0.20, condition: 0.15, flood_penalty: 0.10}` | Signal weights for residential scoring |
| `LAND_WEIGHTS` | `{price_per_acre_deviation: 0.40, ...}` | Signal weights for land scoring |
| `COMMERCIAL_WEIGHTS` | `{price_deviation: 0.35, assessor_gap: 0.25, cap_rate_estimate: 0.20, ...}` | Signal weights for commercial scoring |
| `COMP_DEFAULTS.radius_miles` | 3 | Initial comp search radius |
| `COMP_DEFAULTS.min_comps_required` | 3 | Minimum comps before expanding radius |
| `COMP_DEFAULTS.max_radius_miles` | 10 | Maximum comp search radius |
| `COMP_DEFAULTS.similar_sqft_pct` | 0.30 | ±30% sqft filter for residential comps |
| `COMP_DEFAULTS.similar_acres_pct` | 0.50 | ±50% acres filter for land comps |
| `RATE_LIMITS.realtor` | 2-5s delay | HomeHarvest rate limiting |
| `RATE_LIMITS.zillow` | 4-9s delay | Playwright Zillow rate limiting |

---

## 9. Data Pipeline Summary

### End-to-end flow for one property:

```
1. RAW DATA (external sources)
   ├── Realtor.com ──────→ 30+ raw fields (HomeHarvest library)
   ├── Zillow (optional) ──→ 20+ raw fields (Playwright stealth)
   └── Sold comps ────────→ 200 sold properties (HomeHarvest)

2. NORMALIZATION
   └── normalize_listing() ──→ 30 standard property fields

3. ENRICHMENT
   ├── enrich_with_assessor_data() ──→ estimated_value, assessed_value, county
   ├── get_flood_zone() ─────────────→ flood_zone code
   └── fetch_permits() ──────────────→ permit_risk, violation flags

4. BRAIN CLASSIFICATION
   └── classify_property() ─────────→ classification, red flags, green flags,
                                       seller motivation, estimated condition

5. COMP ANALYSIS
   └── calculate_comps(property, sold_list) ──→ comp_median_price,
                                                  price_deviation_pct,
                                                  comp_count, radius

6. SCORING
   ├── score_residential() / score_land() / score_commercial()
   └── assign_tier() ──────────────→ 0-100 score + lead tier

7. OUTPUT
   ├── Stored in SQLite (properties table, 50+ columns)
   ├── SSE streamed to web UI in real-time
   ├── Rich terminal table (CLI)
   └── HTML report (static page)
```

### What's being fetched vs blocked:

| Data Point | Source | Fetch Status | Why Blocked |
|-----------|--------|-------------|-------------|
| Address, City, State, ZIP | Realtor.com | ✅ Fetched | — |
| List Price | Realtor.com | ✅ Fetched | — |
| Beds, Baths, Sqft | Realtor.com | ✅ Usually | Some listings omit |
| Year Built | Realtor.com | ✅ Usually | — |
| Days on Market | Realtor.com | ✅ Usually | Some listings omit |
| Lat/Lon | Realtor.com | ✅ Always | — |
| Description | Realtor.com | ✅ Usually | Some listings have no description |
| County | Realtor.com | ⚠️ Sometimes | Not always provided |
| Estimated Value | Realtor.com | ⚠️ Sometimes | Only on some listings |
| Assessed Value | Realtor.com | ⚠️ Sometimes | Only on some listings |
| Price History | Realtor.com | ❌ Blocked | HomeHarvest doesn't return it; Zillow's is locked behind GraphQL |
| Photos | Realtor.com | ⚠️ URL only | HomeHarvest returns URLs but we store them |
| Flood Zone | FEMA API | ✅ Fetched | —, but requires lat/lon |
| Permit Records | County portals | ⚠️ V1 limited | Accela portals require interactive JS |
| Deeper tax data | County assessor | ❌ V2 planned | qPublic scraping not built yet |
| Auction listings | Auction sites | ❌ V2 planned | ToS issues + CAPTCHA |
| Zillow Zestimate | Zillow | ⚠️ JSON method only | Only available via Next.js data extraction |
