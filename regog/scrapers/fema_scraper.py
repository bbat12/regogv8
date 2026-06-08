"""
FEMA Flood Zone Scraper — queries the FEMA National Flood Hazard Layer (NFHL)
ArcGIS REST API to determine flood zone for a given lat/lon coordinate.

Free, no API key required.

Endpoint: https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query
"""

import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# FEMA NFHL ArcGIS endpoint for Flood Hazard Zones (layer 28)
FEMA_ENDPOINT = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"

# Simple in-memory cache: (lat, lon) -> flood_zone
# Key is rounded to 3 decimal places (~100m resolution) to avoid redundant queries
_flood_cache: dict[tuple[float, float], Optional[str]] = {}

# Rate limiting
_last_request_time: float = 0
_MIN_DELAY = 1.0  # seconds between requests


def get_flood_zone(lat: float, lon: float) -> Optional[str]:
    """
    Query FEMA NFHL for flood zone at a given latitude/longitude.

    Args:
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.

    Returns:
        Flood zone code string (e.g. 'X', 'AE', 'A', 'VE', 'D') or None if unknown.
    """
    if lat is None or lon is None:
        logger.debug("No lat/lon provided — cannot query flood zone")
        return None

    # Check cache (rounded to 3 decimal places ~ 100m resolution)
    cache_key = (round(lat, 3), round(lon, 3))
    if cache_key in _flood_cache:
        return _flood_cache[cache_key]

    # Rate limit
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < _MIN_DELAY:
        time.sleep(_MIN_DELAY - elapsed)

    # Retry up to 2 times for transient failures
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            params = {
                "f": "json",
                "geometry": f'{{"x":{lon},"y":{lat},"spatialReference":{{"wkid":4326}}}}',
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "outSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA,FLOODWAY",
                "returnGeometry": "false",
            }

            response = httpx.get(FEMA_ENDPOINT, params=params, timeout=15)
            _last_request_time = time.time()

            if response.status_code != 200:
                logger.warning(f"FEMA API returned status {response.status_code} (attempt {attempt + 1})")
                if attempt < max_retries:
                    time.sleep(2)
                    continue
                _flood_cache[cache_key] = None
                return None

            data = response.json()

            # Check for ArcGIS errors
            if "error" in data:
                err_msg = data['error'].get('message', 'unknown')
                if attempt < max_retries:
                    logger.debug(f"FEMA API error (attempt {attempt + 1}): {err_msg} — retrying...")
                    time.sleep(2)
                    continue
                logger.warning(f"FEMA API error: {err_msg}")
                _flood_cache[cache_key] = None
                return None

            # Extract flood zone from features
            features = data.get("features", [])
            if not features:
                logger.debug(f"No FEMA flood zone data for ({lat:.4f}, {lon:.4f})")
                _flood_cache[cache_key] = None
                return None

            # Get the first feature's FLD_ZONE attribute
            attributes = features[0].get("attributes", {})
            flood_zone = attributes.get("FLD_ZONE")

            if flood_zone:
                flood_zone = flood_zone.strip().upper()
                logger.debug(
                    f"Flood zone at ({lat:.4f}, {lon:.4f}): {flood_zone} "
                    f"(subtype: {attributes.get('ZONE_SUBTY', 'N/A')})"
                )
            else:
                logger.debug(f"No FLD_ZONE attribute for ({lat:.4f}, {lon:.4f})")

            _flood_cache[cache_key] = flood_zone
            return flood_zone

        except httpx.TimeoutException:
            logger.warning(f"FEMA API timeout for ({lat:.4f}, {lon:.4f}) (attempt {attempt + 1})")
            if attempt < max_retries:
                time.sleep(2)
                continue
            _flood_cache[cache_key] = None
            return None
        except Exception as e:
            logger.warning(f"FEMA API error for ({lat:.4f}, {lon:.4f}): {e} (attempt {attempt + 1})")
            if attempt < max_retries:
                time.sleep(2)
                continue
            _flood_cache[cache_key] = None
            return None

    return None


def get_flood_zone_batch(coords: list[tuple[float, float]]) -> dict[tuple[float, float], Optional[str]]:
    """
    Get flood zones for multiple coordinates.
    Returns dict mapping (lat, lon) -> flood_zone or None.
    """
    results = {}
    for lat, lon in coords:
        results[(lat, lon)] = get_flood_zone(lat, lon)
    return results


def clear_cache():
    """Clear the in-memory flood zone cache."""
    _flood_cache.clear()
    logger.debug("FEMA flood zone cache cleared")
