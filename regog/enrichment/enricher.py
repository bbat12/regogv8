"""
Property Enricher — orchestrates enrichment of property data with
assessor valuations and FEMA flood zone information.

Called once per property during the scan pipeline, after normalization
but before scoring.
"""

import logging
from typing import Optional

from scrapers.fema_scraper import get_flood_zone
from scrapers.assessor_scraper import enrich_with_assessor_data
from scrapers.permit_scraper import fetch_permits

logger = logging.getLogger(__name__)


def enrich_property(property_dict: dict, skip_flood: bool = False) -> dict:
    """
    Enrich a single property with assessor data, FEMA flood zone, and permit signals.

    Steps:
    1. Extract assessor/valuation data (estimated_value, assessed_value, county)
    2. Query FEMA flood zone by lat/lon (unless skip_flood=True)
    3. Analyze listing description for permit signals
    4. Return updated property dict

    Args:
        property_dict: Normalized property dict from the scan pipeline.
        skip_flood: If True, skip FEMA flood zone lookup (faster).

    Returns:
        Enriched property dict with additional fields:
            - assessed_value (if available)
            - estimated_value (if available)
            - county (if resolved)
            - flood_zone (from FEMA API, if lat/lon available and not skipped)
            - permit_flags (dict with permit risk signals)
            - permit_risk (str: low/medium/high/unknown)
    """
    prop = dict(property_dict)  # Don't mutate original

    # Step 1: Assessor enrichment
    prop = enrich_with_assessor_data(prop)

    # Step 2: FEMA flood zone
    if skip_flood:
        prop["flood_zone"] = None
    else:
        lat = prop.get("lat")
        lon = prop.get("lon")
        if lat is not None and lon is not None:
            flood_zone = get_flood_zone(lat, lon)
            if flood_zone:
                prop["flood_zone"] = flood_zone
                logger.debug(
                    f"Flood zone for {prop.get('address', 'unknown')}: {flood_zone}"
                )
            else:
                if "flood_zone" not in prop:
                    prop["flood_zone"] = None
        else:
            logger.debug(f"No coordinates for {prop.get('address', 'unknown')} — skipping flood zone lookup")
            prop["flood_zone"] = None

    # Step 3: Permit signal analysis (from listing description)
    permit_result = fetch_permits(
        address=prop.get("address"),
        zip_code=prop.get("zip"),
        county=prop.get("county"),
        city=prop.get("city"),
        description=prop.get("listing_description"),
    )
    # Store permit data as JSON (permit_risk is embedded inside the dict)
    prop["permit_flags"] = permit_result

    if permit_result.get("unpermitted_additions") or permit_result.get("code_violations"):
        logger.debug(
            f"Permit red flags for {prop.get('address', 'unknown')}: "
            f"unpermitted={permit_result['unpermitted_additions']}, "
            f"violations={len(permit_result.get('code_violations', []))}"
        )

    return prop


def batch_enrich(properties: list[dict], batch_size: int = 50) -> list[dict]:
    """
    Enrich a batch of properties.

    Args:
        properties: List of normalized property dicts.
        batch_size: Number to log progress at.

    Returns:
        List of enriched property dicts.
    """
    enriched = []
    total = len(properties)

    for i, prop in enumerate(properties):
        enriched_prop = enrich_property(prop)
        enriched.append(enriched_prop)

        if (i + 1) % batch_size == 0:
            logger.info(f"Enriched {i + 1}/{total} properties...")

    logger.info(f"Enrichment complete: {total} properties")
    return enriched
