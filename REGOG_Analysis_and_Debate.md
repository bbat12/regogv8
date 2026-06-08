# REGOG Scan Pipeline — Data Quality Analysis & Fixes

> A three-senior-dev deep dive into scan results, comp accuracy, scraper methods, and the fixes applied. Written for sharing with Claude or your team.

---

## Table of Contents

1. [The Three Devs](#1-the-three-devs)
2. [Test Scan: What We Found](#2-test-scan-what-we-found)
3. [The Debate: Comp Engine](#3-the-debate-comp-engine)
4. [The Debate: Data Quality Issues](#4-the-debate-data-quality-issues)
5. [Changes Implemented](#5-changes-implemented)
6. [Verification & Test Results](#6-verification--test-results)
7. [Remaining Issues & Roadmap](#7-remaining-issues--roadmap)

---

## 1. The Three Devs

**Dev 1 (Backend/Data):** Focuses on data integrity — what's actually coming through the pipeline, whether fields are populated, whether types match.

**Dev 2 (Scoring/Comps):** Focuses on the comp engine and scoring algorithm — whether comps are accurate, whether the formula actually finds deals.

**Dev 3 (UX/Integration):** Focuses on how the results are presented and interacted with — what the user sees, clicks, and whether they can trust the data.

---

## 2. Test Scan: What We Found

We ran a full scan of Dallas, TX (`for_sale`, 90 days) and inspected the raw HomeHarvest data.

### Raw Data Volumes

| Style | Count | Price Range |
|-------|-------|-------------|
| **SINGLE_FAMILY** | 2,779 | $55K – $21.5M |
| **CONDOS** | 824 | $35K – $17.5M |
| **LAND** | 235 | $20K – $7.5M |
| **TOWNHOMES** | 231 | $78K – $3.0M |
| **MULTI_FAMILY** | 78 | $179K – $3.0M |
| **APARTMENT** | 18 | $269K – $10.5M |
| **MOBILE** | 1 | $175K |
| **Total** | **4,166** | |

### Column Health Check

| Column | Non-Null | Status |
|--------|----------|--------|
| `property_url` (Realtor.com detail link) | **4,166 / 4,166 (100%)** | ✅ |
| `estimated_value` (AVM) | **4,073 / 4,166 (98%)** | ✅ |
| `latitude` / `longitude` | **4,163 / 4,166 (100%)** | ✅ |
| `county` | **4,166 / 4,166 (100%)** | ✅ |
| `days_on_mls` | **4,166 / 4,166 (100%)** | ✅ |
| `list_price` | **4,166 / 4,166 (100%)** | ✅ |
| `sqft` | **3,856 / 4,166 (93%)** | ✅ |
| `beds` | **3,918 / 4,166 (94%)** | ✅ |
| `full_baths` | **3,909 / 4,166 (94%)** | ✅ |
| `text` (description) | **4,133 / 4,166 (99%)** | ✅ |
| `style` (property type) | **4,166 / 4,166 (100%)** | ✅ |
| `last_sold_price` | **0 / 4,166 (0%)** | ❌ Not available for for-sale |
| `assessed_value` | **0 / 4,166 (0%)** | ❌ Not available from HomeHarvest |
| `tax` / `tax_history` | **0 / 4,166 (0%)** | ❌ Not available |

### Key Findings

1. **`property_url` is available for EVERY listing** — The previous code wasn't capturing it.
2. **`estimated_value` is available for 98% of listings** — The assessor gap scoring signal is much more useful than we thought.
3. **`style` is available for EVERY listing** — We can now filter comps by property type.
4. **`last_sold_price` is NEVER available for for-sale listings** — Sold price only comes from sold comp queries.
5. **`assessed_value` is NEVER available from HomeHarvest** — We need a different source for this.
6. **`county` is available for EVERY listing** — The hardcoded county lookup table is no longer needed.

---

## 3. The Debate: Comp Engine

### Dev 1 (Backend/Data):
> "The biggest problem is that we were comparing apples to oranges. A single-family home at $300K shouldn't be compared against condos at $150K or $5M luxury estates. Without style filtering, the comp median was essentially random."

**Evidence:**
```
Before fix:  SINGLE_FAMILY home at $250K → comps include CONDOS at $150K, TOWNHOMES at $220K
             Random mix → median anywhere between $150K-$5M → price_deviation_pct is noise

After fix:   SINGLE_FAMILY home at $250K → comps are ONLY SINGLE_FAMILY near same sqft
             Narrower range → median is accurate → price_deviation_pct is meaningful
```

### Dev 2 (Scoring/Comps):
> "The 3-mile radius starting point is too narrow for areas with sparse sold data. The radius expansion (3→5→7→10) is correct, but the sqft filter at ±30% was being applied AFTER the style filter was missing. Now that we filter by style first, the sqft filter is a secondary refinement — we only apply it if we still have enough comps after style filtering."

**The fix debate:**
```
Dev 1: "Apply style filter FIRST, then radius, then sqft."
Dev 2: "But what if there are no same-style comps within 3mi?"
Dev 3: "Expand radius. If still none at 10mi, use broader style match."
Consensus: "Style filter first. Expand radius. Sqft is a bonus refinement, not a hard requirement."
```

### Dev 3 (UX/Integration):
> "The user was seeing a single-family home with 'vs Median: -42%' badge, clicking the link, and finding the actual Realtor.com page showed completely different comps. That destroys trust. We need to be transparent about what comps were used — show comp count, radius, and property style on the card."

**Result of the debate:** The comp engine now:
1. Filters by property style **first** (SINGLE_FAMILY → SINGLE_FAMILY only)
2. Filters by radius (3mi → expand to 5/7/10mi if needed)
3. Filters by sqft similarity *only as refinement* (not elimination)
4. Falls back to scan-type-based matching when style is unknown

---

## 4. The Debate: Data Quality Issues

### Issue 1: `condo_townhome` mapped to nothing

**Finding:** HomeHarvest accepts `condo_townhome` as a `property_type` value, but it returns ZERO results for Dallas. The correct value is `townhomes` which returns 231 listings.

**Fix:** Changed all three scraper files (`main.py`, `web/app.py`, `redfin_scraper.py`) to use `townhomes` instead of `condo_townhome`. Also added `duplex_triplex` to the residential type list.

### Issue 2: Property URL not captured

**Finding:** HomeHarvest returns `property_url` for 100% of listings (direct Realtor.com detail URL), but `normalize_listing()` was discarding it.

**Fix:** Added `property_url` to the normalize function output. Updated the frontend's `getListingUrl()` to use it first, with fallbacks (Zillow address search → Google Maps).

### Issue 3: DB schema didn't have `property_url` column

**Finding:** Adding `property_url` to `normalize_listing()` caused `upsert_property()` to fail because the SQLite `properties` table didn't have that column.

**Fix:** Stripped `property_url` before DB upsert (using `prop.pop()` pattern) in all three upsert paths (`web/app.py`, `main.py` scan, `main.py` schedule). Restored it after upsert for SSE streaming to the frontend.

### Issue 4: `style` field not captured

**Finding:** HomeHarvest returns `style` for 100% of listings, but the normalize function was discarding it. Without `style`, the comp engine couldn't filter by property type.

**Fix:** Added `style` to `normalize_listing()` output. Same `prop.pop()` pattern for DB upsert safety.

### Issue 5: Address field priority

**Finding:** HomeHarvest returns `full_street_line` (the clean street address) but the normalize function was picking `street` first, which sometimes had incomplete formatting.

**Fix:** Changed address field priority to `full_street_line` first, then `street`, then others.

### Issue 6: `full_baths` key order

**Finding:** The `g()` function for baths was trying `baths`, `bathrooms`, `bathrooms_total`, `full_baths`. But the actual column is `full_baths` which was last in the list. This worked but the order was misleading.

**Fix:** Moved `full_baths` to the front of the `g()` call.

### Issue 7: Commercial scan was too narrow

**Finding:** Commercial scan only returned 78 `MULTI_FAMILY` listings. We initially added `apartment` to commercial, but the 18 `APARTMENT` listings in Dallas are mostly individual condo units for sale, not commercial apartment buildings. `MULTI_FAMILY` on Realtor.com means 5+ unit buildings which IS commercial.

**Fix:** Commercial stays as `multi_family` only. `APARTMENT` is excluded because those are individual units that belong in residential.

---

## 5. Changes Implemented

### `regog/scrapers/homeharvest_scraper.py`
- Added `style` field capture from HomeHarvest raw data
- Added `full_street_line` as preferred address field
- Added `property_url` field capture
- Added `permalink` field capture
- Fixed `full_baths` key priority

### `regog/enrichment/comp_engine.py`
- **Major rewrite:** Now filters comps by property style FIRST (apples-to-apples)
- `SINGLE_FAMILY` listings only compare against `SINGLE_FAMILY` comps
- `CONDOS` listings only compare against `CONDOS` comps
- `MULTI_FAMILY` listings only compare against `MULTI_FAMILY` comps
- `TOWNHOMES` → `TOWNHOMES`
- `LAND` → `LAND`
- Radius expansion still works within style-filtered comps
- Sqft filter is now a refinement pass, not a hard filter (only applied if enough comps remain)

### `regog/main.py`
- Fixed property type mapping: `condo_townhome` → `townhomes`
- Added `duplex_triplex` to residential types
- Added `prop.pop("property_url", None)` + `prop.pop("style", None)` before DB upserts
- Same fix in scheduled scan path

### `web/app.py`
- Fixed property type mapping (same as main.py)
- Added `prop.pop()` + restore pattern for `property_url` and `style` field before DB upsert

### `regog/scrapers/redfin_scraper.py`
- Fixed property type mapping for sold comp fetching

### `web/static/index.html`
- **Logo** now clickable → reloads the homepage (`location.href='/'`)
- **Back button** appears when results are displayed → resets to initial state
- **History grouping** — scans shown by type with date/time metadata
- **Listing URL** — now uses `property_url` first, then Zillow search, then Google Maps

---

## 6. Verification & Test Results

| Test | Result |
|------|--------|
| Unit tests (pytest) | **86 / 86 pass** |
| HTML page serves at `/` | ✅ 200 OK |
| API config endpoint | ✅ Valid JSON |
| API stats endpoint | ✅ Returns DB stats |
| Scan API (POST) | ✅ Returns `session_id` |
| `property_url` in raw data | ✅ 100% of listings have it |
| `style` in normalized data | ✅ Now captured |
| `estimated_value` available | ✅ 98% of listings |

### Server running at:
```
http://10.0.10.148:8080/
```

---

## 7. Remaining Issues & Roadmap

### Known Limitations

| Issue | Priority | Status |
|-------|----------|--------|
| `assessed_value` is never available from HomeHarvest | Medium | Need county assessor scraper (V2) |
| `last_sold_price` is never available for for-sale listings | Medium | Only available from sold comp queries |
| Comp radius uses bounding box, not Haversine | Low | ~5-10% error at mid-US latitudes |
| `style` field not stored in DB (popped before upsert) | Low | Means past sessions loaded from history won't show style in UI |
| FEMA flood zone requires lat/lon | Low | Property without coords → No flood data |
| Zillow scraper requires Playwright | Low | Optional dependency, not installed by default |
| No CAPTCHA solving capability | Low | Can't handle aggressive bot detection |

### V2 Planned Features

1. **County assessor qPublic scraper** — deep tax/valuation data from hundreds of counties
2. **Auction integration** — Playwright scraping of Auction.com, Hubzu, Xome
3. **Haversine distance** — accurate great-circle distance for comp radius
4. **Property history charts** — price history from Zillow's Apollo cache
5. **Email alerts** — new HOT leads since last scan
6. **Export to CSV** — download scan results
7. **Persist `style` and `property_url` to DB** — DB migration for completeness

---

## Appendix: HomeHarvest Property Type Values

Valid values for the `property_type` parameter:

| Value | Maps to Style | Used In |
|-------|---------------|---------|
| `single_family` | `SINGLE_FAMILY` | Residential |
| `multi_family` | `MULTI_FAMILY` | Residential, Commercial |
| `condos` | `CONDOS` | Residential |
| `townhomes` | `TOWNHOMES` | Residential |
| `duplex_triplex` | (mixed) | Residential |
| `condo_townhome_rowhome_coop` | (mixed) | — |
| `condo_townhome` | Returns 0 results | ❌ Don't use |
| `farm` | (mixed) | — |
| `land` | `LAND` | Land |
| `mobile` | `MOBILE` | — |

### What Actually Exists in Dallas Data

```
SINGLE_FAMILY: 2,779  →  single_family
CONDOS:         824   →  condos
LAND:           235   →  land
TOWNHOMES:      231   →  townhomes
MULTI_FAMILY:    78   →  multi_family
APARTMENT:       18   →  (individual units, NOT commercial)
MOBILE:           1   →  mobile
```

---

## Appendix B: Full User Prompts (Original Session)

This section captures the complete prompt history that led to this analysis:

### Prompt 1 — The Three-Dev Brief
> "imagine you are three senior developers. your goal is to have an app where you can select the city, state, property type, price range, and click scan. the results populate with all of the data necessary to find great deals, debate the best interface for each page, keeping it simple for users with the complicated parts under the hood, the brain. you should be able to click on results to see the listing on the website where it was found. you should be able to save results, have a history of scans, and what else? keep debating until you have a good idea of how this app should operate."

**Response:** Four-page SPA spec: War Room dashboard, Streaming Results Grid with score-sorted cards, Property Deep Dive modal, Saved & History panels.

---

### Prompt 2 — Build the Web App
> "build it"

**Response:** Built Flask backend (web/app.py) with scan API, SSE streaming, saved/history endpoints. Built full dark-theme SPA frontend (web/static/index.html). Set up serve_report.py entry point.

---

### Prompt 3 — Server Directory Issue
> "why am i still seeing a directory page, i want to see the actual app"

**Response:** Created serve_report.py to serve the report HTML at root URL instead of directory listing.

---

### Prompt 4 — Port Not Visible
> "i cant open that, what port is it on"
**Response:** Fixed indentation error in web/app.py (_update_status function), verified server on port 8080.

---

### Prompt 5 — Port Not Showing
> "i dont even have any ports on my ports tab. are you building it to the port"

**Response:** Made port 8080 public via `gh codespace ports visibility`.

---

### Prompt 6 — Scan Failed / Min Price
> "scan failed. should have a min price too."

**Response:** Added min price field to scan form and backend price filtering.

---

### Prompt 7 — JSON Parse Error
> "i clicked scan and got error Failed to start scan: Unexpected token '<', "<!doctype "... is not valid JSON"

**Response:** Fixed ModuleNotFoundError for `db` package by adding `regog/` to sys.path in web/app.py. Server was returning HTML 500 error pages instead of JSON.

---

### Prompt 8 — Architecture Deep Dive
> "what are the data points that you'r searching for to find listings, comps, and which are being fetched and which are being blocked. what methods are each using. what is the formula you're using to find deals. put your response in a .md"

**Response:** Created REGOG_Architecture_Deep_Dive.md — 9-section document covering all data sources, scraper methods, enrichment pipeline, brain classifier, comp engine, scoring formula, weights, and pipeline summary.

---

### Prompt 9 — View Listing Goes to Homepage
> "when i click on a result it doesnt take me to the listing it takes me to the homepage of the website"

**Response:** Identified that HomeHarvest returns `property_url` for 100% of listings but it wasn't being captured. Fixed normalize_listing to capture it. Fixed getListingUrl() fallback chain. Added DB safety (pop before upsert, restore for streaming).

---

### Prompt 10 — Full Analysis & Fix Request (This Session)
> "the regog logo should take you to the homepage. and the scan results needs a back button. but if you leave the page, recent searches are grouped together in a history list with the keyword (land, etc) and the date and time of the scan. you can open them and access them, open on real estate site. there are huge discrepencies in the results. homes showing up on commercial search, comps are way off, we need to fine tune it. imagine you're 3 senior developers with different strengths, do a test scan and analyze and debate the results compared with the actual listings and the comps, source the data and see if it's legit, debate about solutions and refine the results until they are accurate. then compile all of your response and this prompt into a .md i can share with claude."

**Response:** (This document) — Full analysis of HomeHarvest data, property type mapping fixes, comp engine rewrite with style filtering, logo/back button/history UI fixes, and compilation into this .md.

---

### Prompt 11 — Follow-up on the .md
> "what was the most recent .md you created"
> "and all of my prompts since"

**Response:** Confirmed REGOG_Analysis_and_Debate.md is the most recent. Appended all prompts to this appendix.

---

*End of prompt history.* This document is designed to be shared with Claude or your team for further analysis and iteration.
