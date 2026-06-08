"""
Land Scoring — 0-100 score for vacant land / acreage properties.
"""

from typing import Optional
from config import LAND_WEIGHTS, TIER_THRESHOLDS, FLOOD_SCORES
from scoring.utils import assign_tier, parse_flags


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
    scores = {}

    # 1. Price per acre deviation (40 pts max)
    ppa_dev = property_dict.get("price_deviation_pct") or 0
    # Negative deviation = below median = good deal
    scores["price_per_acre_deviation"] = max(0, min(40, (-ppa_dev / 50) * 40))

    # 2. Zoning bonus (20 pts max)
    zoning = (property_dict.get("zoning") or "").upper()
    buildable_zones = {"R1", "R2", "R3", "R4", "C", "C1", "C2", "I", "M1", "M2", "PUD"}
    non_buildable_zones = {"AG", "AG1", "A", "CONSERVED", "CONSERVATION", "FLOODWAY", "OS"}

    if any(bz in zoning for bz in buildable_zones):
        scores["zoning_bonus"] = 20
    elif any(nbz in zoning for nbz in non_buildable_zones):
        scores["zoning_bonus"] = 2
    else:
        scores["zoning_bonus"] = 10  # Unknown — assume buildable

    # 3. Road access (10 pts max — from brain green flags)
    brain_flags = parse_flags(property_dict.get("brain_green_flags"))
    road_keywords = ["road access", "frontage", "paved road", "county road"]
    has_road_access = any(
        kw in (flag.lower() for flag in brain_flags) for kw in road_keywords
    )
    scores["road_access_bonus"] = 10 if has_road_access else 5

    # 4. Utilities bonus (10 pts max — from brain green flags)
    # Re-parse brain_flags for utilities check (safe to call twice)
    brain_flags_utils = parse_flags(property_dict.get("brain_green_flags"))
    util_keywords = ["utilities", "power", "water", "sewer", "gas", "electric"]
    has_utilities = any(
        kw in (flag.lower() for flag in brain_flags_utils) for kw in util_keywords
    )
    scores["utilities_bonus"] = 10 if has_utilities else 3

    # 5. Acreage premium (10 pts max)
    # Smaller parcels are worth more per acre; large parcels discounted
    acres = property_dict.get("acres") or 0
    if acres <= 1:
        scores["acreage_premium"] = 10
    elif acres <= 5:
        scores["acreage_premium"] = 8
    elif acres <= 10:
        scores["acreage_premium"] = 6
    elif acres <= 40:
        scores["acreage_premium"] = 4
    else:
        scores["acreage_premium"] = 2

    # 6. Flood penalty (10 pts max — deduction)
    flood_zone = property_dict.get("flood_zone")
    scores["flood_penalty"] = FLOOD_SCORES.get(flood_zone, 8)

    # Total
    total = sum(scores.values())

    # Lead tier
    tier = assign_tier(total)

    return {
        "scores": scores,
        "total": round(total, 1),
        "tier": tier,
    }


