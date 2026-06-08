"""
REGOG Configuration — all settings, thresholds, weights in one place.
"""
from dataclasses import dataclass, field
from typing import Optional

# ─── Database ────────────────────────────────────────────────────────────────
DB_PATH = "regog.db"

# ─── Scoring Weights ─────────────────────────────────────────────────────────
RESIDENTIAL_WEIGHTS = {
    "price_deviation": 0.40,  # How far below median comp price
    "dom_signal": 0.15,       # Days on market anomaly
    "assessor_gap": 0.20,     # Listed vs assessed value gap
    "condition": 0.15,        # Brain classification
    "flood_penalty": 0.10,    # FEMA zone deduction
}

LAND_WEIGHTS = {
    "price_per_acre_deviation": 0.40,
    "zoning_bonus": 0.20,
    "road_access_bonus": 0.10,
    "utilities_bonus": 0.10,
    "acreage_premium": 0.10,
    "flood_penalty": 0.10,
}

COMMERCIAL_WEIGHTS = {
    "price_deviation": 0.35,
    "assessor_gap": 0.25,
    "cap_rate_estimate": 0.20,
    "condition": 0.10,
    "flood_penalty": 0.10,
}

# ─── Lead Tiers (score thresholds) ───────────────────────────────────────────
TIER_THRESHOLDS = {
    "HOT": 70,
    "WARM": 50,
    "NEUTRAL": 35,
    "RISKY": 20,
    "SKIP": 0,
}

# ─── Comp Engine ─────────────────────────────────────────────────────────────
COMP_DEFAULTS = {
    "radius_miles": 3,
    "min_comps_required": 3,
    "max_radius_miles": 10,
    "similar_sqft_pct": 0.30,   # ±30% sqft for residential
    "similar_acres_pct": 0.50,  # ±50% acres for land
    "sold_months": 12,          # look back window
}

# ─── Scan Defaults ───────────────────────────────────────────────────────────
SCAN_DEFAULTS = {
    "past_days": 90,
}

# ─── Rate Limits (seconds between requests) ──────────────────────────────────
RATE_LIMITS = {
    "realtor": {"delay_min": 2, "delay_max": 5, "max_per_hour": 200},
    "redfin": {"delay_min": 1, "delay_max": 3, "max_per_hour": 300},
    "zillow": {"delay_min": 4, "delay_max": 9, "max_per_hour": 60},
    "assessor": {"delay_min": 3, "delay_max": 8, "max_per_hour": 100},
}

# ─── User Agents ─────────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# ─── Brain Classifier Keywords ───────────────────────────────────────────────
CLASSIFICATION_KEYWORDS = {
    "distressed": [
        "distressed", "as-is", "needs work", "needs tlc", "handyman special",
        "fixer-upper", "fixer upper", "deferred maintenance", "repairs needed",
        "needs renovation", "needs repair", "cosmetic issues",
    ],
    "teardown": [
        "teardown", "tear down", "land value", "land only", "buildable lot",
        "scrape", "demolish", "knockdown", "lot for sale",
    ],
    "fire_damage": [
        "fire damage", "smoke damage", "water damage", "burnt", "burned",
        "fire-damaged", "structure fire",
    ],
    "vacant": [
        "vacant", "abandoned", "unoccupied", "boarded up", "vacant lot",
        "vacant property", "no occupants",
    ],
    "luxury": [
        "luxury", "high-end", "high end", "premium", "estate",
        "gourmet kitchen", "marble", "custom built", "architect",
        "panoramic view", "oceanfront", "waterfront",
    ],
}

SELLER_MOTIVATION_KEYWORDS = {
    "high": [
        "motivated seller", "motivated", "priced to sell", "bring all offers",
        "must sell", "relocation", "divorce", "estate sale", "short sale",
        "pre-foreclosure", "bankruptcy", "price reduced", "price reduction",
    ],
    "medium": [
        "open to offers", "flexible", "seller motivated", "offers encouraged",
    ],
}

RED_FLAG_KEYWORDS = [
    "foundation issues", "structural", "mold", "termites", "roof leak",
    "electrical", "plumbing", "septic", "well water", "no heat",
    "no ac", "code violation", "unpermitted", "lien", "title issue",
]

GREEN_FLAG_KEYWORDS = [
    "renovated", "updated", "new roof", "new hvac", "new windows",
    "new kitchen", "new bath", "remodeled", "move-in ready",
    "turnkey", "investment opportunity", "positive cash flow",
    "tenant occupied", "rental", "income producing",
]

# ─── FEMA Flood Zone Scoring ─────────────────────────────────────────────────
FLOOD_SCORES = {
    "X": 10,       # Minimal risk — no penalty
    "AE": 3,       # High risk — 7pt penalty
    "A": 4,        # High risk
    "VE": 0,       # Coastal extreme — full penalty
    None: 8,       # Unknown — slight penalty
}

# ─── Condition Score Map ─────────────────────────────────────────────────────
CONDITION_SCORES = {
    "standard": 15,
    "luxury": 12,
    "vacant": 10,
    "distressed": 7,
    "teardown": 4,
    "fire_damage": 3,
}

# ─── Permit Scoring ─────────────────────────────────────────────────────────
PERMIT_SCORES = {
    "low": 3,         # Permits mentioned → small bonus
    "unknown": 0,     # No signal → neutral
    "medium": -2,     # Possible issues → slight penalty
    "high": -5,       # Unpermitted work/violations → significant penalty
}

# ─── DOM Score Brackets ──────────────────────────────────────────────────────
DOM_SCORE_BRACKETS = [
    (30, 15),     # 0-30 days → 15 pts
    (90, 10),     # 31-90 days → 10 pts
    (180, 5),     # 91-180 days → 5 pts
    (float("inf"), 2),  # 180+ → 2 pts
]
