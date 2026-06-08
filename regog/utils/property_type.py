"""
Property Type Detection — maps HomeHarvest style/property_type values to
'residential', 'land', or 'commercial' categories for comp radius selection.
"""

from typing import Optional

# Styles that map to residential
_RESIDENTIAL_STYLES: set[str] = {
    "SINGLE_FAMILY", "CONDOS", "CONDO", "TOWNHOMES", "TOWNHOUSE",
    "MULTI_FAMILY", "DUPLEX", "TRIPLEX", "QUADPLEX", "APARTMENT",
    "MOBILE", "MANUFACTURED",
}

# Styles that map to land
_LAND_STYLES: set[str] = {
    "LAND", "LOT", "LOTS_LAND", "FARM", "RANCH", "ACREAGE", "VACANT",
}

# Styles that map to commercial
_COMMERCIAL_STYLES: set[str] = {
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
) -> str:
    """
    Maps HomeHarvest style/property_type values to a property category
    for comp radius selection.

    Args:
        style: HomeHarvest 'style' field (e.g. 'SINGLE_FAMILY', 'LAND').
        property_type: Fallback field if style is None.

    Returns:
        'residential', 'land', or 'commercial'.
        Defaults to 'residential' if neither matches.
    """
    # Try style first
    norm_style = _normalize_style(style)
    if norm_style:
        if norm_style in _RESIDENTIAL_STYLES:
            return "residential"
        if norm_style in _LAND_STYLES:
            return "land"
        if norm_style in _COMMERCIAL_STYLES:
            return "commercial"

    # Fall back to property_type
    norm_ptype = _normalize_style(property_type)
    if norm_ptype:
        if norm_ptype in _RESIDENTIAL_STYLES:
            return "residential"
        if norm_ptype in _LAND_STYLES:
            return "land"
        if norm_ptype in _COMMERCIAL_STYLES:
            return "commercial"

    return "residential"
