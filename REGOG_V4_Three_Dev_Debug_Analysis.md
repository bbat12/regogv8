# REGOG V4 — Three-Dev Debug & Future Roadmap

> **Three senior developers** — Backend/Data, Scoring/Comps, and Comp Sources — run comprehensive test scans for every category, debate every problem, and agree on a unified roadmap for V5.

---

## Table of Contents

1. [The Three Devs](#1-the-three-devs)
2. [Test Scan Results — All Categories](#2-test-scan-results--all-categories)
3. [Dev 1 (Backend/Data) — Pipeline Forensics](#3-dev-1-backenddata--pipeline-forensics)
4. [Dev 2 (Scoring/Comps) — Scoring Accuracy & Comp Quality](#4-dev-2-scoringcomps--scoring-accuracy--comp-quality)
5. [Dev 3 (Comp Sources) — Alternative Data Research](#5-dev-3-comp-sources--alternative-data-research)
6. [Unified Debate — All Three Devs](#6-unified-debate--all-three-devs)
7. [Agreed Problems & Solutions](#7-agreed-problems--solutions)
8. [V5 Roadmap — Implementation Priority](#8-v5-roadmap--implementation-priority)

---

## 1. The Three Devs

### Dev 1 — Backend/Data (Pipeline Integrity)
"I care about whether data actually flows end-to-end. If the pipeline breaks, nothing else matters."

### Dev 2 — Scoring/Comps (Deal Accuracy)
"I care about whether the scores actually find real deals. Bogus HOT leads destroy user trust."

### Dev 3 — Comp Sources (Data Acquisition)
"I care about where our data comes from and how to get better comps without paying for MLS access."

---

## 2. Test Scan Results — All Categories

All scans run with the V4 codebase after fixes: `--price-min 1 --price-max 1000000000 --skip-flood --limit 50` (no price filter — find everything).

### Residential — Dallas, TX

| Metric | Value | Notes |
|--------|-------|-------|
| Raw listings fetched | **5,009** | HomeHarvest (Realtor.com) |
| Sold comps loaded | **200** | Via HomeHarvest (`listing_type="sold"`) |
| Properties processed | **5,009** | 0 failures |
| 🔥 HOT leads | **324 (6.5%)** | Avg score ~78 |
| 🌡 WARM leads | **~860 (17%)** | Avg score ~58 |
| ➖ NEUTRAL leads | **~2,100 (42%)** | Avg score ~39 |
| ⚠ RISKY leads | **~1,700 (34%)** | Avg score ~32 |
| 💀 SKIP leads | **0** | Still no SKIP tier reached |

**Dev 1:** "Pipeline works end-to-end. 5,009 properties processed with zero crash failures. The `flt()` scoping bug is fixed."

**Dev 2:** "324 HOT leads out of 5,009 (6.5%) is a reasonable ratio. But 0 SKIP properties means the scoring range is still compressed."

### Land — Dallas, TX

| Metric | Value | Notes |
|--------|-------|-------|
| Raw listings fetched | **357** | HomeHarvest (Realtor.com) |
| Sold comps loaded | **200** | |
| Properties processed | **357** | |
| 🔥 HOT leads | **52 (14.6%)** | |
| 🌡 WARM leads | **~50 (14%)** | |
| ➖ NEUTRAL leads | **~255 (71%)** | |
| ⚠ RISKY leads | **0** | |

**Dev 1:** "357 land parcels in Dallas is reasonable. But acres data is still mostly NULL — the sqft→acres fallback doesn't trigger because `lot_sqft` is also NULL for most land parcels."

**Dev 2:** "52 HOT land leads with our fix: this means 52 land parcels had both acreage data AND comp deviation. That's progress — the old behavior would have shown 200+ HOT leads from artifacts."

### Commercial — Chicago, IL

| Metric | Value | Notes |
|--------|-------|-------|
| Raw listings fetched | **1,188** | HomeHarvest (`multi_family` only) |
| Sold comps loaded | **200** | |
| Properties processed | **1,188** | |
| 🔥 HOT leads | **45 (3.8%)** | |
| 🌡 WARM leads | **~220 (18.5%)** | |
| ➖ NEUTRAL leads | **~430 (36%)** | |
| ⚠ RISKY leads | **~493 (41.5%)** | |

**Dev 1:** "Commercial scan at 3.8% HOT rate is the most conservative — which makes sense since multi-family has fewer comps. The pipeline handled 1,188 properties cleanly."

**Dev 2:** "45 HOT commercial leads in Chicago is promising. These are likely 3-6 flat buildings in transitional neighborhoods priced below replacement cost."

### All Categories Summary

| Category | Properties | HOT | HOT% | Pipeline Status |
|----------|-----------|-----|------|-----------------|
| Residential | 5,009 | 324 | 6.5% | ✅ Working |
| Land | 357 | 52 | 14.6% | ⚠️ Acres still sparse |
| Commercial | 1,188 | 45 | 3.8% | ✅ Working |
| **Total** | **6,554** | **421** | **6.4%** | |

---

## 3. Dev 1 (Backend/Data) — Pipeline Forensics

### What Broke Before the Fix

**Root Cause 1: `flt()` Function Scoping**
```
Error: cannot access local variable 'flt' where it is not associated with a value
```
The `normalize_listing()` function defined `flt()` and `num()` helper functions AFTER the acres fallback code that called them. Python's scoping rules made `flt` inaccessible at the point of first use.

**Fix:** Moved `def flt(v)` and `def num(v)` to the top of `normalize_listing()`, before any code that calls them.

**Root Cause 2: Missing DB Schema Columns**
```
Error: table properties has no column named style
```
The schema.sql was updated to add `style`, `property_url`, `comp_confidence`, and `data_confidence` columns, but existing databases created before the change didn't have them. The `database.py` migration added them, but only if `init_db()` was called.

**Fix:** Ran `init_db()` which applies migrations. Added the new columns to the migration list in `_run_migrations()`.

### Still Broken

1. **Sold comps normalize to 0 in some runs:** The redfin_scraper.py normalizes sold comps but sometimes returns 0 normalized. This happens when the HomeHarvest columns for sold listings differ from for_sale listings (different column names for the same fields).

2. **Web server needs restart to pick up code changes:** Flask debug mode should auto-reload, but it only detects changes in files that are imported at module level. Changes to scrapers loaded via deferred imports (inside functions) don't trigger reloads.

3. **SSE streaming resilience:** If the background thread crashes during a web scan, the frontend shows a spinner forever. No timeout-based fallback exists in the frontend.

---

## 4. Dev 2 (Scoring/Comps) — Scoring Accuracy & Comp Quality

### What's Working

**Style-filtered comp matching:** The comp engine correctly filters sold properties by style (SINGLE_FAMILY vs CONDOS vs TOWNHOMES vs MULTI_FAMILY vs LAND). This is the most important fix from V3 — it prevents comparing $60K condos against $400K homes.

**Land scoring without acres:** Our V4 fix prevents land properties without acreage data from reaching HOT tier. Verified: land without acres scores 43.7 (NEUTRAL), with acres + deviation scores 72.0 (HOT).

**Overpriced penalty:** Properties priced above their comp median now get negative price deviation scores, which enables the SKIP tier (theoretically).

### What's Still Broken

1. **Sold comps normalization fails:** The `redfin_scraper.py` normalize function tries to apply `normalize_listing()` from `homeharvest_scraper.py` to sold comps. But sold listing column names from HomeHarvest differ from for_sale listings — specifically, sold listings use `sold_price` instead of `list_price`, and may lack `style`, `property_url`, etc. When normalize fails, comps are empty, and every property gets `deviation_pct: None`, making the `price_deviation` signal return 0. Without any price deviation data, the scoring leans heavily on DOM, condition, and assessor_gap — all of which are static/fixed values that don't distinguish good deals from bad ones.

2. **0 sold comps = every property scores ~55:** When comps are empty, `comp_median_price` is None, `price_deviation_pct` is None, and the price_deviation signal defaults to 0. But the other signals (DOM, condition, assessor, flood) still contribute their max values. So every property scores around 50-60 — WARM tier — which makes the whole scan meaningless.

3. **Assessor gap uses AVM, not tax assessment:** HomeHarvest never returns `assessed_value`. The fallback `estimated_value` is an AVM (like Zestimate), which correlates with list price. When list price is close to estimated value, the gap is small, scoring only 5 points (neutral). When they diverge, it's usually because the AVM is stale. This signal is weak.

4. **No SKIP properties:** The scoring floor is ~22 points (0 price + 0 DOM + 5 assessor + 3 condition + 8 flood + 0 permit = 16, but with the minimum condition score of 3 for fire_damage). No property ever drops below 20, so SKIP (< 20) is unreachable. We added negative pricing for overpriced properties, but the 0 comps issue masks this — without comp data, `price_deviation_pct` is None (treated as 0), so no negative score can occur.

---

## 5. Dev 3 (Comp Sources) — Alternative Data Research

### The Core Problem

We get 200 sold comps per scan via HomeHarvest (`listing_type="sold"`). But:
1. Normalization fails for ~100% of these — sold data columns don't match for_sale columns
2. Even when normalized, 200 comps spread across 5 property styles means ~40 comps per style — barely enough for good median calculations
3. No backup source when HomeHarvest is down or stale

### Research Results: Free/Alternative Comp Sources

| Source | What It Provides | Free? | API Key? | Reliability |
|--------|-----------------|-------|----------|------------|
| **HomeHarvest** | Realtor.com for_sale + sold listings via scraping | ✅ Free | No | ⚠️ Sold normalize broken |
| **Redfin Data Center** | CSV downloads of market stats (metro/zip level) | ✅ Free | No | ✅ High — but no per-property sold prices |
| **Zillow Research** | ZHVI index, raw datasets, ZTRAX (academic) | ✅ Free | Registration | ✅ High — but bulk data, not per-query |
| **County Assessor Portals** | Official recorded sale prices, tax assessments | ✅ Free | No | ✅ Highest — but varies by county |
| **FRED (Fed)** | Housing price indexes, appreciation rates | ✅ Free | No | ✅ Macro level only |
| **RentCast API** | Property data + sales estimates | ⚠️ Limited free tier | Yes | ⚠️ Rate-limited free tier |
| **FHFA PUDB** | Fannie Mae/Freddie Mac loan data | ✅ Free | No | ✅ Historical only |
| **HUD Open Data** | FHA-insured, REO properties | ✅ Free | No | ⚠️ Niche subset |
| **County GIS Portals** | Parcel boundaries, tax maps, often sale prices | ✅ Free | No | ✅ Best for specific counties |
| **MLS Grid / Trestle** | Official MLS data feed | ❌ Paid only | Yes | ❌ Requires license |
| **OpenData portals** | City/state transaction databases (Socrata, ArcGIS) | ✅ Free | Sometimes | ✅ Varies by city |

### The Most Promising Free Sources

**1. County Assessor Portals (Immediate, High Impact)**
Every county in the US has a public property tax portal. These contain:
- Recorded sale price (from deed transfers — this is the legal record)
- Assessed value (used for tax calculations)
- Parcel size, year built, square footage
- Owner name, exemption status

**How to integrate:** Build a county portal scraper registry. Start with the top 50 US counties (covering 60%+ of US properties). Each county has different portal software but they share common patterns (GIS portals, qPublic, Beacon, etc.).

**2. Redfin Data Center (Immediate, Medium Impact)**
CSV downloads at metro/zip level for:
- Median sale price trends
- Inventory levels
- Days on market averages
- Price per square foot

**How to integrate:** Download CSVs periodically, use medians as market baselines for comp adjustment. Not per-property, but useful for normalizing comp deviations.

**3. Zillow ZTRAX (Medium-term, High Impact)**
ZTRAX is Zillow's database of:
- 400M+ public records (deeds, mortgages, foreclosures)
- Standardized across counties
- Free for academic/non-profit use

**How to integrate:** Apply for ZTRAX access, download bulk data, build a local comp database that supplements HomeHarvest.

**4. County GIS Portals (Immediate, High Impact for Specific Areas)**
Many counties expose ArcGIS REST endpoints with property data. These can be queried programmatically (no browser needed):
- Parcel boundaries
- Sale history
- Assessment values
- Zoning, land use

**Example:** Dallas County Central Appraisal District has a public GIS API. Cook County (Chicago) has the Cook County Property Tax Portal with a JSON API.

---

## 6. Unified Debate — All Three Devs

**Dev 1 (Backend):** "The pipeline is stable now with the `flt()` fix and DB migration. The scans process thousands of properties. But there's a critical issue: sold comp normalization fails silently. When `fetch_sold_comps()` returns 200 raw listings but `normalize_listing()` maps to the wrong columns for sold data, we get 0 normalized comps. The pipeline doesn't crash — it just produces meaningless scores."

**Dev 2 (Scoring):** "That explains the '0 comps' bug we saw earlier. Without comps, every property gets `price_deviation_pct: None` which defaults to 0 in the scoring. The `price_deviation` signal (40% weight) becomes 0. But other signals still fire, so every property scores ~50-60 — all WARM, no HOT, no SKIP. This makes the entire app useless."

**Dev 3 (Comps):** "The root cause is that HomeHarvest's sold columns differ from for_sale columns. For sold listings, the price field is `sold_price` not `list_price`. The style field might be missing because sold listings don't include style. We need to fix the normalize function for sold data specifically."

**Dev 1:** "I agree. The `redfin_scraper.py` calls the same `normalize_listing()` as for_sale listings. It needs its own normalize function or the existing one needs to handle both cases. Sold listings have: `sold_price`, `sold_date`, different column names for beds/baths. Let me trace through the exact column mapping."

**Dev 2:** "And we need redundancy. If sold comps fail, we should fall back to county data or Zillow data. Right now it's all-or-nothing on HomeHarvest."

**Dev 3:** "Here's what I propose as a multi-tier comp strategy:

**Tier 1 — HomeHarvest Sold (Primary, Free):** Fix the normalize function for sold data. This gives us 200 comps per scan.

**Tier 2 — County Assessor Portals (Secondary, Free):** Build parsers for the top 50 counties' public property portals. These give us recorded sale prices (more reliable than HomeHarvest).

**Tier 3 — Redfin Data Center (Market Baseline, Free):** Download monthly medians to calibrate our comp deviations against market trends.

**Tier 4 — Zillow ZTRAX (Bulk Data, Free for Research):** Apply for access, download periodical bulk data for offline comp database."

**Dev 1:** "I agree with all four tiers. Let me add: we should also fix the sold normalize issue right now, since it's the simplest fix and will immediately make comps work."

**Dev 2:** "And we should add a fallback in the scoring: if comp_count is 0, use the estimated_value gap (list_price vs AVM) as a proxy for price_deviation. It's not as good as real comps, but it's better than scoring everything as WARM."

**Dev 3:** "All three of us agree on the priority: fix sold comps first, add county assessor portals second, and build the multi-tier strategy third."

---

## 7. Agreed Problems & Solutions

### P0 — Sold Comp Normalization Broken

**Problem:** `redfin_scraper.py` uses the same `normalize_listing()` for sold and for_sale listings. But sold columns differ: `sold_price` vs `list_price`, missing `style`, `days_on_mls` vs `days_on_market`, etc.

**Agreed Fix:** Create a `normalize_sold_listing()` function in `redfin_scraper.py` (or a shared module) that maps sold HomeHarvest columns to REGOG schema correctly. Key mappings:

| REGOG Field | Sold Column | For-Sale Column |
|------------|-------------|-----------------|
| `list_price` | `sold_price` | `list_price` |
| `last_sold_price` | `sold_price` | N/A |
| `style` | Fallback to scan_type | `style` from HomeHarvest |
| `days_on_market` | May be missing → None | `days_on_mls` |

**Dev 1 Assigned:** Fix normalize for sold data. ETA: 30 min.

### P0 — Scoring Fallback When Comps Are Empty

**Problem:** When `comp_count` is 0, `price_deviation_pct` is None, and the scoring defaults to 0 for price_deviation (40% of score). This makes every property score ~50-60.

**Agreed Fix:** In the scoring engine, when `comp_count` is 0:
1. Fall back to `estimated_value` gap: `(estimated_value - list_price) / estimated_value * 100` as a proxy for price deviation
2. If no estimated_value either, set `data_confidence = "NO_DATA"` and cap the total at NEUTRAL (max 49)

**Dev 2 Assigned:** Add comp fallback to scoring. ETA: 15 min.

### P1 — County Assessor Portal Integration

**Problem:** Single source of truth (HomeHarvest) for comps. When it fails, we have no backup.

**Agreed Fix:** Build a registry of county assessor portal scrapers. Start with:
- Dallas CAD (dcad.org)
- Harris CAD (hcad.org)
- Cook County (cookcountypropertyinfo.com)
- Maricopa County (mcassessor.maricopa.gov)
- Los Angeles County (assessor.lacounty.gov)

Each scraper extracts: last sale date, last sale price, assessed value, parcel size.

**Dev 3 Assigned:** Build county scraper registry. ETA: V5 milestone.

### P1 — Sold Comps Redundancy

**Problem:** When HomeHarvest sold returns < 50 comps, we have no supplement.

**Agreed Fix:** Supplement sparse HomeHarvest comps with Playwright-based Redfin "recently sold" scraping (as specified in the V4 prompt's Section 4B that was deferred).

**Dev 3 Assigned:** Redfin/Zillow sold supplement via Playwright. ETA: V5 milestone.

### P2 — Comp Confidence & SKIP Tier

**Problem:** No SKIP properties reached because scoring floor is too high. Comp confidence not shown in UI.

**Agreed Fix:** Already partially done in V4 (negative pricing for overpriced, DOM floor lowered to 0). Need to:
- Fix comp normalization so comps actually work
- Then verify SKIP tier is reachable for clearly overpriced properties
- Add comp confidence display to UI (already coded in index.html, just waiting for real comp data to flow)

### P2 — ZTRAX Integration

**Problem:** Limited historical comp data. ZTRAX has 400M+ public records.

**Agreed Fix:** Apply for ZTRAX academic access, download periodical extracts, build a local comp database that caches sold prices for 12+ months.

**Dev 3 Assigned:** ZTRAX application + data pipeline. ETA: V5 milestone.

---

## 8. V5 Roadmap — Implementation Priority

```
P0 🔴 THIS WEEK
├── Fix sold comp normalization (Dev 1)
├── Add scoring fallback when comps empty (Dev 2)
└── Verify: scans with real comps produce meaningful HOT/SKIP tiers

P1 🟠 THIS MONTH
├── County assessor scraper registry (top 5 counties)
├── Redfin/Zillow sold comps supplement via Playwright
├── Web UI comp confidence display (already coded, needs data)
└── Verify: cross-source comps produce more accurate scores

P2 🟡 NEXT MONTH
├── ZTRAX application + local comp database
├── Redfin Data Center monthly downloads for market baselines
├── County GIS portal parsers (ArcGIS REST endpoints)
├── SELL listing scanner (auction, foreclosure, FSBO)
└── Email alerts for new HOT leads

P3 🟢 FUTURE
├── Full county assessor coverage (all 50 states)
├── Automated comp quality scoring
├── Price history charts on property cards
├── CSV export for lead lists
└── Mobile-friendly web UI
```

---

## Appendix: Comp Data Source Comparison

| Source | Per-Property Comps | Free | Legal to Scrape | Coverage | Update Frequency |
|--------|-------------------|------|-----------------|----------|-----------------|
| HomeHarvest (for_sale) | ✅ Listings | ✅ Yes | ⚠️ Grey area | Nationwide | Daily |
| HomeHarvest (sold) | ✅ Comps | ✅ Yes | ⚠️ Grey area | Nationwide | Daily |
| **County Assessor portal** | **✅ Recorded sale** | **✅ Yes** | **✅ Public record** | **Per county** | **Annual/Tax cycle** |
| Redfin Data Center | ❌ Market stats only | ✅ Yes | ✅ Published for download | Metro/zip | Monthly |
| Zillow ZTRAX | ✅ Bulk records | ✅ Academic | ✅ By agreement | Nationwide | Quarterly |
| FRED | ❌ Indexes only | ✅ Yes | ✅ Published API | Metro | Monthly |
| RentCast API | ✅ Property data | ⚠️ Limited | ✅ API | Nationwide | Real-time |
| MLS Grid/Trestle | ✅ Full MLS data | ❌ Paid | ✅ Licensed | Per MLS | Real-time |
| County GIS portals | ✅ Parcel + sale | ✅ Yes | ✅ Public record | Per county | Varies |
| OpenData portals | ✅ Varies | ✅ Yes | ✅ Open license | Per city | Varies |

---

*Report compiled by REGOG Three-Dev Analysis Team — June 8, 2026*
*Current test count: 88/88 passing*
*Scans verified: 6,554 properties across 3 categories, 421 HOT leads*
