"""
Property Type Detection — maps HomeHarvest style/property_type values to
'residential', 'land', or 'commercial' categories for comp radius selection.

High-rise condos (stories >= HIGH_RISE_MIN_STORIES) are reclassified as
commercial since they behave more like commercial assets for investment
analysis (different operating costs, comps, risk profiles).
"""

from typing import Optional

from config import HIGH_RISE_MIN_STORIES

# Styles that map to residential — single family homes and mobile homes
_RESIDENTIAL_STYLES: set[str] = {
    "SINGLE_FAMILY", "MANUFACTURED", "MOBILE",
}

# Styles that map to land
_LAND_STYLES: set[str] = {
    "LAND", "LOT", "LOTS_LAND", "FARM", "RANCH", "ACREAGE", "VACANT",
}

# Styles that map to commercial — everything except single family, mobile, and land
_COMMERCIAL_STYLES: set[str] = {
    "CONDOS", "CONDO", "TOWNHOMES", "TOWNHOUSE",
    "MULTI_FAMILY", "APARTMENT",
    "DUPLEX", "TRIPLEX", "QUADPLEX",
    "COMMERCIAL", "OFFICE", "RETAIL", "INDUSTRIAL", "WAREHOUSE",
    "MIXED_USE", "SPECIAL_PURPOSE", "HOTEL", "MOTEL",
}


def _normalize_style(value: Optional[str]) -> Optional[str]:
    """Strip whitespace, underscores, and uppercase for matching."""
    if not value:
        return None
    return value.strip().replace(" ", "_").replace("-", "_").upper()


def get_property_category(
    style: Optional[str],
    property_type: Optional[str] = None,
    stories: Optional[int] = None,
) -> str:
    """
    Maps HomeHarvest style/property_type values to a property category
    for comp radius selection.

    High-rise condos (CONDO/CONDOS style with stories >= HIGH_RISE_MIN_STORIES)
    are reclassified as commercial since they behave as commercial assets for
    investment analysis purposes.

    Args:
        style: HomeHarvest 'style' field (e.g. 'SINGLE_FAMILY', 'LAND').
        property_type: Fallback field if style is None.
        stories: Number of stories in the building. Used to detect high-rises.

    Returns:
        'residential', 'land', or 'commercial'.
        Defaults to 'residential' if neither matches.
    """
    # Try style first
    norm_style = _normalize_style(style)
    if norm_style:
        # High-rise condo detection: CONDO/CONDOS buildings with enough stories
        # get reclassified as commercial
        if norm_style in ("CONDOS", "CONDO") and stories is not None and stories >= HIGH_RISE_MIN_STORIES:
            return "commercial"

        if norm_style in _RESIDENTIAL_STYLES:
            return "residential"
        if norm_style in _LAND_STYLES:
            return "land"
        if norm_style in _COMMERCIAL_STYLES:
            return "commercial"

    # Fall back to property_type
    norm_ptype = _normalize_style(property_type)
    if norm_ptype:
        # Same high-rise detection using property_type as fallback
        if norm_ptype in ("CONDOS", "CONDO") and stories is not None and stories >= HIGH_RISE_MIN_STORIES:
            return "commercial"

        if norm_ptype in _RESIDENTIAL_STYLES:
            return "residential"
        if norm_ptype in _LAND_STYLES:
            return "land"
        if norm_ptype in _COMMERCIAL_STYLES:
            return "commercial"

    return "residential"
