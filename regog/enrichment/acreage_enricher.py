"""
Acreage Enricher — enriches land parcels with acreage data from multiple fallback sources
when HomeHarvest returns null lot_sqft or acreage.

Sources tried in order:
1. Compute from lot_sqft if available (1 acre = 43,560 sqft)
2. Parse from listing description text
3. Parse from title/address text
4. Estimate from price-based heuristic as last resort
"""

import re
import math
from typing import Optional

SQFT_PER_ACRE = 43_560


def enrich_acreage(prop: dict) -> dict:
    """
    Attempts to fill missing acreage from multiple sources.
    Updates prop in place. Returns prop.

    Sources tried in order:
    1. Already have acreage → skip
    2. Compute from lot_sqft / lot_size_sqft
    3. Parse from description text
    4. Parse from title/address text
    5. Estimate from price-based heuristic
    """
    # Already have acreage → skip
    if prop.get("acres") and float(prop["acres"]) > 0:
        return prop

    # Source 1: Compute from lot_sqft
    lot_sqft = prop.get("lot_sqft") or prop.get("lot_size_sqft")
    if lot_sqft and float(lot_sqft) > 0:
        prop["acres"] = round(float(lot_sqft) / SQFT_PER_ACRE, 4)
        prop["acres_source"] = "lot_sqft"
        return prop

    # Source 2: Parse from description text
    description = prop.get("description") or prop.get("listing_description") or prop.get("text") or ""
    acres_from_desc = parse_acreage_from_text(description)
    if acres_from_desc:
        prop["acres"] = acres_from_desc
        prop["acres_source"] = "description_parse"
        return prop

    # Source 3: Parse from title/address text
    title = prop.get("full_street_line") or prop.get("address") or prop.get("list_price_text") or ""
    acres_from_title = parse_acreage_from_text(title)
    if acres_from_title:
        prop["acres"] = acres_from_title
        prop["acres_source"] = "title_parse"
        return prop

    # Source 4: Estimate from parcel type / price heuristic
    style = (prop.get("style") or "").upper()
    prop_type = (prop.get("property_type") or "").upper()

    if any(s in style or s in prop_type for s in ["LOT", "LAND", "VACANT"]):
        price = float(prop.get("list_price", 0) or 0)
        if price < 50_000:
            prop["acres"] = 0.15  # Small city lot
        elif price < 150_000:
            prop["acres"] = 0.25  # Standard lot
        elif price < 500_000:
            prop["acres"] = 1.0  # Larger lot
        else:
            prop["acres"] = 5.0  # Rural parcel
        prop["acres_source"] = "price_estimate"
        prop["acres_estimated"] = True

    return prop


def parse_acreage_from_text(text: str) -> Optional[float]:
    """
    Extracts acreage from free text using regex patterns.

    Examples:
        "1.5 acres" → 1.5
        "0.25 AC" → 0.25
        "2 acre lot" → 2.0
        "±3.2 acres" → 3.2
        "43,560 sq ft" → 1.0 (converted from sqft)

    Args:
        text: Free text to search for acreage patterns.

    Returns:
        Acreage as float, or None if no match found.
    """
    if not text:
        return None

    patterns = [
        r'(\d+\.?\d*)\s*acres?\b',           # "1.5 acres"
        r'(\d+\.?\d*)\s*ac\b',               # "1.5 ac"
        r'(\d+\.?\d*)\s*acre\s+lot',         # "1.5 acre lot"
        r'±\s*(\d+\.?\d*)\s*acres?',         # "±1.5 acres"
        r'approx\.?\s*(\d+\.?\d*)\s*acres?', # "approx 1.5 acres"
        r'(\d+,\d+)\s*sq\.?\s*ft',           # "43,560 sq ft" → convert
        r'(\d+)\s*sqft',                      # "43560 sqft" → convert
    ]

    text_lower = text.lower()
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            val_str = match.group(1).replace(",", "")
            try:
                val = float(val_str)
                # If it looks like sqft (> 1000), convert to acres
                if val > 1000:
                    val = round(val / SQFT_PER_ACRE, 4)
                if 0.01 <= val <= 10000:  # Sanity check
                    return val
            except ValueError:
                continue

    return None
