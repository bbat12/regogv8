# REGOG V1 — Real Estate Go/No-Go Scanner
## Complete Build Prompt for Freebuff (Codespaces)

---

## PROJECT OVERVIEW

Build **REGOG** — a nationwide US real estate intelligence scanner that finds undervalued properties automatically using only free, no-API-key methods. It scrapes public listing sites and government data, enriches each listing with assessor records and comps, scores every property using a multi-signal algorithm, and surfaces the hottest leads first in a futuristic terminal + HTML dashboard interface.

**Stack:**
- Python 3.11+
- SQLite (via `sqlite3` + `aiosqlite`)
- `homeharvest` (pip) — Realtor.com scraping, no key needed
- `playwright` + `playwright-stealth` — JS-heavy site browsing
- `beautifulsoup4` + `httpx` — lightweight HTML crawling
- `rich` — terminal UI (tables, progress bars, panels)
- `geopy` — distance calculations for comp radius
- `ollama` (local) or Freebuff's built-in AI brain — property condition classification
- `apscheduler` — scheduled background scans
- `jinja2` — HTML report generation
- `sqlite-utils` — database management CLI

---

## FILE STRUCTURE

```
regog/
├── main.py                  # Entry point, CLI router
├── config.py                # All settings, thresholds, weights
├── db/
│   ├── schema.sql           # Database schema
│   └── database.py          # DB connection + helpers
├── scrapers/
│   ├── __init__.py
│   ├── homeharvest_scraper.py   # Realtor.com via HomeHarvest
│   ├── redfin_scraper.py        # Redfin sold comps
│   ├── zillow_stealth.py        # Playwright-based Zillow scraper
│   ├── assessor_scraper.py      # County assessor HTML crawler
│   ├── fema_scraper.py          # FEMA flood zone via WMS (free)
│   └── permit_scraper.py        # County permit records
├── enrichment/
│   ├── __init__.py
│   ├── comp_engine.py           # Comp calculation + median logic
│   ├── brain.py                 # LLM property classifier
│   └── geocoder.py              # Address → lat/lon (nominatim, free)
├── scoring/
│   ├── __init__.py
│   ├── residential_score.py
│   ├── land_score.py
│   └── commercial_score.py
├── ui/
│   ├── terminal.py              # Rich terminal dashboard
│   ├── report_generator.py      # HTML report output
│   └── templates/
│       └── report.html.j2       # Jinja2 HTML template
├── scheduler/
│   └── scan_scheduler.py        # APScheduler cron jobs
└── requirements.txt
```

---

## DATABASE SCHEMA (db/schema.sql)

```sql
CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT UNIQUE,
    source TEXT,                    -- 'realtor', 'redfin', 'zillow'
    scan_type TEXT,                 -- 'residential', 'land', 'commercial'
    commercial_subtype TEXT,        -- 'multifamily', 'hotel', 'industrial', 'office', 'retail', 'skyscraper', null
    address TEXT,
    city TEXT,
    state TEXT,
    zip TEXT,
    lat REAL,
    lon REAL,
    list_price INTEGER,
    price_per_sqft REAL,
    price_per_acre REAL,
    sqft INTEGER,
    acres REAL,
    beds INTEGER,
    baths REAL,
    year_built INTEGER,
    lot_sqft INTEGER,
    days_on_market INTEGER,
    listing_status TEXT,
    listing_description TEXT,
    price_history TEXT,             -- JSON array
    last_sold_price INTEGER,
    last_sold_date TEXT,
    assessed_value INTEGER,
    assessed_year INTEGER,
    flood_zone TEXT,                -- FEMA zone code
    zoning TEXT,
    permit_flags TEXT,              -- JSON: {unpermitted_additions: bool, recent_permits: [...]}
    brain_classification TEXT,      -- LLM output: 'luxury|standard|distressed|teardown|fire_damage|vacant|land_only'
    brain_red_flags TEXT,           -- JSON array of detected red flag strings
    brain_green_flags TEXT,         -- JSON array of detected opportunity strings
    brain_seller_motivation TEXT,   -- 'high|medium|low'
    comp_median_price INTEGER,
    comp_count INTEGER,
    comp_radius_miles REAL,
    comp_price_per_sqft_median REAL,
    comp_price_per_acre_median REAL,
    score_total REAL,               -- 0-100
    score_price_deviation REAL,
    score_dom_signal REAL,
    score_assessor_gap REAL,
    score_condition REAL,
    score_acreage_value REAL,
    score_flood_penalty REAL,
    lead_tier TEXT,                 -- 'HOT', 'WARM', 'NEUTRAL', 'RISKY', 'SKIP'
    price_deviation_pct REAL,       -- negative = below median (good), positive = above
    first_seen TEXT,
    last_updated TEXT,
    scan_session_id TEXT
);

CREATE TABLE IF NOT EXISTS scan_sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT,
    completed_at TEXT,
    scan_type TEXT,
    search_params TEXT,             -- JSON: {zip, city, state, price_min, price_max, radius}
    properties_found INTEGER,
    hot_leads_found INTEGER
);

CREATE TABLE IF NOT EXISTS price_history_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT,
    recorded_at TEXT,
    price INTEGER,
    days_on_market INTEGER,
    FOREIGN KEY (listing_id) REFERENCES properties(listing_id)
);
```

---

## SCORING ENGINE

### Residential Score (scoring/residential_score.py)

```python
WEIGHTS = {
    'price_deviation':  0.40,   # Biggest signal — how far below median
    'dom_signal':       0.15,   # Days on market anomaly
    'assessor_gap':     0.20,   # Listed vs assessed value gap
    'condition':        0.15,   # Brain classification
    'flood_penalty':    0.10,   # FEMA zone deduction
}

def score_residential(property: dict) -> dict:
    scores = {}
    
    # 1. Price deviation (40 pts max)
    # price_deviation_pct: -50% = 40pts, -20% = 20pts, +10% = 0pts
    dev = property['price_deviation_pct']
    scores['price_deviation'] = max(0, min(40, (-dev / 50) * 40))
    
    # 2. Days on market (15 pts max)
    # 0-30 days = 15pts (fresh), 31-90 = 10pts, 91-180 = 5pts, 180+ = 2pts
    dom = property['days_on_market'] or 0
    if dom <= 30:   scores['dom_signal'] = 15
    elif dom <= 90: scores['dom_signal'] = 10
    elif dom <= 180: scores['dom_signal'] = 5
    else:           scores['dom_signal'] = 2
    
    # 3. Assessor gap (20 pts max)
    # Listed significantly below assessed = opportunity
    assessed = property['assessed_value']
    listed = property['list_price']
    if assessed and listed:
        gap_pct = ((assessed - listed) / assessed) * 100
        scores['assessor_gap'] = max(0, min(20, (gap_pct / 30) * 20))
    else:
        scores['assessor_gap'] = 5  # neutral if missing
    
    # 4. Condition (15 pts max)
    condition_map = {
        'standard': 15, 'luxury': 12, 'vacant': 10,
        'distressed': 7, 'teardown': 4, 'fire_damage': 3
    }
    classification = property.get('brain_classification', 'standard')
    scores['condition'] = condition_map.get(classification, 10)
    
    # 5. Flood penalty (10 pts max — deduction)
    flood_map = {
        'X': 10,    # Minimal risk — no penalty
        'AE': 3,    # High risk — 7pt penalty
        'A': 4,     # High risk
        'VE': 0,    # Coastal extreme — full penalty
        None: 8     # Unknown — slight penalty
    }
    scores['flood_penalty'] = flood_map.get(property.get('flood_zone'), 8)
    
    total = sum(scores.values())
    
    # Lead tier assignment
    if total >= 70:   tier = 'HOT'
    elif total >= 50: tier = 'WARM'
    elif total >= 35: tier = 'NEUTRAL'
    elif total >= 20: tier = 'RISKY'
    else:             tier = 'SKIP'
    
    # Override: distressed/fire_damage always gets RISKY tag added
    if classification in ('fire_damage', 'teardown'):
        tier = 'DISTRESSED_' + tier
    
    return {'scores': scores, 'total': total, 'tier': tier}
```

### Land Score (scoring/land_score.py)

Key differences from residential:
- Primary metric is **price per acre** vs nearby land sales within 5 miles
- Bonus for **buildable zoning** (R1, R2, C, I vs AG/conserved)
- Bonus for **road access** (detected from listing description via brain)
- Bonus for **utilities nearby** (brain signal from description)
- No sqft/beds/baths — irrelevant
- Acreage premium: >10 acres discounted relative to smaller parcels (bulk land is cheaper per acre)

### Commercial Score (scoring/commercial_score.py)

Routes by `commercial_subtype`:
- **multifamily**: price per unit vs nearby apartment sales; cap rate estimate if rent mentioned
- **hotel/motel**: price per room vs regional hotel sales
- **industrial/manufacturing**: price per sqft warehouse vs nearby industrial sales
- **office/retail**: price per sqft vs local commercial comps
- **skyscraper/large mixed**: assessed value gap + price per sqft (comps sparse, weight assessor heavily)

---

## THE BRAIN (enrichment/brain.py)

```python
CLASSIFICATION_PROMPT = """
You are a real estate analyst AI. Analyze this property listing and return a JSON object only.

Property:
Address: {address}
Type: {scan_type}
List Price: ${list_price:,}
Sqft: {sqft}
Year Built: {year_built}
Days on Market: {dom}
Description: {description}

Return ONLY valid JSON, no explanation:
{{
  "classification": "luxury|standard|distressed|teardown|fire_damage|vacant|land_only",
  "confidence": 0.0-1.0,
  "red_flags": ["list of detected problems"],
  "green_flags": ["list of detected opportunities"],
  "seller_motivation": "high|medium|low",
  "motivation_signals": ["estate sale", "as-is", "motivated seller", etc],
  "estimated_condition": "excellent|good|fair|poor|uninhabitable",
  "is_luxury": true/false,
  "notes": "one sentence summary for investor"
}}

Classification rules:
- luxury: high-end finishes, premium location, price >2x area median
- standard: typical residential in average condition
- distressed: major repairs needed, code violations, neglect evident  
- teardown: structure has no salvage value, land value only
- fire_damage: explicit fire/smoke/water damage mentioned
- vacant: property is unoccupied, may be abandoned
- land_only: vacant land, no structure, or structure irrelevant
"""
```

Use Freebuff's built-in AI (via its agent) to call this per listing. Cache results in SQLite by `listing_id` so re-scans skip the LLM call.

---

## SCRAPERS

### HomeHarvest Scraper (scrapers/homeharvest_scraper.py)

```python
from homeharvest import scrape_property

def fetch_listings(location: str, listing_type: str = 'for_sale', 
                   past_days: int = 90, property_type: list = None):
    """
    listing_type: 'for_sale' | 'sold' | 'for_rent' | 'pending'
    property_type: ['single_family','multi_family','land','commercial'] or None for all
    """
    return scrape_property(
        location=location,
        listing_type=listing_type,
        past_days=past_days,
        property_type=property_type
    )

def fetch_sold_comps(lat: float, lon: float, radius_miles: float = 3, 
                     scan_type: str = 'residential') -> list:
    """Pull sold listings near a point for comp calculation."""
    # HomeHarvest accepts city/zip — we geocode to nearest city first
    # then pull sold listings and filter by distance in Python
    ...
```

### Redfin Scraper (scrapers/redfin_scraper.py)

Redfin has semi-public CSV download endpoints:
```
https://www.redfin.com/stingray/api/gis-csv?al=1&market=socal&min_stories=1&num_homes=350&ord=redfin-recommended-asc&page_number=1&sf=1,2,3,5,6,10,11&status=9&uipt=1,2,3,4,5,6&v=8&region_id=&region_type=
```
Parse region parameters from Redfin's URL structure and pull CSV directly — no auth needed. Use this for sold comps as a secondary source.

### Assessor Scraper (scrapers/assessor_scraper.py)

Strategy:
1. Geocode address to county via `geopy` / Nominatim (free)
2. Look up county assessor URL from our built-in county URL registry (JSON file mapping ~3000 US counties to their assessor URLs + scrape patterns)
3. Search by address or APN using `httpx` + `beautifulsoup4`
4. Extract: assessed value, assessment year, owner, tax history, zoning, permit flags
5. For counties using qPublic platform (hundreds of counties share it): unified scraper handles all

### FEMA Flood Scraper (scrapers/fema_scraper.py)

```python
# FEMA National Flood Hazard Layer — free WMS, no auth
FEMA_WMS = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"

def get_flood_zone(lat: float, lon: float) -> str:
    params = {
        'geometry': f'{lon},{lat}',
        'geometryType': 'esriGeometryPoint',
        'spatialRel': 'esriSpatialRelIntersects',
        'outFields': 'FLD_ZONE,ZONE_SUBTY',
        'f': 'json',
        'inSR': '4326',
        'outSR': '4326'
    }
    # Returns flood zone code: X (low), AE/A (high), VE (coastal extreme)
    ...
```

---

## SCAN TYPES & CLI INTERFACE

### Scan modes

```
regog scan residential  --location "Phoenix, AZ" --zip 85001 --price-max 500000
regog scan land         --location "Texas" --acres-min 5 --price-max 200000
regog scan commercial   --location "Chicago, IL" --type multifamily --price-min 1000000
regog leads             --tier HOT --limit 20
regog report            --session-id abc123 --output report.html
regog schedule          --location "Los Angeles, CA" --interval 24h
regog config            --set comp_radius_miles 5
```

### Search parameters (all scan types)

| Param | Description |
|---|---|
| `--location` | City, "City, State", ZIP, county, or state |
| `--price-min` / `--price-max` | Listing price range |
| `--zip` | One or more ZIP codes (comma-separated) |
| `--radius` | Mile radius from city center |
| `--beds-min` | Min bedrooms (residential) |
| `--sqft-min` | Min square footage |
| `--acres-min` / `--acres-max` | Acreage range (land) |
| `--type` | Commercial subtype: multifamily, hotel, industrial, office, retail |
| `--dom-max` | Max days on market |
| `--score-min` | Only show properties above this score |
| `--tier` | HOT, WARM, NEUTRAL, RISKY |
| `--fresh` | Only listings added/updated in last N days |

---

## COMP ENGINE (enrichment/comp_engine.py)

```python
def calculate_comps(property: dict, db_conn, radius_miles: float = 3) -> dict:
    """
    Pull sold comps within radius_miles of property.
    Filters by:
    - Same scan_type (residential/land/commercial)
    - Similar sqft (±30% for residential)
    - Similar acreage (±50% for land)  
    - Sold within last 12 months
    - Min 3 comps required; expands radius if insufficient
    
    Returns:
    - comp_median_price
    - comp_count
    - comp_price_per_sqft_median
    - comp_price_per_acre_median (land)
    - price_deviation_pct: how far listed price is from comp median
    """
    ...

def expand_radius_if_needed(lat, lon, min_comps=3, max_radius=10):
    """Automatically expand search radius until we have enough comps."""
    for radius in [2, 3, 5, 7, 10]:
        comps = fetch_comps_in_radius(lat, lon, radius)
        if len(comps) >= min_comps:
            return comps, radius
    return comps, max_radius  # Return what we have even if sparse
```

---

## TERMINAL UI (ui/terminal.py)

Use `rich` library. Design: dark terminal, red/crimson accents on borders and headers.

```python
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

REGOG_BANNER = """
██████╗ ███████╗ ██████╗  ██████╗  ██████╗ 
██╔══██╗██╔════╝██╔════╝ ██╔═══██╗██╔════╝ 
██████╔╝█████╗  ██║  ███╗██║   ██║██║  ███╗
██╔══██╗██╔══╝  ██║   ██║██║   ██║██║   ██║
██║  ██║███████╗╚██████╔╝╚██████╔╝╚██████╔╝
╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝  ╚═════╝
Real Estate Go / No-Go Scanner  |  v1.0
"""

def render_leads_table(properties: list):
    table = Table(
        box=box.HEAVY_HEAD,
        border_style="red",
        header_style="bold red",
        show_lines=True
    )
    table.add_column("TIER", width=12)
    table.add_column("SCORE", width=8)
    table.add_column("ADDRESS", width=35)
    table.add_column("PRICE", width=14)
    table.add_column("VS MEDIAN", width=12)
    table.add_column("TYPE", width=14)
    table.add_column("DOM", width=6)
    table.add_column("FLAGS", width=30)
    ...
```

Tier color coding in terminal:
- 🔥 HOT → bold red
- 🌡 WARM → bold yellow  
- ⚪ NEUTRAL → white
- ⚠️ RISKY → bold magenta
- 💀 SKIP → dim gray

---

## HTML REPORT AESTHETICS

The HTML report (`ui/templates/report.html.j2`) must match the terminal aesthetic:

- Background: `#0a0a0f` (near-black with slight blue tint)
- Primary accent: `#ff2233` (glowing red)
- Secondary accent: `#cc0018` (deeper red)
- Surface cards: `#111118` with `1px solid #ff223344` border
- Glow effect on HOT leads: `box-shadow: 0 0 18px #ff223366`
- Text: `#e8e8f0` (off-white, readable on dark)
- Muted text: `#888899`
- Input fields: `#1a1a22` background, `#ff2233` border on focus, `#ffffff` text
- Buttons: `#ff2233` background, `#ffffff` text, `#ff4455` on hover
- Font: `'Orbitron'` (Google Fonts) for headings — futuristic/spaceship feel
- Font: `'Inter'` for body text — clean and legible
- All data values in `#ff4466` (bright red-pink — readable on dark)
- All labels in `#aaaacc` (muted lavender — distinct from values)
- HOT badge: red glow pill
- WARM badge: amber pill
- DISTRESSED badge: magenta pulse animation

---

## ANTI-BOT / RATE LIMITING STRATEGY

```python
RATE_LIMITS = {
    'realtor': {'delay_min': 2, 'delay_max': 5, 'max_per_hour': 200},
    'redfin':  {'delay_min': 1, 'delay_max': 3, 'max_per_hour': 300},
    'zillow':  {'delay_min': 4, 'delay_max': 9, 'max_per_hour': 60},
    'assessor':{'delay_min': 3, 'delay_max': 8, 'max_per_hour': 100},
}

USER_AGENTS = [
    # Rotate through 10+ real Chrome/Firefox user agents
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...",
    ...
]

# Playwright stealth: randomize viewport, timezone, language headers
# Never scrape same domain twice within min delay window
# Exponential backoff on 429/503 responses
# Respect robots.txt — skip disallowed paths
```

---

## SCHEDULER (scheduler/scan_scheduler.py)

```python
from apscheduler.schedulers.background import BackgroundScheduler

# Example: scan LA every 24 hours, alert on new HOT leads
scheduler.add_job(
    run_scan,
    'interval',
    hours=24,
    kwargs={'location': 'Los Angeles, CA', 'scan_type': 'residential'},
    id='la_residential_daily'
)
```

New HOT leads since last scan → printed to terminal on next launch.

---

## INSTALL & SETUP (for Codespaces)

```bash
# 1. Install Freebuff
npm install -g freebuff

# 2. Clone / init project
mkdir regog && cd regog
freebuff init  # Let Freebuff scaffold based on this prompt

# 3. Install Python deps
pip install homeharvest playwright playwright-stealth beautifulsoup4 \
            httpx rich geopy apscheduler jinja2 sqlite-utils aiosqlite

# 4. Install Playwright browsers
playwright install chromium

# 5. Initialize DB
python -c "from db.database import init_db; init_db()"

# 6. Run first scan
python main.py scan residential --location "Dallas, TX" --price-max 400000
```

---

## V1 SUCCESS CRITERIA

- [ ] Can search by city, ZIP, price range for all 3 scan types
- [ ] Pulls listings from at least 2 sources (Realtor + Redfin)
- [ ] Calculates comp median from sold data within configurable radius
- [ ] Scores every property 0-100 with tier assignment
- [ ] Brain classifies property condition from listing description
- [ ] Assessor data pulled for at least qPublic counties (~800+ US counties)
- [ ] FEMA flood zone appended to every property
- [ ] Terminal dashboard shows sorted hot leads with color coding
- [ ] HTML report generated per scan session
- [ ] SQLite stores all data; re-scans update without duplicating
- [ ] Rate limiting prevents bans across all sources

---

*REGOG V1 — Built with Freebuff on GitHub Codespaces*
*All data sources: public, free, no API keys required*
