# REGOG Comp Pipeline — Full Technical Document

> **What you're seeing:** When you click a comp card in the UI ($530k in your case) and Zillow shows "price unknown" with a Zestimate of $515k, it's because the comp URL is generated client-side by constructing a Zillow search URL from the address text — it's *not* a direct link to the scraped data. This document explains every layer of how comps actually work.

---

## High-Level Architecture

```
HomeHarvest (Realtor.com API)     ← Layer 1: Data Source
        ↓
normalize_sold_listing()          ← Layer 2: Sold-specific normalization
        ↓
fetch_sold_comps()                ← Layer 3: Pool fetching (dynamic sizing)
        ↓
calculate_comps()                 ← Layer 4: Comp engine (2D expansion search)
        ↓
score_residential/land/           ← Layer 5: Scoring engine (uses comps)
  commercial_score()
```

---

## Layer 1: Data Source — HomeHarvest

**File:** `regog/scrapers/redfin_scraper.py`

All comparable sales (sold properties) come from the **HomeHarvest** Python library (`homeharvest==0.8.18`), which scrapes **Realtor.com**. There is no API key, no subscription — it's scraping the public website.

### Sold vs For-Sale

HomeHarvest returns different column names depending on `listing_type`:

| For-Sale Columns | Sold Columns |
|---|---|
| `list_price` | `sold_price`, `last_sold_price`, `close_price` |
| `listing_date` | `last_sold_date`, `sold_date`, `close_date` |
| `days_on_market` | `days_on_market` (historical DOM at time of sale) |
| (status = active) | `listing_status` = "sold" |

### Dynamic Comp Pool Sizing

**File:** `regog/config.py` (lines 80-91)

The system sizes the comp pool dynamically based on the number of active listings found:

```python
SOLD_COMPS_BASE = 300          # minimum pool size
SOLD_COMPS_PER_LISTING = 0.15  # 15% of active listing count
SOLD_COMPS_MAX = 2000          # hard cap

def get_comp_pool_size(active_listing_count: int) -> int:
    dynamic_size = int(active_listing_count * SOLD_COMPS_PER_LISTING)
    return max(SOLD_COMPS_BASE, min(dynamic_size, SOLD_COMPS_MAX))
```

Example: 1,000 active listings → `max(300, min(150, 2000))` = **300 comps** fetched.
Example: 10,000 active listings → `max(300, min(1500, 2000))` = **1,500 comps** fetched.

---

## Layer 2: Sold-Specific Normalization

**File:** `regog/scrapers/redfin_scraper.py` — `normalize_sold_listing()`

This function is separate from the for-sale normalizer (`homeharvest_scraper.normalize_listing`) and explicitly handles sold-specific column names.

### Key Mapping Logic

```python
sold_price = num(g("sold_price", "last_sold_price", "close_price", "sale_price", "price", "list_price"))
```

The function tries **6 different key names** in priority order to find the sold price.

### Acreage Derivation

For land parcels, acreage may come from:
1. Direct: `acres`, `acreage`, `lot_size_acres`, `lot_acres`, `total_acres`, etc.
2. Derived: `lot_sqft` / 43,560 (if lot sqft available but no direct acres field)
3. For land: if no sqft but acres available, sqft = acres × 43,560

### Fields Extracted Per Comp

Each normalized sold comp includes ~30 fields, most importantly:

| Field | Source | Used For |
|---|---|---|
| `list_price` | sold_price (mapped) | Median price calculation |
| `last_sold_price` | sold_price (duplicated) | Explicit sold price field |
| `last_sold_date` | sold_date/close_date | Lookback filter, staleness calc |
| `price_per_sqft` | `sold_price / sqft` | PPSF median comp |
| `price_per_acre` | `sold_price / acres` | PPA median comp (land) |
| `lat`/`lon` | latitude/longitude | Haversine distance filter |
| `style` | property_type/home_type | Style-based filtering |
| `sqft` | square_feet/sq_ft | Sqft similarity filter |
| `acres` | acres/lot_sqft/43560 | Acres similarity filter (land) |
| `beds`/`baths` | bedrooms/bathrooms | Bed/bath similarity filter |
| `property_url` | property_url/listing_url | ⚠️ RARELY AVAILABLE for sold listings |
| `listing_status` | Hardcoded "sold" | Status label in UI |

---

## Layer 3: Comp Pool Fetching

**File:** `regog/scrapers/redfin_scraper.py` — `fetch_sold_comps()`

```python
def fetch_sold_comps(location, scan_type="residential", past_days=180, limit=200):
```

### Type Mapping

| scan_type | property_types sent to HomeHarvest |
|---|---|
| `residential` | `["single_family", "mobile"]` |
| `land` | `["land"]` |
| `commercial` | `["multi_family", "apartment", "condos", "townhomes", "duplex_triplex", "farm"]` |

### What Happens

1. Calls `scrape_property(location, listing_type="sold", past_days=180, property_type=..., limit=...)`
2. HomeHarvest returns a pandas DataFrame
3. Each raw row goes through `normalize_sold_listing()`
4. Rows that fail normalization (no sold price) are silently dropped
5. Result is truncated to `limit`

### Known Limitation

HomeHarvest scrapes Realtor.com. **Realtor.com often hides sold prices** on their website unless you're logged in or using their API. HomeHarvest *can* access some sold data, but the coverage is inconsistent:
- Some markets have rich sold data (hundreds of comps)
- Other markets return 0-5 sold listings
- Land sold data is especially sparse

---

## Layer 4: Comp Engine (2D Expansion Search)

**File:** `regog/enrichment/comp_engine.py` — `calculate_comps()`

This is the heart of the system. For **every single active listing**, it searches through the sold comp pool to find comparable properties.

### Step 4a: Property Category & Density Detection

```python
density = get_market_density(zip_code)         # → "urban" | "suburban" | "rural"
category = get_property_category(style)         # → "residential" | "land" | "commercial"
radii = get_comp_radii(property_dict)           # → [tier1, tier2, tier3] in miles
```

**Density** is determined by ZIP code prefix (first 3 digits). See `utils/density.py` for the full lookup table of ~200 ZIP prefixes.

**Category** is determined by property style (SINGLE_FAMILY → residential, LAND → land, MULTI_FAMILY → commercial). High-rise condos (≥5 stories) are reclassified as commercial.

### Step 4b: Radius Tiers

From `config.py`:

| Category | Density | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|---|
| Residential | Urban | 0.25mi | 0.50mi | 0.75mi |
| Residential | Suburban | 0.50mi | 1.00mi | 1.50mi |
| Residential | Rural | 2.00mi | 5.00mi | 10.0mi |
| Land | Urban | 0.50mi | 1.00mi | 2.00mi |
| Land | Suburban | 1.00mi | 3.00mi | 5.00mi |
| Land | Rural | 5.00mi | 10.0mi | 20.0mi |
| Commercial | Urban | 0.50mi | 1.00mi | 1.50mi |
| Commercial | Suburban | 1.00mi | 2.00mi | 3.00mi |
| Commercial | Rural | 3.00mi | 7.00mi | 15.0mi |

### Step 4c: Two-Dimensional Expansion (the key algorithm)

**File:** `regog/enrichment/comp_engine.py` — `find_comps_with_expansion()`

The search expands in **two dimensions**: first radius, then time.

```
MIN_COMPS_REQUIRED = 5  # must find at least 5 comps
```

**Expansion order** (outer loop = time, inner loop = radius):

```
Time\Radius  |  Tier 1  |  Tier 2  |  Tier 3  |  Emergency (r3×2, r3×4, …)
─────────────┼──────────┼──────────┼──────────┼─────────────────────────
180 days     |  ①       |  ②       |  ③       |  → multiplies by 2, 4, 6…
270 days     |  ④       |  ⑤       |  ⑥       |  (same expansion)
365 days     |  ⑦       |  ⑧       |  ⑨       |
540 days     |  ⑩       |  ⑪       |  ⑫       |
730 days     | ⑬        | ⑭        | ⑮        |  100mi cap
```

For each cell, it:
1. Filters the sold pool by **lookback window** (e.g., sold within 180 days)
2. Filters by **haversine distance** from the target property
3. If ≥5 comps found → accepts this tier, stops expanding
4. If <5 comps → tries next radius tier
5. If all radius tiers exhausted → tries next time window, resets to tier 1

**Last resort:** 730 days lookback, 100mi radius, whatever comps exist.

### Step 4d: Style Filtering (Apples-to-Apples)

```python
style_map = {
    "SINGLE_FAMILY": ["SINGLE_FAMILY", "MANUFACTURED", "MOBILE"],
    "CONDOS": ["CONDOS"],
    "TOWNHOMES": ["TOWNHOMES"],
    "MULTI_FAMILY": ["MULTI_FAMILY", "APARTMENT"],
    "LAND": ["LAND"],
    "FARM": ["FARM", "LAND"],
    # ... etc
}
```

Excludes comps of incompatible property types before the expansion search ever starts.

### Step 4e: Acreage Pre-Filter (Land-Only)

For land scans, if the target property has known acreage, the engine first attempts to find comps within ±50% acreage. Only falls back to the all-acreage pool if the acreage-filtered pool can't yield 5 comps even after full 2D expansion.

### Step 4f: Post-Expansion Similarity Filters

After finding enough comps spatially/temporally, the engine applies additional filters:

| Filter | Scan Type | Range | When Applied |
|---|---|---|---|
| Sqft ±30% | Residential, Commercial | ±30% of target sqft | If enough comps remain (≥5) |
| Beds ±1 | Residential | ±1 bedroom | If enough comps remain (≥5) |
| Baths ±1 | Residential | ±1 bathroom | If enough comps remain (≥5) |
| Acres ±50% | Land | ±50% of target acres | If enough comps remain (≥5) |

### Step 4g: Median & Statistics

From the final comp set:

```python
comp_median_price = median(prices)              # Median sold price
comp_ppsf_median = median(price_per_sqft_list)  # Median $/sqft
comp_ppa_median = median(price_per_acre_list)   # Median $/acre (land)

price_deviation_pct = ((target_price - median_price) / median_price) * 100
# Negative = below median (good for buyer)
# Positive = above median (bad for buyer)

# Variance detection
comp_price_range = max(prices) - min(prices)
if comp_price_range / median_price > 0.50:
    comp_variance_high = True  # Prices are highly scattered
```

### Step 4h: Confidence Scoring

```python
conf_float, conf_label = calculate_comp_confidence(comp_count, tier_used, lookback_used)
```

**Penalties:**
| Condition | Penalty |
|---|---|
| Only 1 comp | −0.40 |
| Only 2 comps | −0.35 |
| Tier 2 radius | −0.10 |
| Tier 3 radius | −0.20 |
| Emergency tier (4+) | −0.25 |
| 180-365d lookback | −0.05 |
| 365d+ lookback | −0.15 (staleness penalty) |

**Final label:**
| Confidence | Label |
|---|---|
| ≥ 0.80 | HIGH |
| ≥ 0.50 | MEDIUM |
| < 0.50 | LOW |

### Step 4i: Top 10 Comps for UI Display

The engine selects up to 10 comps from the final set, sorted by **price proximity** to the target property (closest prices first), and attaches:

```python
top_comps.append({
    "address": "...",
    "list_price": sold_price,        # The actual sold price
    "sqft": ...,
    "acres": ...,
    "beds": ...,
    "baths": ...,
    "style": "...",
    "property_url": "...",           # ⚠️ OFTEN EMPTY for sold listings!
    "primary_photo": "...",          # Sometimes available
    "listing_status": "sold",
    "distance_miles": 0.8,
    "last_sold_date": "2024-03-15",
    "last_sold_date_short": "Mar 2024",
})
```

### Step 4j: No Lat/Lon Fallback

If the target property lacks coordinates, comps are impossible (can't calculate distance). Returns all-None comp metadata and an empty `comp_listings` array.

---

## Layer 5: Scoring Engine's Use of Comps

### Residential Score (`scoring/residential_score.py`)

**Price Deviation (40% weight):**
Percentile-band scoring — how far below median comp price:

| Below Median | Points |
|---|---|
| 60%+ below | 40.0 |
| 50-60% below | 36.0 |
| 40-50% below | 32.0 |
| 30-40% below | 26.0 |
| 20-30% below | 20.0 |
| 10-20% below | 13.0 |
| 5-10% below | 7.0 |
| 0-5% below | 3.0 |
| 0-10% above | 0.0 |
| 10%+ above | −5.0 |

**Confidence penalties on the price score:**
- LOW confidence → score × 50%
- MEDIUM confidence → score × 75%

**Variance penalty:** If comp count < 5 AND variance is high, reduce further by 25%.

### Land Score (`scoring/land_score.py`)

Uses **price per acre deviation** instead of total price deviation. Same percentile bands, same confidence penalties, plus:

- **Estimated acreage penalty:** −30% if acreage was estimated (not measured)
- **Acreage comparability check:** If comps are <50% or >200% of target size, reduce price-per-acre score by 50%

### Commercial Score (`scoring/commercial_score.py`)

Same price deviation logic scaled from 40pt max to 35pt max, plus cap rate estimation using GRM method.

### Comp Fallback (`scoring/utils.py` — `apply_comp_fallback()`)

If `comp_count = 0` (no comps found at all):
1. Use `estimated_value` (Zestimate/AVM) as a proxy — compare `list_price` vs `estimated_value`
2. If no estimated value either → flag `_fb_cap_at_risky`, which caps max score at 30 (below NEUTRAL threshold)

---

## Layer 6: UI Rendering — The Clickable Comp URLs

**File:** `web/static/index.html` — `getCompUrl()`

```javascript
function getCompUrl(comp, parentProp) {
    // Sold comps: skip Realtor.com URL (hides sold prices) — use Zillow directly
    const city = (comp.city || parentProp.city || '').replace(/ /g, '-').replace(/,/g, '').toLowerCase();
    const state = (comp.state || parentProp.state || '').toLowerCase();
    const addr = (comp.address || '').replace(/ /g, '-').replace(/,/g, '').toLowerCase();
    if (city && state && addr) {
        return `https://www.zillow.com/homes/${addr}_${city}_${state}_rb/`;
    }
    // Fallback: Google Maps
    const fullAddr = [comp.address, comp.city, comp.state, parentProp.zip].filter(Boolean).join(', ');
    return `https://www.google.com/maps/search/${encodeURIComponent(fullAddr || comp.address || '')}`;
}
```

### Why This Is the Problem You Experienced

1. The `property_url` field from HomeHarvest's sold data is **almost always empty** — Realtor.com does not expose direct URLs for sold properties through the scraper
2. Since `property_url` is empty, the UI falls back to constructing a **Zillow search URL** from the comp's address text
3. When you click this link, Zillow does a text search for that address
4. If Zillow doesn't have a listing page for that specific sold property, it shows "price unknown" and instead displays its algorithmically-estimated **Zestimate** ($515k in your case)

**The Zestimate is NOT the sold price** — it's Zillow's own AVM estimate. The actual sold price used by REGOG's comp engine ($530k) came from HomeHarvest's Realtor.com scraping and is stored in the database. It is correct — the issue is just that the UI link doesn't go to a page that shows it.

---

## Complete Data Flow Example

Here's what happens for a single property during a residential scan of "Dallas, TX":

### Phase 1: Pre-Flight
```
1. REGOG fetches active listings → finds 948 properties
2. Comp pool sized at: max(300, min(948 × 0.15, 2000)) = 300 comps
3. HomeHarvest called: scrape_property("Dallas, TX", listing_type="sold", 
   past_days=180, limit=300)
4. Returns ~300 sold rows → normalize_sold_listing() → ~280 valid comps
```

### Phase 2: Per-Property (runs 948 times)
For one specific house on Marsalis Ave (listed at ~$180k):

```
1. Target: lat=32.71, lon=-96.81, style=SINGLE_FAMILY, zip=75216
2. Density: zip 75216 → "752" → not in urban or rural sets → "suburban"
3. Category: SINGLE_FAMILY → "residential"
4. Radii: [0.50mi, 1.00mi, 1.50mi] (residential/suburban)

5. Filter by style: 280 → 210 single-family comps
6. 2D expansion starts:
   - 180d / 0.50mi → 2 comps (✗ < 5)
   - 180d / 1.00mi → 4 comps (✗ < 5)
   - 180d / 1.50mi → 6 comps (✓ ≥ 5)
   - Accepting tier 2, 180 days

7. Post-filter by sqft (±30%): 6 → 5 comps (still ≥ 5, accept)
8. Post-filter by beds (±1): 5 → 5 comps (still ≥ 5, accept)
9. Post-filter by baths (±1): 5 → 5 comps (still ≥ 5, accept)

10. Final comps: 5 properties, prices [$150k, $165k, $175k, $190k, $210k]
11. Median: $175,000
12. Price deviation: (180,000 - 175,000) / 175,000 = +2.86% (slightly over median)
13. Price deviation score: at-market → 3.0 points

14. Confidence: 5 comps, tier 2, 180d → 1.0 - 0.10(tier2) - 0(time) = 0.90 → "HIGH"
15. No variance → comp_variance_high = false
```

---

## Known Issues & Limitations

### 1. Sold Data Coverage Varies by Market
- High-volume metros (Dallas, Phoenix, Atlanta) → hundreds of comps
- Rural areas → 0-20 comps, often triggering expanded search
- Land sold data is especially sparse

### 2. Comp URLs Lead to Zillow Search, Not the Actual Listing
As described above — the `property_url` field is rarely populated for sold data.

### 3. HomeHarvest is a Scraper, Not an API
- Subject to rate limiting (though less aggressive)
- Can break if Realtor.com changes their HTML structure
- Sold data access may change as Realtor.com updates anti-scraping measures

### 4. Coordinate Dependency
If a property lacks lat/lon, comps are impossible. Approximately 5-10% of listings from HomeHarvest lack coordinates.

### 5. Style Mapping Is Imperfect
HomeHarvest's `style` column can be inconsistent (e.g., "Apartment" vs "CONDO" vs "MULTI_FAMILY"). Mismatched styles reduce the effective comp pool.

### 6. 2D Expansion Can Produce Stale Comps
At the extreme end (tier 4+, 730 days), comps may be 2 years old in a market that has changed significantly. The confidence penalty and staleness penalty handle this, but the scores become less reliable.
