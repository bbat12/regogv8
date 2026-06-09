"""
Redfin Scraper — fetches sold comparable properties using HomeHarvest (Realtor.com data).
For V1, this uses the same HomeHarvest library under the hood (which scrapes Redfin/Realtor.com).
Returns normalized property dicts ready for the comp engine.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import homeharvest
try:
    from homeharvest import scrape_property
    HAS_HOMEHARVEST = True
except ImportError:
    HAS_HOMEHARVEST = False
    scrape_property = None  # type: ignore

# Reuse the normalize function from the homeharvest scraper
try:
    from scrapers.homeharvest_scraper import normalize_listing
    CAN_NORMALIZE = True
except ImportError:
    CAN_NORMALIZE = False
    normalize_listing = None  # type: ignore


def normalize_sold_listing(raw: dict, scan_type: str = "residential") -> dict | None:
    """
    Normalize a raw HomeHarvest SOLD listing into the comp engine schema.

    Sold listings from HomeHarvest use different column names than for-sale:
      - sold_price (not list_price)
      - sold_date (not listing_date)
      - close_date, closing_date
      - Days on market is historical (DOM at time of sale)

    This function explicitly handles sold-specific columns and sets
    listing_status = "sold" so the comp engine treats them correctly.

    Args:
        raw: Raw HomeHarvest sold listing dict.
        scan_type: Property category for mapping defaults.

    Returns:
        Normalized property dict suitable for the comp engine, or None if critical fields missing.
    """
    def g(*keys):
        """Get first non-None value from a list of possible keys."""
        for k in keys:
            v = raw.get(k)
            if v is not None:
                return v
        return None

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

    # Sold price is the critical field — must have it
    sold_price = num(g("sold_price", "last_sold_price", "close_price", "sale_price", "price", "list_price"))
    if not sold_price:
        return None

    # Build listing_id
    listing_id = g("property_id", "listing_id", "mls_id", "id")
    if not listing_id:
        listing_id = f"sold_{hash(str(raw.get('address', '')) + str(sold_price))}"

    # Style / property type
    property_style = g("style", "property_type", "home_type")

    # Address fields
    address = g("full_street_line", "street", "address", "full_address", "formatted_address")
    city = g("city", "municipality")
    state = g("state", "province")
    zip_code = g("zip", "zip_code", "postal_code")

    # Coordinates
    lat = flt(g("latitude", "lat"))
    lon = flt(g("longitude", "lon", "lng"))

    # Size fields
    sqft_val = g("sqft", "square_feet", "sq_ft", "living_area", "building_area")
    acres_val = g(
        "acres", "acreage", "lot_size_acres", "lot_acres",
        "total_acres", "parcel_acres", "land_area",
        "land_acres", "area_acres", "gross_acres", "net_acres", "lot_area_acres"
    )

    # Fallback: derive acres from lot_sqft if direct field not found
    if acres_val is None:
        lot_sqft_val = flt(g("lot_sqft", "lot_size_sqft", "lot_area", "land_area_sqft", "lot_square_feet"))
        if lot_sqft_val and lot_sqft_val > 0:
            acres_val = round(lot_sqft_val / 43560, 4)

    lot_sqft = num(g("lot_sqft", "lot_size_sqft", "lot_area", "land_sqft", "parcel_sqft", "lot_size", "lot_area_sqft", "land_area_sqft", "lot_square_feet"))

    # Beds / baths
    beds = num(g("beds", "bedrooms", "baths_full", "bathrooms_full"))
    baths = flt(g("full_baths", "baths", "bathrooms", "bathrooms_total"))

    # Year built
    year_built = num(g("year_built", "year_built"))

    # Price per sqft — calculate from sold price if not directly available
    ppsf = flt(g("price_per_sqft", "ppsf", "price_sqft"))
    if ppsf is None and sold_price and sqft_val:
        sqft_num = flt(sqft_val)
        if sqft_num and sqft_num > 0:
            ppsf = round(sold_price / sqft_num, 2)

    # Price per acre — calculate if we have acres
    ppa = flt(g("price_per_acre"))
    if ppa is None and sold_price and acres_val:
        acres_num = flt(acres_val)
        if acres_num and acres_num > 0:
            ppa = round(sold_price / acres_num, 2)

    # Days on market (historical — DOM at time of sale)
    days_on_market = num(g("days_on_market", "dom", "days_on_mls"))

    # Sold date
    last_sold_date = g("last_sold_date", "sold_date", "close_date", "closing_date")

    # Assessed / estimated value (HomeHarvest may provide)
    estimated_value = num(g("estimated_value", "value", "zestimate", "avm_value"))
    assessed_value = num(g("assessed_value", "tax_assessment", "assessed_valuation"))

    # County
    county = g("county", "parish")

    # Listing description (may not be available for sold)
    description = g("description", "listing_description", "text", "remarks", "public_remarks")

    # Listing image (thumbnail)
    primary_photo = g("primary_photo", "photo", "image_url", "thumbnail_url")

    # Number of stories (for high-rise detection)
    stories = num(g("stories", "num_stories", "floors", "total_stories"))

    # Property URL — HomeHarvest includes this for sold listings too
    property_url = g("property_url", "listing_url", "url", "href")

    return {
        "listing_id": str(listing_id),
        "source": "redfin",
        "scan_type": scan_type,
        "style": property_style,
        "address": address,
        "city": city,
        "state": state,
        "zip": zip_code,
        "lat": lat,
        "lon": lon,
        "list_price": sold_price,        # ← Sold price as list_price for comp engine compatibility
        "price_per_sqft": ppsf,
        "price_per_acre": ppa,
        "sqft": num(sqft_val),
        "acres": flt(acres_val),
        "stories": stories,
        "primary_photo": primary_photo,
        "beds": beds,
        "baths": baths,
        "year_built": year_built,
        "lot_sqft": lot_sqft,
        "days_on_market": days_on_market,
        "listing_status": "sold",         # ← Explicitly set to "sold"
        "listing_description": description,
        "last_sold_price": sold_price,    # ← Explicit sold price field
        "last_sold_date": last_sold_date,
        "property_url": property_url,     # ← Now actually extracted from raw data!
        "price_history": None,
        "estimated_value": estimated_value,
        "assessed_value": assessed_value,
        "county": county,
    }



def fetch_sold_comps(
    location: str,
    scan_type: str = "residential",
    past_days: int = 180,
    limit: int = 200,
) -> list[dict]:
    """
    Fetch sold comparable properties for a location using HomeHarvest.

    These are used by the comp engine to calculate median prices,
    price per sqft, and price deviation for each active listing.

    Uses normalize_sold_listing() which has explicit support for sold
    column names from HomeHarvest (sold_price, close_date, etc.).

    Args:
        location: City, "City, State", or ZIP code.
        scan_type: "residential", "land", or "commercial".
        past_days: Look back window for sold data (default 180 days).
        limit: Max sold properties to return.

    Returns:
        List of normalized property dicts with sold prices.
    """
    if not HAS_HOMEHARVEST:
        logger.warning("homeharvest not installed — cannot fetch sold comps")
        return []

    # Map scan_type to property types for sold search
    property_types = {
        "residential": ["single_family", "mobile"],  # Single family + mobile homes
        "land": ["land"],                              # Vacant land only
        "commercial": ["multi_family", "apartment", "condos", "townhomes", "duplex_triplex", "farm"],  # Everything else except mobile
    }.get(scan_type, ["single_family"])

    logger.info(
        f"Fetching sold comps in '{location}' "
        f"(past {past_days}d, types: {property_types}, limit: {limit})"
    )

    try:
        df = scrape_property(
            location=location,
            listing_type="sold",
            past_days=past_days,
            property_type=property_types,
            limit=limit,
        )

        if df is None or df.empty:
            logger.info(f"No sold comps found for '{location}'")
            return []

        # Convert to list of dicts
        raw_listings = df.to_dict(orient="records")
        logger.info(f"Found {len(raw_listings)} sold comps in '{location}'")

        # Normalize each sold listing using the sold-specific normalizer
        comps = []
        for raw in raw_listings:
            try:
                comp = normalize_sold_listing(raw, scan_type=scan_type)
                if comp:
                    comps.append(comp)
            except Exception as e:
                logger.debug(f"Skipping sold comp normalization error: {e}")
                continue

        logger.info(f"Normalized {len(comps)} sold comps for '{location}'")
        return comps[:limit]

    except Exception as e:
        logger.error(f"Failed to fetch sold comps for '{location}': {e}")
        return []


def fetch_sold_comps_near_coords(
    lat: float,
    lon: float,
    radius_miles: float = 3,
    scan_type: str = "residential",
    limit: int = 50,
) -> list[dict]:
    """
    Fetch sold comps near specific coordinates.
    This is a convenience wrapper — for now, it returns empty since
    HomeHarvest doesn't support coordinate-based queries directly.
    City-level sold comp fetching is used instead.
    """
    logger.info(
        f"Coordinate-based sold comps not yet available "
        f"(near {lat:.4f}, {lon:.4f}). Use city-level fetch instead."
    )
    return []


def fetch_sold_comps_near_coords(
    lat: float,
    lon: float,
    radius_miles: float = 3,
    scan_type: str = "residential",
    limit: int = 50,
) -> list[dict]:
    """
    Fetch sold comps near specific coordinates.
    This is a convenience wrapper — for now, it returns empty since
    HomeHarvest doesn't support coordinate-based queries directly.
    City-level sold comp fetching is used instead.
    """
    logger.info(
        f"Coordinate-based sold comps not yet available "
        f"(near {lat:.4f}, {lon:.4f}). Use city-level fetch instead."
    )
    return []
