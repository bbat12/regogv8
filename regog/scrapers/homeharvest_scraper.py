"""
HomeHarvest Scraper — pulls listings from Realtor.com (free, no API key).
Uses the `homeharvest` library which scrapes Realtor.com directly.
"""

from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Try to import homeharvest; provide a fallback for development
try:
    from homeharvest import scrape_property
    HAS_HOMEHARVEST = True
except ImportError:
    HAS_HOMEHARVEST = False
    scrape_property = None  # type: ignore


def fetch_listings(
    location: str,
    listing_type: str = "for_sale",
    past_days: int = 90,
    property_type: Optional[list] = None,
) -> list[dict]:
    """
    Fetch listings from Realtor.com via HomeHarvest.

    Args:
        location: City, state, ZIP, or "City, State" string.
        listing_type: "for_sale", "sold", "for_rent", or "pending".
        past_days: Look back period (default 90).
        property_type: e.g. ["single_family", "multi_family", "land", "commercial"].

    Returns:
        List of property dicts from HomeHarvest.
    """
    if not HAS_HOMEHARVEST:
        logger.warning("homeharvest not installed — returning empty listing set")
        return []

    logger.info(
        f"Fetching {listing_type} listings in '{location}' "
        f"(past {past_days}d, types: {property_type or 'all'})"
    )

    try:
        df = scrape_property(
            location=location,
            listing_type=listing_type,
            past_days=past_days,
            property_type=property_type,
        )
        if df is None or df.empty:
            logger.info(f"No listings found for '{location}'")
            return []

        # Convert DataFrame to list of dicts, cleaning column names
        properties = df.to_dict(orient="records")
        logger.info(f"Found {len(properties)} listings from HomeHarvest")
        return properties

    except Exception as e:
        logger.error(f"HomeHarvest scrape failed for '{location}': {e}")
        return []


def normalize_listing(raw: dict, source: str = "realtor", scan_session_id: str = None, scan_type: str = "residential") -> dict:
    """
    Normalize a raw HomeHarvest listing dict into REGOG's property schema.
    Maps the library's column names to our database columns.
    """
    # Common field name variations from homeharvest
    def g(*keys):
        """Get first non-None value from a list of possible keys."""
        for k in keys:
            v = raw.get(k)
            if v is not None:
                return v
        return None

    listing_id = g("property_id", "listing_id", "mls_id", "id")
    if not listing_id:
        listing_id = f"{source}_{hash(str(raw.get('address', '')) + str(raw.get('list_price', '')))}"

    beds = g("beds", "bedrooms", "baths_full", "bathrooms_full")
    baths_total = g("full_baths", "baths", "bathrooms", "bathrooms_total")
    sqft_val = g("sqft", "square_feet", "sq_ft", "living_area", "building_area")
    lot_sqft_val = g("lot_sqft", "lot_square_feet", "lot_size_sqft")
    acres_val = g("acres", "acreage", "lot_size_acres", "lot_acres")

    # Property style/type (e.g. SINGLE_FAMILY, CONDOS, TOWNHOMES, MULTI_FAMILY, LAND)
    # Capturing this is critical for accurate comp matching
    property_style = g("style", "property_type", "home_type")

    # Attempt to cast numeric fields
    def num(v):
        try:
            return int(v) if v else None
        except (ValueError, TypeError):
            try:
                return int(float(v))
            except (ValueError, TypeError):
                return None

    def flt(v):
        try:
            return float(v) if v else None
        except (ValueError, TypeError):
            return None

    price = num(g("list_price", "price", "current_price", "sold_price"))
    beds_int = num(beds)
    baths_float = flt(baths_total)

    # Price per sqft
    ppsf = flt(g("price_per_sqft", "ppsf", "price_sqft"))
    if ppsf is None and price and sqft_val:
        sqft_num = flt(sqft_val)
        if sqft_num and sqft_num > 0:
            ppsf = round(price / sqft_num, 2)

    days = num(g("days_on_market", "dom", "days_on_mls", "listing_age"))

    year = num(g("year_built", "year_built"))
    lat = flt(g("latitude", "lat"))
    lon = flt(g("longitude", "lon", "lng"))

    # Price per acre for land
    ppa = flt(g("price_per_acre"))
    if ppa is None and price and acres_val:
        acres_num = flt(acres_val)
        if acres_num and acres_num > 0:
            ppa = round(price / acres_num, 2)

    # Listing description
    description = g("description", "listing_description", "text", "remarks", "public_remarks")

    # Realtor.com detail URL + permalink
    property_url = g("property_url", "rdc_web_url", "href", "url")
    permalink = g("permalink", "mls_id")

    # Last sold info
    last_sold_price = num(g("last_sold_price", "sold_price"))
    last_sold_date = g("last_sold_date", "sold_date")

    # Assessor / valuation data (HomeHarvest may provide estimated_value for for_sale listings)
    estimated_value = num(g("estimated_value", "value", "zestimate", "avm_value"))
    assessed_value = num(g("assessed_value", "tax_assessment", "assessed_valuation"))

    return {
        "listing_id": str(listing_id),
        "source": source,
        "scan_type": scan_type,
        "style": property_style,  # Property type for comp matching
        "address": g("full_street_line", "street", "address", "full_address", "formatted_address"),
        "city": g("city", "municipality"),
        "state": g("state", "province"),
        "zip": g("zip", "zip_code", "postal_code"),
        "lat": lat,
        "lon": lon,
        "list_price": price,
        "price_per_sqft": ppsf,
        "price_per_acre": ppa,
        "sqft": num(sqft_val),
        "acres": flt(acres_val),
        "beds": beds_int,
        "baths": baths_float,
        "year_built": year,
        "lot_sqft": num(lot_sqft_val),
        "days_on_market": days,
        "listing_status": g("status", "listing_status", "property_status", "sale_type"),
        "listing_description": description,
        "last_sold_price": last_sold_price,
        "last_sold_date": last_sold_date,
        "property_url": property_url,
        "price_history": None,  # Not typically available from homeharvest
        "estimated_value": estimated_value,
        "assessed_value": assessed_value,
        "county": g("county", "parish"),
        "scan_session_id": scan_session_id,
    }


def fetch_sold_comps(
    lat: float,
    lon: float,
    radius_miles: float = 3,
    scan_type: str = "residential",
) -> list[dict]:
    """
    Fetch sold comps near a point using HomeHarvest.
    We geocode the point to a nearby city/zip then filter by distance in post-processing.
    This is a simplified version — real implementation requires geocoding integration.
    """
    if not HAS_HOMEHARVEST:
        return []

    logger.info(f"Fetching sold comps near ({lat:.4f}, {lon:.4f}) radius {radius_miles}mi")
    # For now, return empty — comps will be fetched by city-level query
    return []
