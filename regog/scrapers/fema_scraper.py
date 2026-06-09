"""
FEMA Flood Zone Scraper — queries the FEMA National Flood Hazard Layer (NFHL)
ArcGIS REST API to determine flood zone for a given lat/lon coordinate.

Free, no API key required.

Endpoint:
  https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query
"""

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# FEMA NFHL ArcGIS endpoint for Flood Hazard Zones (layer 28)
FEMA_ENDPOINT = (
    "https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL"
    "/MapServer/28/query"
)

# Simple in-memory cache: (lat, lon) -> flood zone dict
# Key is rounded to 4 decimal places (~10m resolution)
_flood_cache: dict[tuple[float, float], Optional[str]] = {}

# Rate limiting
_last_request_time: float = 0
_MIN_DELAY = 0.5  # seconds between requests
_MAX_RETRIES = 2


def get_flood_zone(lat: float, lon: float) -> Optional[str]:
    """
    Query FEMA NFHL for flood zone at a given latitude/longitude.

    Uses the simpler esriGeometryPoint query format. Returns the flood
    zone code string (e.g. 'X', 'AE', 'A', 'VE', 'D') or 'UNKNOWN'.

    Args:
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.

    Returns:
        Flood zone code string or 'UNKNOWN' if data unavailable.
    """
    if lat is None or lon is None:
        logger.debug("No lat/lon provided — cannot query flood zone")
        return "UNKNOWN"

    # Check cache (rounded to 4 decimal places ~ 10m resolution)
    cache_key = (round(lat, 4), round(lon, 4))
    if cache_key in _flood_cache:
        return _flood_cache[cache_key]

    # Rate limit
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < _MIN_DELAY:
        time.sleep(_MIN_DELAY - elapsed)

    attempts = 0
    while attempts <= _MAX_RETRIES:
        attempts += 1
        try:
            params = {
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF",
                "returnGeometry": "false",
                "f": "json",
            }

            resp = requests.get(FEMA_ENDPOINT, params=params, timeout=10)
            _last_request_time = time.time()

            if resp.status_code != 200:
                logger.warning(
                    f"FEMA API returned status {resp.status_code} "
                    f"(attempt {attempts})"
                )
                if attempts <= _MAX_RETRIES:
                    time.sleep(1.0)
                    continue
                _flood_cache[cache_key] = "UNKNOWN"
                return "UNKNOWN"

            data = resp.json()

            # Check for ArcGIS errors
            if "error" in data:
                err_msg = data["error"].get("message", "unknown")
                if attempts <= _MAX_RETRIES:
                    logger.debug(
                        f"FEMA API error (attempt {attempts}): {err_msg}"
                    )
                    time.sleep(1.0)
                    continue
                logger.warning(f"FEMA API error: {err_msg}")
                _flood_cache[cache_key] = "UNKNOWN"
                return "UNKNOWN"

            # Extract flood zone from features
            features = data.get("features", [])
            if not features:
                logger.debug(
                    f"No FEMA flood zone data for ({lat:.4f}, {lon:.4f})"
                )
                _flood_cache[cache_key] = "UNKNOWN"
                return "UNKNOWN"

            # Get the first feature's FLD_ZONE attribute
            attrs = features[0].get("attributes", {})
            zone = attrs.get("FLD_ZONE")

            if zone:
                zone = zone.strip().upper()
                sfha = attrs.get("SFHA_TF", "F") == "T"
                is_high_risk = zone.startswith(("A", "V")) and zone not in ("X",)
                logger.debug(
                    f"Flood zone at ({lat:.4f}, {lon:.4f}): {zone} "
                    f"(high_risk={is_high_risk}, sfha={sfha})"
                )
            else:
                logger.debug(
                    f"No FLD_ZONE attribute for ({lat:.4f}, {lon:.4f})"
                )
                zone = "UNKNOWN"

            _flood_cache[cache_key] = zone
            return zone

        except requests.Timeout:
            logger.warning(
                f"FEMA API timeout for ({lat:.4f}, {lon:.4f}) "
                f"(attempt {attempts})"
            )
            if attempts <= _MAX_RETRIES:
                time.sleep(1.0)
                continue
            _flood_cache[cache_key] = "UNKNOWN"
            return "UNKNOWN"
        except Exception as e:
            logger.warning(
                f"FEMA API error for ({lat:.4f}, {lon:.4f}): {e} "
                f"(attempt {attempts})"
            )
            if attempts <= _MAX_RETRIES:
                time.sleep(1.0)
                continue
            _flood_cache[cache_key] = "UNKNOWN"
            return "UNKNOWN"

    return "UNKNOWN"


def get_flood_zone_batch(
    coords: list[tuple[float, float]]
) -> dict[tuple[float, float], Optional[str]]:
    """Get flood zones for multiple coordinates."""
    results = {}
    for lat, lon in coords:
        results[(lat, lon)] = get_flood_zone(lat, lon)
    return results


def clear_cache() -> None:
    """Clear the in-memory flood zone cache."""
    _flood_cache.clear()
    logger.debug("FEMA flood zone cache cleared")
