"""
Deduplication utility — merges listings from multiple sources,
deduplicating by normalized address similarity.
"""
import re
from typing import Optional


def normalize_address(addr: Optional[str]) -> str:
    """
    Normalize an address string for comparison.
    Strips suffixes, punctuation, and normalizes whitespace.
    """
    if not addr:
        return ""
    addr = addr.lower()
    # Remove common suffixes
    addr = re.sub(
        r'\b(st|street|ave|avenue|blvd|boulevard|dr|drive|rd|road|ln|lane|'
        r'ct|court|pl|place|cir|circle|way|ter|terrace|hwy|highway|'
        r'apt|unit|ste|suite|#)\b',
        '', addr
    )
    # Remove punctuation
    addr = re.sub(r'[^a-z0-9\s]', '', addr)
    # Normalize whitespace
    addr = re.sub(r'\s+', ' ', addr).strip()
    return addr


def merge_and_deduplicate(
    primary: list[dict],
    secondary: Optional[list[dict]] = None,
    tertiary: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Merge multiple listing sources, deduplicating by normalized address.

    Primary source wins on address conflicts.
    Secondary source supplements where address is new.
    Tertiary source supplements where address is new.

    Args:
        primary: Primary listing source (HomeHarvest)
        secondary: Optional secondary source (Redfin/Zillow)
        tertiary: Optional tertiary source (Craigslist)

    Returns:
        Combined list with duplicates removed
    """
    seen: dict[str, bool] = {}
    result: list[dict] = []

    for prop in primary:
        key = normalize_address(prop.get("address", ""))
        if key and len(key) > 3:
            seen[key] = True
        result.append(prop)

    for source in [secondary, tertiary]:
        if not source:
            continue
        for prop in source:
            key = normalize_address(prop.get("address", ""))
            if key and len(key) > 3 and key not in seen:
                seen[key] = True
                result.append(prop)

    return result


def find_duplicates(listings: list[dict]) -> list[tuple[int, int]]:
    """
    Find duplicate listings within a single list.
    Returns list of (original_index, duplicate_index) tuples.

    Useful for debugging cross-source overlap.
    """
    seen: dict[str, int] = {}
    duplicates: list[tuple[int, int]] = []

    for i, prop in enumerate(listings):
        key = normalize_address(prop.get("address", ""))
        if key and len(key) > 3:
            if key in seen:
                duplicates.append((seen[key], i))
            else:
                seen[key] = i

    return duplicates
