"""
Comp Engine — calculates comparable sales (comps) for a property.
Pulls sold listings from the database or scrapers and computes median values.

Uses a two-dimensional expansion search: first tries all radius tiers, then
expands the lookback window. After exhausting all combinations, flags the
comp confidence so the UI and scoring engine can adjust accordingly.
"""

import logging
import math
import statistics
from datetime import datetime, timezone
from typing import Optional

from config import (
    COMP_DEFAULTS,
    COMP_RADII,
    COMP_RADII_DEFAULT,
    MIN_COMPS_REQUIRED,
    COMP_LOOKBACK_TIERS,
    COMP_STALENESS_PENALTY,
    COMP_CONFIDENCE_HIGH,
    COMP_CONFIDENCE_MEDIUM,
    COMP_CONFIDENCE_LOW,
)
from utils.density import get_market_density
from utils.property_type import get_property_category

logger = logging.getLogger(__name__)


# ─── Helpers ────────────────────────────────────────────────────────────────

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points in miles."""
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse a date string into a datetime object. Tries common formats."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def _days_since_sold(comp: dict) -> Optional[int]:
    """Calculate how many days ago a comp was sold, based on last_sold_date."""
    date_str = comp.get("last_sold_date") or comp.get("sold_date") or comp.get("close_date")
    sold_date = _parse_date(date_str)
    if sold_date is None:
        return None
    delta = datetime.now(timezone.utc) - sold_date
    return max(0, delta.days)


def _median(values: list[float]) -> Optional[float]:
    """Compute median of a list."""
    if not values:
        return None
    try:
        return round(statistics.median(values), 2)
    except statistics.StatisticsError:
        return None


# ─── Radius / Category Helpers ──────────────────────────────────────────────

def get_comp_radii(prop: dict) -> list[float]:
    """
    Returns [tier1, tier2, tier3] radii in miles based on ZIP density
    and property category.
    """
    zip_code = prop.get("zip") or prop.get("zip_code", "")
    density = get_market_density(zip_code)
    category = get_property_category(prop.get("style"), prop.get("property_type"))
    radii = COMP_RADII.get(category, COMP_RADII_DEFAULT).get(density, COMP_RADII_DEFAULT["suburban"])
    return list(radii)


def _filter_by_distance(
    properties: list[dict],
    center_lat: Optional[float],
    center_lon: Optional[float],
    radius_miles: float,
) -> list[dict]:
    """Filter properties by haversine distance."""
    if not center_lat or not center_lon or radius_miles <= 0:
        return []
    filtered = []
    for p in properties:
        p_lat = p.get("lat")
        p_lon = p.get("lon")
        if p_lat is not None and p_lon is not None:
            dist = haversine_miles(center_lat, center_lon, p_lat, p_lon)
            if dist <= radius_miles:
                filtered.append(p)
    return filtered


def _filter_by_style(properties: list[dict], target_style: str, scan_type: str) -> list[dict]:
    """Filter sold properties by property style (apples-to-apples)."""
    style_map = {
        "SINGLE_FAMILY": ["SINGLE_FAMILY"],
        "CONDOS": ["CONDOS"],
        "TOWNHOMES": ["TOWNHOMES"],
        "MULTI_FAMILY": ["MULTI_FAMILY"],
        "APARTMENT": ["APARTMENT", "MULTI_FAMILY"],
        "LAND": ["LAND"],
        "MOBILE": ["MOBILE", "SINGLE_FAMILY"],
    }
    matching_styles = style_map.get(target_style.upper(), [])
    if not matching_styles:
        if scan_type == "residential":
            matching_styles = ["SINGLE_FAMILY", "CONDOS", "TOWNHOMES", "MULTI_FAMILY"]
        elif scan_type == "land":
            matching_styles = ["LAND"]
        elif scan_type == "commercial":
            matching_styles = ["MULTI_FAMILY", "APARTMENT"]
    return [c for c in properties if str(c.get("style", "")).upper() in matching_styles]


def _filter_by_lookback(properties: list[dict], max_days: int) -> list[dict]:
    """Filter sold properties to those sold within max_days of today."""
    if max_days <= 0:
        return []
    filtered = []
    for p in properties:
        days_sold = _days_since_sold(p)
        if days_sold is not None and days_sold <= max_days:
            filtered.append(p)
        elif days_sold is None:
            # No date available — include it (conservative: assume recent)
            filtered.append(p)
    return filtered


# ─── Confidence Calculation ────────────────────────────────────────────────

def calculate_comp_confidence(
    comp_count: int,
    radius_used: float,
    lookback_used: int,
    radii: list[float],
) -> tuple[float, str]:
    """
    Calculate a numeric confidence score (0.0–1.0) and a label
    ('HIGH', 'MEDIUM', 'LOW') for a set of comp results.

    Applies penalties for:
      - Low comp count (1 comp → -0.40, 2 comps → -0.20)
      - Expanded radius (tier 2 → -0.10, tier 3 → -0.20)
      - Extended time window (>360d → -0.15, >180d → -0.05)

    Args:
        comp_count: Number of comps found.
        radius_used: The radius (miles) that was used.
        lookback_used: The lookback window (days) that was used.
        radii: The three-tier radii list for this property.

    Returns:
        Tuple of (confidence_float, confidence_label).
    """
    if comp_count == 0:
        return 0.0, "LOW"

    confidence = 1.0

    # Penalty for low comp count
    if comp_count == 1:
        confidence -= 0.40
    elif comp_count == 2:
        confidence -= 0.20

    # Penalty for expanded radius
    if radius_used == radii[2] if len(radii) > 2 else False:
        confidence -= 0.20
    elif radius_used == radii[1] if len(radii) > 1 else False:
        confidence -= 0.10

    # Penalty for extended time window
    if lookback_used > 365:
        confidence -= COMP_STALENESS_PENALTY
    elif lookback_used > 180:
        confidence -= 0.05

    confidence = max(0.0, min(1.0, confidence))

    # Assign label
    if confidence >= COMP_CONFIDENCE_HIGH:
        label = "HIGH"
    elif confidence >= COMP_CONFIDENCE_MEDIUM:
        label = "MEDIUM"
    else:
        label = "LOW"

    return confidence, label


# ─── 2D Expansion Search ───────────────────────────────────────────────────

def find_comps_with_expansion(
    style_filtered: list[dict],
    target_lat: float,
    target_lon: float,
    radii: list[float],
) -> tuple[list[dict], float, int, int, bool]:
    """
    Two-dimensional expansion search: radius tiers FIRST, then time windows.

    Tries every combination of radius tier + lookback window until
    MIN_COMPS_REQUIRED is met.

    Expansion order (outer = time, inner = radius):
        180d/r1 → 180d/r2 → 180d/r3 →
        270d/r1 → 270d/r2 → 270d/r3 →
        365d/r1 → 365d/r2 → 365d/r3 →
        540d/r1 → 540d/r2 → 540d/r3

    Args:
        style_filtered: Sold properties pre-filtered by style match.
        target_lat: Target property latitude.
        target_lon: Target property longitude.
        radii: Three-tier radii list [r1, r2, r3].

    Returns:
        Tuple of (comps_list, radius_used, tier_used, lookback_used, staleness_applied).
    """
    r1, r2, r3 = radii[0], radii[1], radii[2]

    for lookback in COMP_LOOKBACK_TIERS:
        # Filter by time first
        time_filtered = _filter_by_lookback(style_filtered, lookback)

        # Try r1
        comps = _filter_by_distance(time_filtered, target_lat, target_lon, r1)
        if len(comps) >= MIN_COMPS_REQUIRED:
            return comps, r1, 1, lookback, lookback > 365

        # Try r2
        comps = _filter_by_distance(time_filtered, target_lat, target_lon, r2)
        if len(comps) >= MIN_COMPS_REQUIRED:
            return comps, r2, 2, lookback, lookback > 365

        # Try r3
        comps = _filter_by_distance(time_filtered, target_lat, target_lon, r3)
        if len(comps) >= MIN_COMPS_REQUIRED:
            return comps, r3, 3, lookback, lookback > 365

    # If we exhausted all combinations and still don't have enough,
    # use the widest expansion (540 days, r3) — whatever we can get
    time_filtered = _filter_by_lookback(style_filtered, 540)
    comps = _filter_by_distance(time_filtered, target_lat, target_lon, r3)
    return comps, r3, 3, 540, True


# ─── Main Entry Point ──────────────────────────────────────────────────────

def calculate_comps(
    property_dict: dict,
    sold_properties: list[dict],
    radius_miles: Optional[float] = None,
    scan_type: Optional[str] = None,
) -> dict:
    """
    Calculate comps for a given property using two-dimensional expansion.

    Args:
        property_dict: The target property (needs lat, lon, sqft, acres, style, zip).
        sold_properties: List of sold property dicts to compare against.
        radius_miles: DEPRECATED — ignored in favor of tiered radius + time expansion.
        scan_type: 'residential', 'land', or 'commercial'.

    Returns:
        dict with all comp fields including confidence metadata.
    """
    stype = scan_type or property_dict.get("scan_type", "residential")

    target_price = property_dict.get("list_price") or 0
    target_sqft = property_dict.get("sqft")
    target_acres = property_dict.get("acres")
    target_lat = property_dict.get("lat")
    target_lon = property_dict.get("lon")
    target_style = property_dict.get("style", "")

    # Get density, category, and radii
    zip_code = property_dict.get("zip") or property_dict.get("zip_code", "")
    density = get_market_density(zip_code)
    category = get_property_category(property_dict.get("style"), property_dict.get("property_type"))
    radii = get_comp_radii(property_dict)

    # ── Missing lat/lon → skip comps entirely ─────────────────────────────
    if not target_lat or not target_lon:
        logger.info(
            f"Comps: skipped (no lat/lon) [{category}/{density}] — "
            f"{property_dict.get('address', '?')}"
        )
        return {
            "comp_median_price": None,
            "comp_count": 0,
            "comp_radius_miles": None,
            "comp_radius_used": None,
            "comp_tier_used": None,
            "comp_category": category,
            "comp_density": density,
            "comp_price_per_sqft_median": None,
            "comp_price_per_acre_median": None,
            "price_deviation_pct": None,
            "comp_confidence": None,
            "comp_confidence_label": None,
            "comp_confidence": None,
            "comp_lookback_used": None,
            "comp_staleness_penalty_applied": False,
            "comp_listings": [],
        }

    # ── Step 1: Filter by property style ─────────────────────────────────
    style_filtered = _filter_by_style(sold_properties, target_style, stype)

    # ── Step 2: 2D expansion search ──────────────────────────────────────
    comps, radius_used, tier_used, lookback_used, staleness = \
        find_comps_with_expansion(style_filtered, target_lat, target_lon, radii)

    # ── Step 3: Filter by size similarity ────────────────────────────────
    if len(comps) >= MIN_COMPS_REQUIRED:
        if target_sqft and stype in ("residential", "commercial"):
            sqft_pct = COMP_DEFAULTS["similar_sqft_pct"]
            min_sqft = target_sqft * (1 - sqft_pct)
            max_sqft = target_sqft * (1 + sqft_pct)
            sqft_matched = [
                c for c in comps
                if c.get("sqft") and min_sqft <= c["sqft"] <= max_sqft
            ]
            if len(sqft_matched) >= MIN_COMPS_REQUIRED:
                comps = sqft_matched

        elif stype == "land" and target_acres:
            acres_pct = COMP_DEFAULTS["similar_acres_pct"]
            min_acres = target_acres * (1 - acres_pct)
            max_acres = target_acres * (1 + acres_pct)
            acres_matched = [
                c for c in comps
                if c.get("acres") and min_acres <= c["acres"] <= max_acres
            ]
            if len(acres_matched) >= MIN_COMPS_REQUIRED:
                comps = acres_matched

    # ── Step 4: Calculate medians ─────────────────────────────────────────
    prices = [
        c.get("list_price") or c.get("last_sold_price") or 0
        for c in comps
        if (c.get("list_price") or c.get("last_sold_price"))
    ]
    price_per_sqft_list = [c.get("price_per_sqft") or 0 for c in comps if c.get("price_per_sqft")]
    price_per_acre_list = [c.get("price_per_acre") or 0 for c in comps if c.get("price_per_acre")]

    comp_count = len(comps)
    comp_median_price = _median(prices) if prices else None
    comp_ppsf_median = _median(price_per_sqft_list) if price_per_sqft_list else None
    comp_ppa_median = _median(price_per_acre_list) if price_per_acre_list else None

    # Price deviation
    price_deviation_pct = None
    if comp_median_price and target_price:
        price_deviation_pct = round(
            ((target_price - comp_median_price) / comp_median_price) * 100, 2
        )

    # ── Step 5: Calculate confidence ──────────────────────────────────────
    conf_float, conf_label = calculate_comp_confidence(
        comp_count, radius_used, lookback_used, radii
    )

    # ── Log ───────────────────────────────────────────────────────────────
    if comp_count > 0:
        logger.info(
            f"Comps: {comp_count} found at tier {tier_used} ({radius_used}mi, "
            f"{lookback_used}d) [{conf_label}/{conf_float:.0%}] "
            f"[{category}/{density}] — {property_dict.get('address', '?')}"
        )
    else:
        logger.info(
            f"Comps: 0 found (max: {radius_used}mi, {lookback_used}d) "
            f"[{category}/{density}] — {property_dict.get('address', '?')}"
        )

    # ── Step 6: Top comps for clickable display ──────────────────────────
    top_comps = []
    sorted_comps = sorted(
        comps,
        key=lambda c: abs((c.get("list_price") or c.get("last_sold_price") or 0) - target_price)
        if target_price else 0,
    )
    for c in sorted_comps[:10]:
        comp_price = c.get("list_price") or c.get("last_sold_price") or 0
        c_lat = c.get("lat")
        c_lon = c.get("lon")
        distance = None
        if c_lat and c_lon and target_lat and target_lon:
            distance = round(haversine_miles(target_lat, target_lon, c_lat, c_lon), 2)

        top_comps.append({
            "address": c.get("address", ""),
            "list_price": comp_price,
            "sqft": c.get("sqft"),
            "beds": c.get("beds"),
            "baths": c.get("baths"),
            "style": c.get("style", ""),
            "days_on_market": c.get("days_on_market"),
            "property_url": c.get("property_url", ""),
            "listing_status": c.get("listing_status", "sold"),
            "distance_miles": distance,
        })

    return {
        "comp_median_price": comp_median_price,
        "comp_count": comp_count,
        "comp_radius_miles": radius_used,
        "comp_radius_used": radius_used,
        "comp_tier_used": tier_used,
        "comp_lookback_used": lookback_used,
        "comp_category": category,
        "comp_density": density,
        "comp_price_per_sqft_median": comp_ppsf_median,
        "comp_price_per_acre_median": comp_ppa_median,
        "price_deviation_pct": price_deviation_pct,
        "comp_confidence": conf_float,
        "comp_confidence_label": conf_label,
        "comp_staleness_penalty_applied": staleness,
        "comp_listings": top_comps,
    }
