"""
Land Scoring — 0-100 score for vacant land / acreage properties.
"""

from typing import Optional
from config import LAND_WEIGHTS, TIER_THRESHOLDS, FLOOD_SCORES
from scoring.utils import assign_tier, parse_flags, apply_comp_fallback, cap_score_if_no_comps, apply_confidence_cap, apply_variance_penalty


def score_price_per_acre_deviation(prop: dict) -> float:
    """
    Score price per acre deviation using percentile bands.
    
    CRITICAL: If acres is NULL/0, skip this signal entirely.
    Do NOT use total price as proxy for price-per-acre — it produces meaningless deviations.
    
    Uses the same percentile-band scoring as residential:
    - 60%+ below median per-acre → 40 pts
    - 5-10% below → 7 pts
    - At market → 3 pts
    """
    acres = prop.get("acres")
    list_price = prop.get("list_price")
    comp_price_per_acre_median = prop.get("comp_price_per_acre_median")

    # If we don't have real acreage data, skip this signal entirely
    if not acres or float(acres) <= 0:
        return 0.0

    if not list_price or list_price <= 0:
        return 0.0

    # If no comp per-acre median, we can't compute deviation — skip
    if not comp_price_per_acre_median:
        return 0.0

    listing_ppa = float(list_price) / float(acres)
    comp_ppa = float(comp_price_per_acre_median)

    if comp_ppa <= 0:
        return 0.0

    deviation_pct = ((listing_ppa - comp_ppa) / comp_ppa) * 100

    # Percentile band scoring (same bands as residential score_price_deviation)
    conf_label = prop.get("comp_confidence_label", "HIGH")
    acres_estimated = prop.get("acres_estimated", False)

    if deviation_pct <= -60:
        score = 40.0
    elif deviation_pct <= -50:
        score = 36.0
    elif deviation_pct <= -40:
        score = 32.0
    elif deviation_pct <= -30:
        score = 26.0
    elif deviation_pct <= -20:
        score = 20.0
    elif deviation_pct <= -10:
        score = 13.0
    elif deviation_pct <= -5:
        score = 7.0
    elif deviation_pct <= 0:
        score = 3.0
    elif deviation_pct <= 10:
        score = 0.0
    else:
        score = -5.0
    
    # Apply confidence penalty
    if conf_label == "LOW":
        score *= 0.5
    elif conf_label == "MEDIUM":
        score *= 0.75

    # Apply estimated acreage penalty (Part 1 fix):
    # When acreage is estimated (not measured), reduce confidence by 30%
    if acres_estimated:
        score *= 0.70
    
    return max(-10.0, min(40.0, score))


def score_land_assessor_gap(prop: dict) -> float:
    """
    Score gap between list price and assessed value for land.
    Falls back to acreage-based heuristic if no assessed value.
    Max: 20 points.
    """
    list_price = prop.get("list_price")
    assessed_value = prop.get("assessed_value")
    acres = prop.get("acres")

    if assessed_value and assessed_value > 0 and list_price and list_price > 0:
        gap_pct = ((assessed_value - list_price) / assessed_value) * 100
        if gap_pct >= 50:
            return 20.0
        elif gap_pct >= 30:
            return 15.0
        elif gap_pct >= 15:
            return 10.0
        elif gap_pct >= 0:
            return 5.0
        else:
            return 0.0

    # No assessed value — use acreage price heuristic
    if not acres or acres <= 0 or not list_price:
        return 0.0

    price_per_acre = list_price / acres
    if price_per_acre < 5000:
        return 12.0
    elif price_per_acre < 15000:
        return 8.0
    elif price_per_acre < 30000:
        return 4.0
    else:
        return 0.0


def score_zoning(prop: dict) -> float:
    """Score zoning bonus (20 pts max)."""
    zoning = (prop.get("zoning") or "").upper()
    buildable_zones = {"R1", "R2", "R3", "R4", "C", "C1", "C2", "I", "M1", "M2", "PUD"}
    non_buildable_zones = {"AG", "AG1", "A", "CONSERVED", "CONSERVATION", "FLOODWAY", "OS"}

    if any(bz in zoning for bz in buildable_zones):
        return 20.0
    elif any(nbz in zoning for nbz in non_buildable_zones):
        return 2.0
    else:
        return 10.0  # Unknown — assume buildable


def score_road_access(prop: dict) -> float:
    """Score road access (10 pts max).
    Only apply if brain signals explicitly mention road access."""
    brain_flags = parse_flags(prop.get("brain_green_flags"))
    road_keywords = ["road access", "frontage", "paved road", "county road"]
    has_road_access = any(
        kw in (flag.lower() for flag in brain_flags) for kw in road_keywords
    )
    if has_road_access:
        return 10.0
    # No signal = neutral, not assumed
    return 0.0


def score_utilities(prop: dict) -> float:
    """Score utilities bonus (10 pts max).
    Only apply if brain signals explicitly mention utilities."""
    brain_flags = parse_flags(prop.get("brain_green_flags"))
    # Must have actual data — don't assume utilities exist
    if not brain_flags:
        return 0.0
    util_keywords = ["utilities", "power", "water", "sewer", "gas", "electric"]
    has_utilities = any(
        kw in (flag.lower() for flag in brain_flags) for kw in util_keywords
    )
    return 10.0 if has_utilities else 0.0


def score_acreage_premium(prop: dict) -> float:
    """Score acreage premium (10 pts max). Smaller parcels worth more per acre.
    Only applies if acres data is ACTUALLY present, not defaulted."""
    acres = prop.get("acres")
    if acres is None or float(acres) <= 0:
        return 0.0  # No data = no bonus
    acres = float(acres)
    if acres <= 1:
        return 10.0
    elif acres <= 5:
        return 8.0
    elif acres <= 10:
        return 6.0
    elif acres <= 40:
        return 4.0
    else:
        return 2.0


def score_flood(prop: dict) -> float:
    """Score flood penalty (10 pts max — deduction).
    Returns 0 if flood zone is UNKNOWN or None (no data = no penalty)."""
    flood_zone = prop.get("flood_zone")
    if not flood_zone or flood_zone == "UNKNOWN":
        return 0.0  # No data — ZERO penalty (Part 1 fix)
    return float(FLOOD_SCORES.get(flood_zone, 0))


def score_land(property_dict: dict) -> dict:
    """
    Score a land property from 0-100.

    Key metrics:
    - Price per acre vs nearby land sales (within 5 miles)
    - Zoning bonus (buildable = higher score)
    - Road access (from brain signals)
    - Utilities nearby (from brain signals)
    - Acreage premium (>10 acres discounted per unit)
    - Flood penalty
    """
    acres = property_dict.get("acres")
    has_acreage = acres is not None and float(acres) > 0

    price_score = score_price_per_acre_deviation(property_dict)
    zoning_score = score_zoning(property_dict)
    assessor_gap_score = score_land_assessor_gap(property_dict)
    road_score = score_road_access(property_dict)
    utilities_score = score_utilities(property_dict)
    acreage_premium = score_acreage_premium(property_dict) if has_acreage else 0.0
    flood_score = score_flood(property_dict)

    scores = {
        "price_per_acre_deviation": price_score,
        "zoning_bonus": zoning_score,
        "assessor_gap": assessor_gap_score,
        "road_access_bonus": road_score,
        "utilities_bonus": utilities_score,
        "acreage_premium": acreage_premium,
        "flood_penalty": flood_score,
    }

    if not has_acreage:
        # After acreage enrichment, check if we still have no acreage
        # (enrich_acreage may have added an estimate from price heuristic)
        acres_after_enrich = property_dict.get("acres")
        has_acreage_after = acres_after_enrich is not None and float(acres_after_enrich) > 0

        if has_acreage_after:
            # We have estimated acreage — recalculate price_score with the estimate
            # (the acres_estimated flag is already handled inside score_price_per_acre_deviation)
            price_score = score_price_per_acre_deviation(property_dict)
            scores["price_per_acre_deviation"] = price_score
            # Recalculate assessor gap with actual acreage
            assessor_gap_score = score_land_assessor_gap(property_dict)
            scores["assessor_gap"] = assessor_gap_score
            # Flag as estimated on the scores dict
            scores["_fb_acres_estimated"] = True
            # Use estimated acreage — higher score possible but capped
            total = price_score + zoning_score + road_score + utilities_score + acreage_premium + flood_score
            data_confidence = "LOW"
        else:
            # Redistribute the 50% weight (price_per_acre 40% + acreage_premium 10%)
            # across available signals proportionally
            # Zoning 20→33, Road 10→17, Utilities 10→17, Flood 10→17
            # This keeps total < 70 so no HOT leads without acreage data
            total = (
                zoning_score * (33.0 / 20.0) +
                road_score * (17.0 / 10.0) +
                utilities_score * (17.0 / 10.0) +
                flood_score * (17.0 / 10.0)
            )
            data_confidence = "LOW"
    elif price_score == 0 and zoning_score > 0:
        # Has acres but no comp_price_per_acre data — use price_deviation_pct from comp engine
        # (which compares total prices, not per-acre) as a fallback
        # This is acceptable because we DO have acreage data, so we can evaluate whether
        # the total price is reasonable relative to other total prices.
        dev = property_dict.get("price_deviation_pct")
        if dev is not None and float(dev) < 0:
            fallback_price_score = max(0.0, min(40.0, (-float(dev) / 50.0) * 40.0))
            scores["price_deviation"] = fallback_price_score
            total = fallback_price_score + zoning_score + road_score + utilities_score + acreage_premium + flood_score
            data_confidence = "MEDIUM"
        else:
            total = price_score + zoning_score + road_score + utilities_score + acreage_premium + flood_score
            data_confidence = "MEDIUM"
    else:
        total = price_score + zoning_score + road_score + utilities_score + acreage_premium + flood_score
        data_confidence = "HIGH" if price_score > 0 else "MEDIUM"

    # Apply comp fallback: when comp_count=0, use estimated_value as proxy
    # This may modify scores in place (adding price_deviation from estimated_value)
    scores = apply_comp_fallback(property_dict, scores)

    # Apply confidence cap: if comp_confidence_label is LOW/MEDIUM, cap price_deviation
    scores = apply_confidence_cap(property_dict, scores)

    # Apply variance penalty: high-variance comps reduce price signal reliability
    scores = apply_variance_penalty(property_dict, scores)

    # Recalculate total from possibly-updated scores (fallback may have added proxy)
    # Filter out _fb_ metadata keys (strings, booleans) — only numeric score keys
    total = sum(v for k, v in scores.items() if not k.startswith("_fb_"))
    total = min(100.0, max(0.0, round(total, 1)))
    total, _ = cap_score_if_no_comps(total, scores)

    # Lead tier
    tier = assign_tier(total)

    return {
        "scores": scores,
        "total": total,
        "tier": tier,
        "data_confidence": data_confidence,
        "acres_missing": not has_acreage,
    }
