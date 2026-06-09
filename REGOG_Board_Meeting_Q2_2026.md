# REGOG Board Meeting — Q2 2026 Data Review

> **Attendees:** 3 Senior Realtors + 2 Senior Developers  
> **Data Reviewed:** 69 scan sessions across 14,813 properties  
> **Categories:** Residential (7,570), Land (1,581), Commercial (5,662)  
> **Markets Scanned:** Dallas, Manhattan, NYC, Atlanta, Panama City (residential); Billings, El Paso, Livingston, Lancaster (land); Chicago, LA, Orlando, Tampa (commercial)

---

## 📊 The Data at a Glance

| Metric | Residential | Land | Commercial | Total |
|--------|:-:|:-:|:-:|:-:|
| **Properties** | 7,570 | 1,581 | 5,662 | **14,813** |
| **HOT leads** | 1,120 (14.8%) | 498 (31.5%) | 133 (2.3%) | **1,751** |
| **WARM leads** | — | — | — | **2,253** |
| **NEUTRAL leads** | — | — | — | **4,413** |
| **RISKY leads** | — | — | — | **6,714** |
| **Avg score** | 41.0 | 45.6 | 36.9 | **40.1** |
| **Avg price** | $862K | $272K | $781K | — |
| **HIGH confidence** | — | — | — | **94.6%** |
| **LOW comp confidence** | — | — | — | **2,231 (15%)** |
| **High comp variance** | — | — | — | **4,681 (32%)** |

---

## 🗣️ The Board Discussion

---

### 🏡 Senior Realtor #1 — Marcus (Residential Specialist)

*"I'm looking at Manhattan residential and something doesn't smell right. I see property after property with **PDev score of 40 out of 40** — that's the max. Market after market, listing after listing, it says every single property is priced 100% below comps. Either we're finding the best deals in the history of Manhattan real estate, or the comp engine is comparing apples to oranges in dense urban markets. **These $585K Manhattan co-ops scoring 78–98 points with zero variance is a bug, not a feature.**"*

*"What I DO like: Dallas residential pulled 3,911 properties with a 37.1 average score, which feels realistic. The Panama City, FL market gave us an $85K property scoring 98 points — that might be a legitimate distressed beach property. But I need the comp engine to tell me *why* it scored 98, not just spit out max values."*

**Top concern:** *"The 0.25-mile comp radius for urban markets is too tight. In Manhattan, a 2-block radius might include properties on completely different street grids with wildly different valuations. We need **neighborhood-aware** comps, not just distance-based."*

**Supporting Data — Manhattan Scoring Anomaly:**

| Price | Score | PDev | DOM | AGap | Cond | Conf |
|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| $1,200,000 | 80.1 | 30.1 | 10.0 | 20.0 | 12.0 | HIGH |
| $735,000 | 70.0 | 40.0 | 10.0 | 0.0 | 12.0 | HIGH |
| $750,000 | 95.0 | 40.0 | 15.0 | 20.0 | 12.0 | HIGH |
| $585,000 | 78.0 | 40.0 | 10.0 | 5.0 | 15.0 | HIGH |
| $1,800,000 | 78.0 | 40.0 | 10.0 | 5.0 | 15.0 | HIGH |

*Nearly every Manhattan HOT lead shows PDev at or near the absolute max of 40, regardless of price point.*

---

### 🏡 Senior Realtor #2 — Priya (Land & Rural Specialist)

*"Let me tell you about the land data because that's where the **real money** is:*

| Market | Properties | HOT | HOT Rate | Avg Score |
|--------|:-:|:-:|:-:|:-:|
| Billings, MT | 90 | 44 | **48.9%** | 59.0 |
| El Paso, TX | 27 | 19 | **70.4%** | 64.1 |
| Livingston, TX | 25 | 19 | **76.0%** | 66.4 |
| Onalaska, TX | 9 | 7 | **77.8%** | 67.1 |
| Dallas, TX | 334 | 35 | 10.5% | 45.3 |
| Lancaster, CA | 388 | 44 | 11.3% | 39.9 |

*These are land opportunities under $100K per lot — the profit potential is enormous."*

*"But here's the problem: **every Billings land HOT lead scores EXACTLY 76.0**. Not 75.9, not 76.1 — exactly 76.0. The system is hitting a scoring ceiling. The price deviation and assessor gap scores are both ZERO for most of these land properties, which means the land scoring model is barely working. It's hitting the max on some components and zero on others, and the total just flatlines."*

**Billings Land — The Flatline:**

| Price | Acres | $/Acre | Score | Tier | Conf |
|:-:|:-:|:-:|:-:|:-:|:-:|
| $24,000 | 0.11 | $212,955 | **76.0** | HOT | MEDIUM |
| $25,000 | 0.12 | $201,613 | **76.0** | HOT | MEDIUM |
| $65,000 | 0.55 | $117,307 | **76.0** | HOT | MEDIUM |
| $72,500 | 0.50 | $144,595 | **76.0** | HOT | MEDIUM |
| $69,000 | 0.59 | $116,005 | **76.0** | HOT | MEDIUM |

*— same score across wildly different price and acreage profiles —*

*"Also — **52% of land properties have no assessed value**. You can't calculate an assessor gap score without assessed values. We need a better assessor data source for vacant land or we need to accept that land scoring is fundamentally different from improved properties."*

---

### 🏡 Senior Realtor #3 — Carlos (Commercial & Multifamily Specialist)

*"The commercial numbers are the **most broken** part of the system. Only 2.3% hit rate for HOT leads compared to 31.5% for land. Either the market has no good commercial deals, or — and I suspect this is the case — **our commercial scoring model is completely off**."*

**Commercial Style Breakdown:**

| Style | Props | Avg Score | HOT | Avg PDev | Avg AGap |
|--------|:-:|:-:|:-:|:-:|:-:|
| MULTI_FAMILY | 2,519 | 39.7 | 56 | 5.5 | 4.4 |
| CONDOS | 1,886 | 34.6 | 16 | 6.0 | 1.8 |
| TOWNHOMES | 913 | 32.2 | 2 | 4.5 | 1.6 |
| MOBILE | 229 | 40.4 | 6 | 5.9 | 6.9 |
| Unknown/Other | 110 | 45.4 | 4 | 12.0 | 2.2 |
| APARTMENT | 5 | 33.9 | 0 | 4.6 | 4.8 |

*"I'm looking at commercial top leads: LA multifamily $499K at 94.7, Chicago multifamily $57,500 at 92.0. These look great on paper. But every single one has **PDev of exactly 35.0 and AGap of exactly 25.0**. That's identical scoring across different cities, different styles, different price points. This is not real analysis — the scoring components hit their caps uniformly and the system isn't distinguishing between a good deal and a great deal."*

**Commercial Top Leads — Suspicious Uniformity:**

| City | Style | Price | Score | PDev | AGap | FP | Conf |
|------|-------|:-:|:-:|:-:|:-:|:-:|:-:|
| Los Angeles, CA | MULTI_FAMILY | $499,000 | 94.7 | 35.0 | 25.0 | 8.0 | HIGH |
| Atlanta, GA | Unknown | $175,000 | 94.0 | 35.0 | 25.0 | 8.0 | — |
| Chicago, IL | MULTI_FAMILY | $57,500 | 92.0 | 35.0 | 25.0 | 8.0 | — |
| Chicago, IL | MULTI_FAMILY | $169,000 | 88.7 | 35.0 | 25.0 | 8.0 | — |
| Chicago, IL | MULTI_FAMILY | $150,000 | 88.5 | 34.9 | 25.0 | 8.0 | — |
| Tampa, FL | MOBILE | $69,500 | 86.2 | 26.2 | 25.0 | 8.0 | HIGH |
| Chicago, IL | MULTI_FAMILY | $59,900 | 86.0 | 35.0 | 25.0 | 8.0 | — |

*"The commercial model is supposed to use **cap rate estimation** (20% weight) but I don't see cap rate data in the output. If we're not computing NOI or cap rates, we're just scoring commercial properties like oversized residential units. We need **NOI, cap rates, GRM, and lease data** to properly evaluate commercial deals."*

---

### 💻 Senior Developer #1 — Dana (Data Pipeline & Quality)

*"I'm going to walk through the **systemic issues** I found in the data pipeline:"*

#### Issue #1 — FEMA Flood Zone: Completely Dead

> **0** properties out of **14,813** have a flood zone populated.  
> **ALL 14,813** have a flood penalty of exactly **8.0** applied.

The default penalty is triggering on every single property because the FEMA scraper is returning nothing. We're deducting 8 points from every scored property for flood risk we never actually checked. This is silently tanking every score by 8 points.

#### Issue #2 — 32% High Comp Variance

> **4,681 properties** (nearly 1 in 3) are flagged as having high comp variance.

Either our comp radius tiers are too loose, our property-type matching is too generous, or the Redfin comp data itself has quality issues. Additionally, **2,231 properties (15%) have LOW comp confidence**.

#### Issue #3 — The DISTRESSED_ Tier Prefix Bug

> **102 properties** have corrupted tier names like `DISTRESSED_HOT`, `DISTRESSED_NEUTRAL`, `DISTRESSED_SKIP`.

The tier labeling logic is concatenating the brain classification prefix with the tier name instead of keeping them separate. This could break any query filtering by tier.

#### Issue #4 — Sold Comps Pool Too Small

> **200 comps shared across 2,700+ properties** in a single Dallas residential scan.

The system fetches up to 200 sold comps per scan session and reuses them for ALL properties in that session. For large metro areas, the initial comp pool is far too small. The comp engine then adjusts by radius and distance, but can't compensate for an inadequate starting pool.

#### Issue #5 — Missing Data by Category

| Category | Missing Sqft | Missing Yr Built | Missing Assessed Value |
|----------|:-:|:-:|:-:|
| **Residential** | 427 (5.6%) | 185 (2.4%) | 537 (7.1%) |
| **Land** | **1,485 (93.9%)** | **1,492 (94.4%)** | **819 (51.8%)** |
| **Commercial** | 1,953 (34.5%) | 164 (2.9%) | 1,022 (18.1%) |

Land properties are effectively missing their primary scoring dimensions. The normalization and scoring engines don't handle this gracefully — they just pass through zeros and nulls.

#### Issue #6 — Listing Filter Nearly Silent

> Only **59 properties filtered** out of ~48,000 processed (0.12%):
> - 51 demolition
> - 6 land_masquerade
> - 2 burned

---

### 💻 Senior Developer #2 — Elena (ML & Scoring Models)

*"I'll address the **scoring model issues**:"*

#### Signal-to-Noise Ratio

| Tier | Properties | % of Total |
|------|:-:|:-:|
| **HOT** | 1,098 | 7.4% |
| **WARM** | 2,253 | 15.2% |
| **NEUTRAL** | 4,413 | 29.8% |
| **RISKY** | 6,714 | **45.3%** |
| **SKIP** | 233 | 1.6% |

NEUTRAL + RISKY = **75% of all properties**. The model isn't confidently classifying most properties — it's clustering them in the indecision zone.

#### The Manhattan Ceiling Effect

> PDev maxes out at 40 for listing after listing.

The price deviation formula likely gives max score whenever list_price < comp_median_price. In Manhattan, where nearly every listing could be below the median paid comp, everything gets max PDev. We need to use percentile-based scoring or tiered deviation bands.

#### Land Flatlining at 76.0

> The land scoring model has 6 components but most properties score 0 on price_per_acre_deviation and assessor_gap while hitting max on bonuses.

The acreage_premium and utilities_bonus may be applying defaults rather than actual data, creating an artificial floor that every property hits regardless of merit.

#### Commercial Missing Its Core Differentiator

> Cap rate estimation is weighted at **20%** but we're not actually computing it.

If cap_rate is always 0 for the estimate, that's 20% of the weight contributing nothing, making the remaining components carry the full load at reduced effective scale. The commercial model becomes a residential model with different labels.

#### Distressed Properties Scoring Surprisingly High

> Distressed commercial properties in Chicago ($169K, $150K, $60K) are scoring HOT (80–88).

These could be legitimate value-add plays, but the scoring model is treating "distressed" as a positive signal in some cases. We need to verify these are real deals, not scoring artifacts.

---

## ✅ The Agreement — 8 Unanimous Board Decisions

After extensive debate, **all 5 board members voted unanimously** on the following priorities:

### 🔴 CRITICAL FIXES (Ship This Week)

| # | Issue | Impact | Fix |
|:-:|-------|--------|-----|
| **1** | **FEMA flood zone dead** | Every property penalized 8 pts for no reason | Fix the scraper, add fallback API, or remove penalty |
| **2** | **Comp confidence ceiling** | Max scores on every urban listing | Switch to percentile-based PDev scoring |
| **3** | **DISTRESSED_ tier prefix bug** | 102 corrupted tier labels | One-line fix in scoring pipeline |

### 🟡 HIGH PRIORITY (Ship This Sprint)

| # | Issue | Impact | Fix |
|:-:|-------|--------|-----|
| **4** | **Sold comp pool too small** | 200 comps for 2,700+ properties | Increase limit proportionally or cluster by region |
| **5** | **Land scoring flatlines at 76.0** | All land leads indistinguishable | Add per-acre deviation, meaningful assessor gaps |
| **6** | **No cap rates in commercial** | 20% weight is dead code | Integrate GRM-based cap rate estimation |

### 📋 ON THE ROADMAP (Next Sprint)

| # | Issue | Impact | Fix |
|:-:|-------|--------|-----|
| **7** | **Data completeness untracked** | High scores on missing data | Surface "score based on N of 5 factors" badge |
| **8** | **Listing filter too narrow** | 0.12% catch rate | Expand patterns, add image-based detection |

---

## 🎯 Immediate Action Items

1. **Dana** to open the FEMA scraper and diagnose why all flood zone lookups return null
2. **Elena** to refactor the price deviation formula to use percentile bands instead of binary below-median scoring
3. **Dana** to fix the DISTRESSED_ tier prefix concatenation
4. **Elena** to rebuild land scoring with per-acre price deviation and proper fallbacks
5. **All** to review the commercial cap rate estimation and source NOI data

> *"For now, **Billings, MT land** and **El Paso, TX land** are the most trustworthy opportunity zones in the current data — high HOT rates, low absolute prices, and actionable leads. But none of us would write a check based on a Manhattan residential score right now."*  
> — *Board Consensus*
