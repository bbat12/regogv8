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

## Current Status — ALL FIXES COMPLETE

Both sessions of fixes are done. See git log for details.

### Session 1 (Scoring Fixes) — Commits `5ddaf9c`, `f1f23ee`
- Part 1 — FEMA: rewritten with correct NFHL API, unknown zone = 0 penalty
- Part 2 — PDev: percentile band scoring replaces binary below/above
- Part 3 — DISTRESSED_ tier: removed prefix concatenation + DB migration
- Part 4 — Comp pool: base size 200→300, config values added
- Part 5 — Land: assessor gap function, no default bonuses, flatline broken
- Part 6 — Commercial: GRM-based cap rate estimation
- Part 7 — Data completeness: `get_score_completeness()` function added

### Session 2 (UI/Acreage Fixes) — Commits `aecdc02`+
- Part 1 — Land acreage enrichment: created `acreage_enricher.py` with 4 fallback sources (lot_sqft, description parsing, title parsing, price heuristic). Wired into enricher.py. Estimated acreage gets 30% PDev penalty.
- Part 2 — Cap rate in web UI: `buildCapRateSection()` JS function shows est. cap rate, NOI/yr, GRM in 3-column grid. CLI display for HOT/WARM commercial properties.
- Part 3 — Score completeness badge: `renderCompletenessBadge()` + `getScoreCompleteness()` JS functions. Badge shows COMPLETE/PARTIAL/LIMITED DATA with color-coding and missing-factors tooltip.
- Part 4 — Acreage warning: land cards show "Acreage estimated (~Xac)" vs "Acreage unknown" warning based on source.

### What's NOT Done
1. **`web/app.py` background scanner** — still uses `limit=200` for sold comps instead of dynamic pool sizing from config.
2. **`report.html.j2`** — Jinja2 template doesn't show completeness badges or cap rates.
3. **Full dynamic comp pool scaling** — only base size increased (200→300). The `get_comp_pool_size()` function and regional clustering not implemented.
4. **Minor**: card-level acreage display lacks "estimated" qualifier (only shows in expanded detail).

### Key Files (this session)
- `regog/enrichment/acreage_enricher.py` — NEW: acreage fallback enrichment
- `regog/enrichment/enricher.py` — wired acreage enrichment
- `regog/main.py` — completeness + cap rate + CLI details + _print_property_details
- `regog/scoring/land_score.py` — estimated acreage penalty, SKIP→NEUTRAL
- `web/app.py` — completeness in SSE stream, cap rate save/restore
- `web/static/index.html` — completeness badge, cap rate section, acreage warning, JS functions
- `regog/ui/terminal.py` — added COMPS column

### Quick Start for Next Agent
```bash
cd /workspaces/REgog
git log --oneline -10                  # See recent commits
python -m pytest tests/ -v             # Run tests (91/91 pass)
python regog/main.py scan land --location "Billings, MT" --limit 20 --skip-flood  # Test land acreage
python regog/main.py scan residential --location "Dallas, TX" --limit 10 --skip-flood  # Test completeness
python3 serve_report.py                # Start web UI to test cap rate + completeness badges

# Remaining items (if continuing):
# 1. web/app.py — update _run_scan_background comp pool
# 2. regog/ui/templates/report.html.j2 — add completeness + cap rate
# 3. web/static/index.html — add "~" prefix to estimated acreage on card level (minor)
