"""
Comp Engine — calculates comparable sales (comps) for a property.
Pulls sold listings from the database or scrapers and computes median values.
"""

import logging
import statistics
from typing import Optional
from config import COMP_DEFAULTS

logger = logging.getLogger(__name__)


def calculate_comps(
    property_dict: dict,
    sold_properties: list[dict],
    radius_miles: Optional[float] = None,
    scan_type: Optional[str] = None,
) -> dict:
    """
    Calculate comps for a given property against a list of sold properties.

    CRITICAL: Filters comps by property style (SINGLE_FAMILY, CONDOS, etc.)
    to ensure we're comparing apples-to-apples. A single-family home should
    NOT be compared against condos or townhomes.

    Args:
        property_dict: The target property (needs lat, lon, sqft, acres, style).
        sold_properties: List of sold property dicts to compare against.
        radius_miles: Search radius (default from config).
        scan_type: 'residential', 'land', or 'commercial'.

    Returns:
        dict with comp_median_price, comp_count, comp_price_per_sqft_median,
              comp_price_per_acre_median, price_deviation_pct, comp_radius_miles
    """
    radius = radius_miles or COMP_DEFAULTS["radius_miles"]
    stype = scan_type or property_dict.get("scan_type", "residential")

    target_price = property_dict.get("list_price") or 0
    target_sqft = property_dict.get("sqft")
    target_acres = property_dict.get("acres")
    target_lat = property_dict.get("lat")
    target_lon = property_dict.get("lon")
    target_style = property_dict.get("style", "")

    # Step 1: Filter by property style FIRST (apples-to-apples comparison)
    # Map broad scan types to the actual style(s) we should compare against
    style_map = {
        "SINGLE_FAMILY": ["SINGLE_FAMILY"],
        "CONDOS": ["CONDOS"],
        "TOWNHOMES": ["TOWNHOMES"],
        "MULTI_FAMILY": ["MULTI_FAMILY"],
        "APARTMENT": ["APARTMENT", "MULTI_FAMILY"],
        "LAND": ["LAND"],
        "MOBILE": ["MOBILE", "SINGLE_FAMILY"],
    }

    # Determine which style(s) to match
    matching_styles = style_map.get(target_style.upper(), [])
    if not matching_styles:
        # If style is unknown, fall back to scan_type-based matching
        if stype == "residential":
            matching_styles = ["SINGLE_FAMILY", "CONDOS", "TOWNHOMES", "MULTI_FAMILY"]
        elif stype == "land":
            matching_styles = ["LAND"]
        elif stype == "commercial":
            matching_styles = ["MULTI_FAMILY", "APARTMENT"]
        else:
            matching_styles = []

    # Filter sold properties by matching style
    comps = [c for c in sold_properties if str(c.get("style", "")).upper() in matching_styles]

    # Step 2: Filter by radius
    comps = _filter_by_radius(comps, target_lat, target_lon, radius)

    # Step 3: Further filter by size similarity
    if target_sqft and stype in ("residential", "commercial"):
        sqft_pct = COMP_DEFAULTS["similar_sqft_pct"]
        min_sqft = target_sqft * (1 - sqft_pct)
        max_sqft = target_sqft * (1 + sqft_pct)
        sqft_matched = [c for c in comps if c.get("sqft") and min_sqft <= c["sqft"] <= max_sqft]
        if len(sqft_matched) >= COMP_DEFAULTS["min_comps_required"]:
            comps = sqft_matched
        # else: keep unfiltered by sqft rather than having no comps

    elif stype == "land" and target_acres:
        acres_pct = COMP_DEFAULTS["similar_acres_pct"]
        min_acres = target_acres * (1 - acres_pct)
        max_acres = target_acres * (1 + acres_pct)
        acres_matched = [c for c in comps if c.get("acres") and min_acres <= c["acres"] <= max_acres]
        if len(acres_matched) >= COMP_DEFAULTS["min_comps_required"]:
            comps = acres_matched

    # Step 4: If not enough comps, expand radius
    min_comps = COMP_DEFAULTS["min_comps_required"]
    if len(comps) < min_comps and radius < COMP_DEFAULTS["max_radius_miles"]:
        for expanded_radius in [5, 7, 10]:
            comps = _filter_by_radius(sold_properties, target_lat, target_lon, expanded_radius)
            # Re-apply style filter on expanded set
            comps = [c for c in comps if str(c.get("style", "")).upper() in matching_styles]
            if len(comps) >= min_comps:
                radius = expanded_radius
                break

    # Step 5: Calculate medians
    prices = [c.get("list_price") or c.get("last_sold_price") or 0 for c in comps if (c.get("list_price") or c.get("last_sold_price"))]
    price_per_sqft_list = [c.get("price_per_sqft") or 0 for c in comps if c.get("price_per_sqft")]
    price_per_acre_list = [c.get("price_per_acre") or 0 for c in comps if c.get("price_per_acre")]

    comp_count = len(comps)
    comp_median_price = _median(prices) if prices else None
    comp_ppsf_median = _median(price_per_sqft_list) if price_per_sqft_list else None
    comp_ppa_median = _median(price_per_acre_list) if price_per_acre_list else None

    # Price deviation — negative means below median (good deal)
    price_deviation_pct = None
    if comp_median_price and target_price:
        price_deviation_pct = round(
            ((target_price - comp_median_price) / comp_median_price) * 100, 2
        )

    return {
        "comp_median_price": comp_median_price,
        "comp_count": comp_count,
        "comp_radius_miles": radius,
        "comp_price_per_sqft_median": comp_ppsf_median,
        "comp_price_per_acre_median": comp_ppa_median,
        "price_deviation_pct": price_deviation_pct,
    }


def _filter_by_radius(
    properties: list[dict],
    center_lat: Optional[float],
    center_lon: Optional[float],
    radius_miles: float,
) -> list[dict]:
    """Filter properties by approximate radius using lat/lon."""
    if not center_lat or not center_lon:
        return []

    # Approximate: 1 degree lat ≈ 69 miles, 1 degree lon ≈ 54 miles (at mid-US lat)
    # Simple bounding box filter (not exact great-circle distance — good enough for V1)
    lat_deg = radius_miles / 69.0
    lon_deg = radius_miles / 54.0

    filtered = []
    for p in properties:
        p_lat = p.get("lat")
        p_lon = p.get("lon")
        if p_lat and p_lon:
            if (
                abs(p_lat - center_lat) <= lat_deg
                and abs(p_lon - center_lon) <= lon_deg
            ):
                filtered.append(p)

    return filtered


def _median(values: list[float]) -> Optional[float]:
    """Compute median of a list."""
    if not values:
        return None
    try:
        return round(statistics.median(values), 2)
    except statistics.StatisticsError:
        return None
