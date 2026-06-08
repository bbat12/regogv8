"""
Geocoder — converts address strings to lat/lon using Nominatim (free, no API key).
Also reverses geocode for nearest city when needed.
"""

import logging
import time
from typing import Optional
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Rate limit: 1 req/sec per Nominatim's ToS
_LAST_REQUEST_TIME = 0.0


@dataclass
class GeocodeResult:
    lat: float
    lon: float
    display_name: str
    city: Optional[str] = None
    county: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None


def _rate_limit():
    """Ensure we don't exceed Nominatim's 1 req/sec limit."""
    global _LAST_REQUEST_TIME
    now = time.time()
    elapsed = now - _LAST_REQUEST_TIME
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _LAST_REQUEST_TIME = time.time()


def geocode_address(address: str) -> Optional[GeocodeResult]:
    """
    Geocode a full address string to lat/lon using Nominatim.
    Returns None on failure.
    """
    _rate_limit()

    params = {
        "q": address,
        "format": "json",
        "limit": 1,
        "addressdetails": 1,
    }
    headers = {
        "User-Agent": "REGOG/1.0 (real-estate-scanner)",
    }

    try:
        resp = httpx.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            logger.warning(f"Geocode returned no results for '{address}'")
            return None

        entry = data[0]
        addr = entry.get("address", {})
        return GeocodeResult(
            lat=float(entry["lat"]),
            lon=float(entry["lon"]),
            display_name=entry.get("display_name", ""),
            city=addr.get("city") or addr.get("town") or addr.get("village"),
            county=addr.get("county"),
            state=addr.get("state"),
            zip_code=addr.get("postcode"),
        )

    except httpx.HTTPError as e:
        logger.error(f"Geocode HTTP error for '{address}': {e}")
        return None
    except (KeyError, ValueError, IndexError) as e:
        logger.error(f"Geocode parse error for '{address}': {e}")
        return None


def reverse_geocode(lat: float, lon: float) -> Optional[GeocodeResult]:
    """
    Reverse geocode lat/lon to address using Nominatim.
    """
    _rate_limit()

    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "addressdetails": 1,
    }
    headers = {
        "User-Agent": "REGOG/1.0 (real-estate-scanner)",
    }

    try:
        resp = httpx.get(
            "https://nominatim.openstreetmap.org/reverse",
            params=params,
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        addr = data.get("address", {})
        return GeocodeResult(
            lat=lat,
            lon=lon,
            display_name=data.get("display_name", ""),
            city=addr.get("city") or addr.get("town") or addr.get("village"),
            county=addr.get("county"),
            state=addr.get("state"),
            zip_code=addr.get("postcode"),
        )

    except httpx.HTTPError as e:
        logger.error(f"Reverse geocode HTTP error for ({lat}, {lon}): {e}")
        return None
