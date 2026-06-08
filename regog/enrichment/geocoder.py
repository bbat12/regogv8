"""
GEOCODER — ⚠️ DEAD CODE ⚠️

This module was originally intended for Nominatim-based geocoding (reverse geocode
address to lat/lon, resolve county from coordinates). However, it is NEVER called
by the scan pipeline in main.py, web/app.py, or any other module.

HomeHarvest provides lat/lon and county data directly, making this module unnecessary.

If county resolution for non-60-major-metros is needed in the future, re-enable this
with the Nominatim API (1 req/sec, free, no key).

For now, this file exists as a placeholder but is NOT imported anywhere.
"""
