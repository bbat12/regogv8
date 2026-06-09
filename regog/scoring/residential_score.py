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
from scoring.utils import assign_tier, apply_comp_fallback, cap_score_if_no_comps, apply_confidence_cap, apply_variance_penalty, score_price_deviation


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

    # 1. Price deviation (40 pts max, -10 to 40 range)
    # Uses percentile-band scoring — how far below median matters
    # Falls back to price_deviation_pct if comp_median_price not available
    list_price = property_dict.get("list_price") or 0
    comp_median = property_dict.get("comp_median_price")
    conf_label = property_dict.get("comp_confidence_label", "HIGH")
    
    # Determine the deviation percentage from best available source
    deviation_pct = None
    if comp_median and list_price > 0:
        deviation_pct = ((float(list_price) - float(comp_median)) / float(comp_median)) * 100
    elif property_dict.get("price_deviation_pct") is not None:
        deviation_pct = float(property_dict["price_deviation_pct"])
    
    if deviation_pct is not None:
        # Percentile band scoring
        if deviation_pct <= -60:
            scores["price_deviation"] = 40.0
        elif deviation_pct <= -50:
            scores["price_deviation"] = 36.0
        elif deviation_pct <= -40:
            scores["price_deviation"] = 32.0
        elif deviation_pct <= -30:
            scores["price_deviation"] = 26.0
        elif deviation_pct <= -20:
            scores["price_deviation"] = 20.0
        elif deviation_pct <= -10:
            scores["price_deviation"] = 13.0
        elif deviation_pct <= -5:
            scores["price_deviation"] = 7.0
        elif deviation_pct <= 0:
            scores["price_deviation"] = 3.0
        elif deviation_pct <= 10:
            scores["price_deviation"] = 0.0
        else:
            scores["price_deviation"] = -5.0
        
        # Apply confidence penalty
        if conf_label == "LOW":
            scores["price_deviation"] *= 0.5
        elif conf_label == "MEDIUM":
            scores["price_deviation"] *= 0.75
    else:
        scores["price_deviation"] = 0.0

    # 2. Days on market (15 pts max, 0 for 180+ days)
    dom = property_dict.get("days_on_market") or 0
    dom_score = 0  # default for 180+ days (was 2, now 0 to enable SKIP)
    # DOM_SCORE_BRACKETS: [(30, 15), (90, 10), (180, 5), (365, 2), (inf, 0)]
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
    # Unknown zone = 0 penalty (Part 1 fix)
    flood_zone = property_dict.get("flood_zone")
    if not flood_zone or flood_zone == "UNKNOWN":
        scores["flood_penalty"] = 0.0
    else:
        scores["flood_penalty"] = FLOOD_SCORES.get(flood_zone, 0)

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

    # Apply comp fallback: when comp_count=0, use estimated_value as proxy
    scores = apply_comp_fallback(property_dict, scores)

    # Apply confidence cap: if comp_confidence_label is LOW/MEDIUM, cap price_deviation
    scores = apply_confidence_cap(property_dict, scores)

    # Apply variance penalty: high-variance comps reduce price signal reliability
    scores = apply_variance_penalty(property_dict, scores)

    # Total (can be negative if severely overpriced)
    total = sum(scores.values())
    total, _ = cap_score_if_no_comps(total, scores)

    # Lead tier
    tier = assign_tier(total)

    # NOTE: DISTRESSED_ prefix removed per Part 3 fix.
    # Brain classification and tier are kept as SEPARATE fields.
    # The tier column stores ONLY the scoring tier (HOT/WARM/NEUTRAL/RISKY/SKIP).
    # The brain_classification column stores the classification separately.

    # Data confidence — HIGH for residential with comp confidence
    # (Will be overridden by comp_confidence from the engine)

    return {
        "scores": scores,
        "total": round(total, 1),
        "tier": tier,
        "data_confidence": "HIGH",
    }


