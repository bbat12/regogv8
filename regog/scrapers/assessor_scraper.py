"""
County Assessor Scraper — provides assessed/estimated property values.

For V1, this module extracts valuation data directly from HomeHarvest results
(estimated_value, assessed_value fields that come from Realtor.com).

Strategy for future versions:
1. Geocode address to county via geopy/Nominatim
2. Look up county assessor URL from built-in registry
3. Search by address or APN using httpx + beautifulsoup4
4. qPublic platform → unified scraper for hundreds of counties
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# In-memory cache for county lookups
_county_cache: dict[str, Optional[str]] = {}


def enrich_with_assessor_data(property_dict: dict) -> dict:
    """
    Enrich a property dict with assessor/valuation data.

    For V1, this extracts the estimated_value and assessed_value that
    HomeHarvest already provides. Future versions will add direct
    county assessor website scraping.

    Args:
        property_dict: Property dict (usually from normalize_listing).

    Returns:
        Updated property dict with assessor fields filled in.
    """
    prop = dict(property_dict)  # Don't mutate original

    # HomeHarvest already provides these (or None)
    estimated_value = prop.get("estimated_value")
    assessed_value = prop.get("assessed_value")

    # If we have estimated_value but no assessed_value, use estimated as a proxy
    if assessed_value is None and estimated_value is not None:
        prop["assessed_value"] = estimated_value
        logger.debug(f"Using estimated_value ${estimated_value:,} as assessor proxy")

    # Try to determine county from address if not provided
    county = prop.get("county")
    if not county:
        # Attempt reverse geocode or fall back to looking up from city/state
        city = prop.get("city", "")
        state = prop.get("state", "")
        if city and state:
            county = _lookup_county(city, state)
            if county:
                prop["county"] = county

    return prop


def _lookup_county(city: str, state: str) -> Optional[str]:
    """
    Look up county name for a given city and state.
    Uses a built-in registry of major US cities → county mappings.

    For V1, this covers major metro areas. Future versions will
    use the geocoder for dynamic lookup.
    """
    cache_key = f"{city}, {state}".lower()
    if cache_key in _county_cache:
        return _county_cache[cache_key]

    # Built-in registry for major metro areas
    registry = {
        # Texas
        ("dallas", "tx"): "Dallas County",
        ("fort worth", "tx"): "Tarrant County",
        ("houston", "tx"): "Harris County",
        ("austin", "tx"): "Travis County",
        ("san antonio", "tx"): "Bexar County",
        ("plano", "tx"): "Collin County",
        ("irving", "tx"): "Dallas County",
        ("garland", "tx"): "Dallas County",
        ("mesquite", "tx"): "Dallas County",
        ("frisco", "tx"): "Collin County",
        ("carrollton", "tx"): "Denton County",
        ("denton", "tx"): "Denton County",
        ("arlington", "tx"): "Tarrant County",
        ("el paso", "tx"): "El Paso County",
        # California
        ("los angeles", "ca"): "Los Angeles County",
        ("san diego", "ca"): "San Diego County",
        ("san jose", "ca"): "Santa Clara County",
        ("san francisco", "ca"): "San Francisco County",
        ("oakland", "ca"): "Alameda County",
        ("sacramento", "ca"): "Sacramento County",
        ("fresno", "ca"): "Fresno County",
        ("long beach", "ca"): "Los Angeles County",
        # Arizona
        ("phoenix", "az"): "Maricopa County",
        ("tucson", "az"): "Pima County",
        ("mesa", "az"): "Maricopa County",
        ("scottsdale", "az"): "Maricopa County",
        # Florida
        ("miami", "fl"): "Miami-Dade County",
        ("orlando", "fl"): "Orange County",
        ("tampa", "fl"): "Hillsborough County",
        ("jacksonville", "fl"): "Duval County",
        # New York
        ("new york", "ny"): "New York County",
        ("brooklyn", "ny"): "Kings County",
        ("queens", "ny"): "Queens County",
        ("buffalo", "ny"): "Erie County",
        # Illinois
        ("chicago", "il"): "Cook County",
        ("aurora", "il"): "Kane County",
        # Other major cities
        ("seattle", "wa"): "King County",
        ("portland", "or"): "Multnomah County",
        ("denver", "co"): "Denver County",
        ("las vegas", "nv"): "Clark County",
        ("atlanta", "ga"): "Fulton County",
        ("nashville", "tn"): "Davidson County",
        ("charlotte", "nc"): "Mecklenburg County",
        ("memphis", "tn"): "Shelby County",
        ("boston", "ma"): "Suffolk County",
        ("philadelphia", "pa"): "Philadelphia County",
        ("detroit", "mi"): "Wayne County",
        ("minneapolis", "mn"): "Hennepin County",
        ("st. louis", "mo"): "St. Louis County",
        ("kansas city", "mo"): "Jackson County",
        ("columbus", "oh"): "Franklin County",
        ("indianapolis", "in"): "Marion County",
        ("milwaukee", "wi"): "Milwaukee County",
        ("new orleans", "la"): "Orleans Parish",
        ("salt lake city", "ut"): "Salt Lake County",
        ("raleigh", "nc"): "Wake County",
        ("baltimore", "md"): "Baltimore City",
        ("richmond", "va"): "Richmond City",
    }

    result = registry.get((city.lower().strip(), state.lower().strip()))
    _county_cache[cache_key] = result
    if result:
        logger.debug(f"Resolved county for {city}, {state}: {result}")
    return result
