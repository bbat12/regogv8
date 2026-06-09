# REGOG V5 Scoring Fixes — Build Instructions

If this agent (Codebuff) loses context due to codespace disconnection, here's what was being done:

## Context
- Project: REGOG (Real Estate Go/No-Go Scanner) at `/workspaces/REgog`
- A board meeting analyzed 14,813 properties across 69 scan sessions
- Board agreed on 8 critical/high-priority fixes (documented in `REGOG_Board_Meeting_Q2_2026.md`)
- Build instructions for the fixes are in this file

## Fix Parts (execute in order)

There are 7 fix parts to execute. Each part should be committed after completion with `git add -A && git commit -m "regog: part X — description"`.

### Part 1 — Fix FEMA Flood Zone (CRITICAL)
**Files to modify:**
- `regog/scrapers/fema_scraper.py` — Rewrite with simpler NFHL API query format
- `regog/config.py` — Change FLOOD_SCORES[None] from 8 to 0 (unknown = no penalty)
- Or create a `score_flood()` function that returns 0 for unknown zones

The FEMA NFHL API endpoint: `https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query`
Query params: `geometry={lon},{lat}`, `geometryType=esriGeometryPoint`, `spatialRel=esriSpatialRelIntersects`, `outFields=FLD_ZONE,ZONE_SUBTY,SFHA_TF`, `returnGeometry=false`, `f=json`

### Part 2 — Fix PDev Ceiling Effect (CRITICAL)
**Files to modify:**
- Create percentile band scoring function in `regog/scoring/utils.py`
- Update `regog/scoring/residential_score.py` to use it
- Update `regog/scoring/commercial_score.py` to use it
- Update `regog/scoring/land_score.py` to use percentile bands

### Part 3 — Fix DISTRESSED_ Tier Prefix Bug (CRITICAL)
**Files to modify:**
- `regog/scoring/residential_score.py` — Remove tier concatenation
- `regog/scoring/commercial_score.py` — Remove tier concatenation
- `regog/db/database.py` — Add migration to fix 102 corrupted records
- `regog/ui/terminal.py` — Handle new tier format

### Part 4 — Increase Sold Comp Pool Size (HIGH PRIORITY)
**Files to modify:**
- `regog/config.py` — Add SOLD_COMPS_BASE, SOLD_COMPS_PER_LISTING, SOLD_COMPS_MAX
- `regog/main.py` — Update fetch_sold_comps call to use dynamic pool size

### Part 5 — Fix Land Scoring Flatline (HIGH PRIORITY)
**Files to modify:**
- `regog/scoring/land_score.py` — Add per-acre price deviation, assessor gap fallback

### Part 6 — Add Commercial Cap Rate Estimation (HIGH PRIORITY)
**Files to modify:**
- `regog/scoring/commercial_score.py` — Replace _estimate_cap_rate with real GRM-based estimator

### Part 7 — Surface Data Completeness in UI
**Files to modify:**
- `regog/scoring/utils.py` — Add get_score_completeness function
- `web/static/index.html` — Show completeness badges in property cards

## Tests
Run tests after all fixes: `cd /workspaces/REgog && python -m pytest tests/ -v`

## Verification
- FEMA API: `python3 -c "from regog.scrapers.fema_scraper import get_flood_zone; print(get_flood_zone(32.7767, -96.7970))"`
- PDev scoring: test with 50% below, 5% below, at market, above market
- Corrupted tiers: `SELECT COUNT(*) FROM properties WHERE lead_tier LIKE '%_%HOT'`
- Land scoring: run scan for Billings, MT — scores should vary
- Commercial: run scan for Chicago, IL — should show cap rate estimates

## Current Status
The initial save commit was made. The agent was about to start implementing Part 1.
