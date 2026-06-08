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

    if not CAN_NORMALIZE:
        logger.warning("normalize_listing not available — cannot fetch sold comps")
        return []

    # Map scan_type to property types for sold search
    property_types = {
        "residential": ["single_family", "multi_family", "condos", "townhomes", "duplex_triplex"],
        "land": ["land"],
        "commercial": ["multi_family"],
    }.get(scan_type, ["single_family", "multi_family", "condos", "townhomes"])

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

        # Normalize each listing into the REGOG property schema
        comps = []
        for raw in raw_listings:
            try:
                comp = normalize_listing(raw, source="redfin", scan_type=scan_type)
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
