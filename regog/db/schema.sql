-- REGOG Database Schema

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
    estimated_value INTEGER,        -- AVM estimate (Zestimate-like), from HomeHarvest
    assessed_year INTEGER,
    flood_zone TEXT,                -- FEMA zone code
    zoning TEXT,
    permit_flags TEXT,              -- JSON: {unpermitted_additions: bool, recent_permits: [...]}
    brain_classification TEXT,      -- 'luxury', 'standard', 'distressed', 'teardown', 'fire_damage', 'vacant', 'land_only'
    brain_red_flags TEXT,           -- JSON array of detected red flag strings
    brain_green_flags TEXT,         -- JSON array of detected opportunity strings
    brain_seller_motivation TEXT,   -- 'high', 'medium', 'low'
    comp_median_price INTEGER,
    comp_count INTEGER,
    comp_radius_miles REAL,
    comp_price_per_sqft_median REAL,
    comp_price_per_acre_median REAL,
    property_url TEXT,              -- Direct Realtor.com detail URL
    style TEXT,                     -- Property type for comp matching: SINGLE_FAMILY, CONDOS, TOWNHOMES, MULTI_FAMILY, LAND
    comp_confidence TEXT,           -- 'HIGH' | 'MEDIUM' | 'LOW' based on comp count
    score_total REAL,               -- 0-100
    score_price_deviation REAL,
    score_dom_signal REAL,
    score_assessor_gap REAL,
    score_condition REAL,
    score_acreage_value REAL,
    score_flood_penalty REAL,
    lead_tier TEXT,                 -- 'HOT', 'WARM', 'NEUTRAL', 'RISKY', 'SKIP'
    price_deviation_pct REAL,       -- negative = below median (good), positive = above
    data_confidence TEXT,           -- 'HIGH' | 'MEDIUM' | 'LOW' — data quality indicator
    first_seen TEXT,
    last_updated TEXT,
    comp_listings TEXT,             -- JSON array of top comps: [{address, list_price, property_url, ...}]
    comp_lookback_used INTEGER,     -- days of sold history used (180/270/365/540)
    comp_confidence_label TEXT,     -- 'HIGH' | 'MEDIUM' | 'LOW'
    comp_staleness_penalty_applied INTEGER,  -- SQLite boolean: 0 or 1
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

CREATE INDEX IF NOT EXISTS idx_properties_listing_id ON properties(listing_id);
CREATE INDEX IF NOT EXISTS idx_properties_scan_session ON properties(scan_session_id);
CREATE INDEX IF NOT EXISTS idx_properties_tier ON properties(lead_tier);
CREATE INDEX IF NOT EXISTS idx_properties_score ON properties(score_total DESC);
CREATE INDEX IF NOT EXISTS idx_properties_location ON properties(city, state);
