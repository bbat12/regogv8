"""
Residential Scoring — 0-100 score for residential properties.
"""

from typing import Optional
from config import (
    RESIDENTIAL_WEIGHTS,
    TIER_THRESHOLDS,
    CONDITION_SCORES,
    DOM_SCORE_BRACKETS,
    FLOOD_SCORES,
    PERMIT_SCORES,
)
from scoring.utils import assign_tier


def score_residential(property_dict: dict) -> dict:
    """
    Score a residential property from 0-100.

    Input: property_dict with fields like:
        price_deviation_pct, days_on_market, assessed_value, list_price,
        brain_classification, flood_zone

    Returns dict with:
        scores: dict of component scores
        total: float 0-100
        tier: str
    """
    scores = {}

    # 1. Price deviation (40 pts max)
    # price_deviation_pct: -50% = 40pts, -20% = 20pts, +10% = 0pts
    dev = property_dict.get("price_deviation_pct") or 0
    scores["price_deviation"] = max(0, min(40, (-dev / 50) * 40))

    # 2. Days on market (15 pts max)
    dom = property_dict.get("days_on_market") or 0
    dom_score = 2  # default for 180+
    for threshold, pts in DOM_SCORE_BRACKETS:
        if dom <= threshold:
            dom_score = pts
            break
    scores["dom_signal"] = dom_score

    # 3. Assessor gap (20 pts max)
    assessed = property_dict.get("assessed_value")
    listed = property_dict.get("list_price")
    if assessed and listed and assessed > 0:
        gap_pct = ((assessed - listed) / assessed) * 100
        scores["assessor_gap"] = max(0, min(20, (gap_pct / 30) * 20))
    else:
        scores["assessor_gap"] = 5  # neutral if missing

    # 4. Condition (15 pts max)
    classification = property_dict.get("brain_classification", "standard")
    scores["condition"] = CONDITION_SCORES.get(classification, 10)

    # 5. Flood penalty (0-10 pts — deduction for flood risk)
    flood_zone = property_dict.get("flood_zone")
    scores["flood_penalty"] = FLOOD_SCORES.get(flood_zone, 8)

    # 6. Permit risk modifier (-5 to +3 pts, from permit_flags JSON)
    permit_flags = property_dict.get("permit_flags") or {}
    if isinstance(permit_flags, str):
        import json
        try:
            permit_flags = json.loads(permit_flags)
        except (json.JSONDecodeError, TypeError):
            permit_flags = {}
    permit_risk = permit_flags.get("permit_risk", "unknown")
    scores["permit_risk"] = PERMIT_SCORES.get(permit_risk, 0)

    # Total
    total = sum(scores.values())

    # Lead tier
    tier = assign_tier(total)

    # Override: distressed/fire_damage/teardown always gets DISTRESSED_ prefix
    if classification in ("fire_damage", "teardown"):
        tier = f"DISTRESSED_{tier}"

    return {
        "scores": scores,
        "total": round(total, 1),
        "tier": tier,
    }


