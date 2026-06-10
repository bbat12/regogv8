"""
Location Resolver — converts loose/colloquial location terms into
HomeHarvest-compatible search strings.

HomeHarvest (Realtor.com) expects standard location formats:
  - "City"                    (single city name)
  - "City, ST"               (city + state abbreviation)
  - "ZIP"                    (5-digit ZIP code)
  - "County, ST"             (county + state)

CRITICAL: HomeHarvest TIMES OUT on bare state-level queries like "Georgia"
or "Texas".  All colloquial regions resolve to SPECIFIC ANCHOR CITIES
rather than state names.
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# ── State names (lowercase → uppercase abbreviation) ─────────────────────
STATE_NAMES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA",
    "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}

# Reverse: abbreviation → full state name (title-cased)
ABBREV_TO_STATE: dict[str, str] = {
    v: k.title() for k, v in STATE_NAMES.items()
}

VALID_STATE_CODES: set[str] = set(ABBREV_TO_STATE.keys())

# ── State abbreviation variants ──────────────────────────────────────────
STATE_ABBREV_VARIANTS: dict[str, str] = {
    "al": "AL", "ak": "AK", "az": "AZ", "ar": "AR",
    "ca": "CA", "co": "CO", "ct": "CT", "de": "DE",
    "dc": "DC", "fl": "FL", "fla": "FL", "ga": "GA",
    "hi": "HI", "id": "ID", "il": "IL", "in": "IN",
    "ia": "IA", "ks": "KS", "ky": "KY", "la": "LA",
    "me": "ME", "md": "MD", "ma": "MA", "mi": "MI",
    "mn": "MN", "ms": "MS", "mo": "MO", "mt": "MT",
    "ne": "NE", "nv": "NV", "nh": "NH", "nj": "NJ",
    "nm": "NM", "ny": "NY", "nc": "NC", "nd": "ND",
    "oh": "OH", "ok": "OK", "or": "OR", "pa": "PA",
    "ri": "RI", "sc": "SC", "sd": "SD", "tn": "TN",
    "tx": "TX", "ut": "UT", "vt": "VT", "va": "VA",
    "wa": "WA", "wv": "WV", "wi": "WI", "wy": "WY",
    "cali": "CA", "penn": "PA", "mass": "MA",
}

# ── State → anchor city ──────────────────────────────────────────────────
# HomeHarvest TIMES OUT on bare state queries.  When resolution produces a
# bare state name, we redirect to a major metropolitan anchor city.
STATE_TO_ANCHOR: dict[str, str] = {
    "Alabama": "Birmingham, AL", "Alaska": "Anchorage, AK",
    "Arizona": "Phoenix, AZ", "Arkansas": "Little Rock, AR",
    "California": "Los Angeles, CA", "Colorado": "Denver, CO",
    "Connecticut": "Hartford, CT", "Delaware": "Wilmington, DE",
    "Florida": "Orlando, FL", "Georgia": "Atlanta, GA",
    "Hawaii": "Honolulu, HI", "Idaho": "Boise, ID",
    "Illinois": "Chicago, IL", "Indiana": "Indianapolis, IN",
    "Iowa": "Des Moines, IA", "Kansas": "Wichita, KS",
    "Kentucky": "Louisville, KY", "Louisiana": "New Orleans, LA",
    "Maine": "Portland, ME", "Maryland": "Baltimore, MD",
    "Massachusetts": "Boston, MA", "Michigan": "Detroit, MI",
    "Minnesota": "Minneapolis, MN", "Mississippi": "Jackson, MS",
    "Missouri": "Kansas City, MO", "Montana": "Billings, MT",
    "Nebraska": "Omaha, NE", "Nevada": "Las Vegas, NV",
    "New Hampshire": "Manchester, NH", "New Jersey": "Newark, NJ",
    "New Mexico": "Albuquerque, NM", "New York": "New York, NY",
    "North Carolina": "Charlotte, NC", "North Dakota": "Fargo, ND",
    "Ohio": "Columbus, OH", "Oklahoma": "Oklahoma City, OK",
    "Oregon": "Portland, OR", "Pennsylvania": "Philadelphia, PA",
    "Rhode Island": "Providence, RI", "South Carolina": "Columbia, SC",
    "South Dakota": "Sioux Falls, SD", "Tennessee": "Nashville, TN",
    "Texas": "Dallas, TX", "Utah": "Salt Lake City, UT",
    "Vermont": "Burlington, VT", "Virginia": "Virginia Beach, VA",
    "Washington": "Seattle, WA", "West Virginia": "Charleston, WV",
    "Wisconsin": "Milwaukee, WI", "Wyoming": "Cheyenne, WY",
}

# ── Directional / regional qualifiers ────────────────────────────────────
DIRECTIONAL_PREFIXES: list[str] = [
    "northwest ", "northeast ", "southwest ", "southeast ",
    "northern ", "southern ", "eastern ", "western ",
    "central ", "coastal ", "upper ", "lower ",
    "north ", "south ", "east ", "west ",
    "ne ", "nw ", "se ", "sw ",
    "n ", "s ", "e ", "w ",
]

# ── Common colloquial region → anchor city ───────────────────────────────
# ALL values are "City, ST" — never bare state names, because HomeHarvest
# times out on state-level queries.
COLLOQUIAL_REGIONS: dict[str, str] = {
    # ── Georgia ────────────────────────────────────────────────────────
    "north georgia": "Atlanta, GA",        "north ga": "Atlanta, GA",
    "n ga": "Atlanta, GA",                 "north ga.": "Atlanta, GA",
    "n ga.": "Atlanta, GA",
    "south georgia": "Valdosta, GA",       "south ga": "Valdosta, GA",
    "s ga": "Valdosta, GA",
    "east georgia": "Augusta, GA",          "east ga": "Augusta, GA",
    "west georgia": "Columbus, GA",         "west ga": "Columbus, GA",
    "central georgia": "Macon, GA",         "central ga": "Macon, GA",
    "northwest georgia": "Rome, GA",        "nw georgia": "Rome, GA",
    "northwest ga": "Rome, GA",            "nw ga": "Rome, GA",
    "northeast georgia": "Athens, GA",      "ne georgia": "Athens, GA",
    "northeast ga": "Athens, GA",          "ne ga": "Athens, GA",
    "southwest georgia": "Albany, GA",      "sw georgia": "Albany, GA",
    "southwest ga": "Albany, GA",          "sw ga": "Albany, GA",
    "southeast georgia": "Savannah, GA",    "se georgia": "Savannah, GA",
    "southeast ga": "Savannah, GA",        "se ga": "Savannah, GA",
    "georgia coast": "Savannah, GA",       "ga coast": "Savannah, GA",
    "ga coastal": "Savannah, GA",          "georgia coastal": "Savannah, GA",

    # ── Florida ────────────────────────────────────────────────────────
    "north florida": "Jacksonville, FL",    "north fl": "Jacksonville, FL",
    "n fl": "Jacksonville, FL",            "north fla": "Jacksonville, FL",
    "south florida": "Miami, FL",           "south fl": "Miami, FL",
    "s fl": "Miami, FL",                   "south fla": "Miami, FL",
    "central florida": "Orlando, FL",       "central fl": "Orlando, FL",
    "c fl": "Orlando, FL",
    "east florida": "Daytona Beach, FL",    "east fl": "Daytona Beach, FL",
    "west florida": "Tampa, FL",            "west fl": "Tampa, FL",
    "northwest florida": "Pensacola, FL",   "nw florida": "Pensacola, FL",
    "northwest fl": "Pensacola, FL",       "nw fl": "Pensacola, FL",
    "northeast florida": "Jacksonville, FL","ne florida": "Jacksonville, FL",
    "northeast fl": "Jacksonville, FL",    "ne fl": "Jacksonville, FL",
    "southwest florida": "Fort Myers, FL",  "sw florida": "Fort Myers, FL",
    "southwest fl": "Fort Myers, FL",      "sw fl": "Fort Myers, FL",
    "southeast florida": "Fort Lauderdale, FL", "se florida": "Fort Lauderdale, FL",
    "southeast fl": "Fort Lauderdale, FL", "se fl": "Fort Lauderdale, FL",
    "florida coast": "Tampa, FL",           "fl coast": "Tampa, FL",
    "florida panhandle": "Panama City, FL", "fl panhandle": "Panama City, FL",
    "panhandle": "Panama City, FL",
    "florida keys": "Key West, FL",         "fl keys": "Key West, FL",

    # ── Texas ──────────────────────────────────────────────────────────
    "north texas": "Dallas, TX",            "north tx": "Dallas, TX",
    "n tx": "Dallas, TX",
    "south texas": "San Antonio, TX",       "south tx": "San Antonio, TX",
    "s tx": "San Antonio, TX",
    "east texas": "Houston, TX",            "east tx": "Houston, TX",
    "west texas": "El Paso, TX",            "west tx": "El Paso, TX",
    "central texas": "Austin, TX",          "central tx": "Austin, TX",
    "northwest texas": "Amarillo, TX",      "nw texas": "Amarillo, TX",
    "northwest tx": "Amarillo, TX",        "nw tx": "Amarillo, TX",
    "northeast texas": "Dallas, TX",        "ne texas": "Dallas, TX",
    "northeast tx": "Dallas, TX",          "ne tx": "Dallas, TX",
    "southwest texas": "San Antonio, TX",   "sw texas": "San Antonio, TX",
    "southwest tx": "San Antonio, TX",     "sw tx": "San Antonio, TX",
    "southeast texas": "Houston, TX",       "se texas": "Houston, TX",
    "southeast tx": "Houston, TX",         "se tx": "Houston, TX",
    "texas coast": "Corpus Christi, TX",    "tx coast": "Corpus Christi, TX",
    "texas hill country": "Austin, TX",     "hill country": "Austin, TX",
    "texas panhandle": "Amarillo, TX",      "tx panhandle": "Amarillo, TX",

    # ── California ─────────────────────────────────────────────────────
    "north california": "San Francisco, CA",  "north ca": "San Francisco, CA",
    "n ca": "San Francisco, CA",
    "south california": "Los Angeles, CA",    "south ca": "Los Angeles, CA",
    "s ca": "Los Angeles, CA",
    "southern california": "Los Angeles, CA", "socal": "Los Angeles, CA",
    "so cal": "Los Angeles, CA",
    "northern california": "San Francisco, CA","norcal": "San Francisco, CA",
    "no cal": "San Francisco, CA",
    "central california": "Fresno, CA",       "central ca": "Fresno, CA",
    "central valley": "Fresno, CA",
    "east bay": "Oakland, CA",
    "silicon valley": "San Jose, CA",
    "california coast": "Los Angeles, CA",    "ca coast": "Los Angeles, CA",
    "california coastal": "Los Angeles, CA",  "ca coastal": "Los Angeles, CA",

    # ── Other states ───────────────────────────────────────────────────
    # Panhandle regions
    "oklahoma panhandle": "Guymon, OK",     "ok panhandle": "Guymon, OK",
    "alaska panhandle": "Juneau, AK",
    "idaho panhandle": "Coeur d'Alene, ID",

    # Coast / Shore regions
    "carolina coast": "Myrtle Beach, SC",   "carolina coastal": "Myrtle Beach, SC",
    "north carolina coast": "Wilmington, NC","nc coast": "Wilmington, NC",
    "south carolina coast": "Charleston, SC","sc coast": "Charleston, SC",
    "oregon coast": "Newport, OR",
    "washington coast": "Seattle, WA",
    "gulf coast": "Mobile, AL",             "gulf coastal": "Mobile, AL",
    "gulf shores": "Mobile, AL",

    # General megaregions
    "east coast": "New York, NY",           "east coastal": "New York, NY",
    "eastern seaboard": "New York, NY",
    "west coast": "Los Angeles, CA",
    "midwest": "Chicago, IL",               "mid-west": "Chicago, IL",
    "northeast": "Boston, MA",              "north east": "Boston, MA",
    "southeast": "Atlanta, GA",             "south east": "Atlanta, GA",
    "southwest": "Phoenix, AZ",             "south west": "Phoenix, AZ",
    "pacific northwest": "Seattle, WA",     "pacific nw": "Seattle, WA",
    "pnw": "Seattle, WA",
    "new england": "Boston, MA",
    "the south": "Atlanta, GA",             "deep south": "Atlanta, GA",
    "the midwest": "Chicago, IL",           "the northeast": "Boston, MA",
    "appalachia": "Knoxville, TN",
    "the rockies": "Denver, CO",            "rocky mountains": "Denver, CO",
}

# ── Words that are not useful location terms (strip or flag) ────────────
FUZZY_WORDS: set[str] = {
    "area", "region", "county", "counties", "parish", "city",
    "town", "somewhere", "anywhere", "around", "near", "nearby",
    "the", "and", "or", "my", "i", "we", "looking", "search",
    "any", "all", "throughout", "across", "entire",
    "coast", "coastal", "coasts", "shore", "shores",
    "panhandle",
}

ZIP_PATTERN = re.compile(r"^\d{5}(-\d{4})?$")


# ═════════════════════════════════════════════════════════════════════════
#  Public API
# ═════════════════════════════════════════════════════════════════════════


def resolve_location(raw_location: str) -> str:
    """
    Convert a loose / colloquial location string into a valid
    HomeHarvest-compatible "City, ST" search string.

    HomeHarvest TIMES OUT on bare state-level queries such as "Georgia".
    This function ensures every result is a city-level (or ZIP) search.
    """
    original = raw_location.strip()
    if not original:
        return original

    normalized = _normalize(original)

    # ── 1. Already a valid format — pass through ──────────────────────
    if _is_valid_format(normalized):
        logger.debug(f"Location '{original}' looks valid — passing through")
        return original

    # ── 2. Exact colloquial match ─────────────────────────────────────
    if normalized in COLLOQUIAL_REGIONS:
        resolved = COLLOQUIAL_REGIONS[normalized]
        logger.info(f"Resolved colloquial location '{original}' → '{resolved}'")
        return resolved

    # ── 3. Just a state abbreviation → anchor city ────────────────────
    if normalized in STATE_ABBREV_VARIANTS:
        state_name = ABBREV_TO_STATE[STATE_ABBREV_VARIANTS[normalized]]
        resolved = STATE_TO_ANCHOR.get(state_name, state_name)
        logger.info(f"Resolved abbreviation '{original}' → '{resolved}'")
        return resolved

    # ── 4. "City, ST" with abbreviation or full name ──────────────────
    comma_match = re.match(r"^(.+?),\s*(.+)$", normalized)
    if comma_match:
        city_part = comma_match.group(1).strip()
        state_part = comma_match.group(2).strip()

        if state_part in STATE_ABBREV_VARIANTS:
            normalised_state = STATE_ABBREV_VARIANTS[state_part]
            resolved = f"{city_part.title()}, {normalised_state}"
            if resolved != original:
                logger.info(f"Normalised state in '{original}' → '{resolved}'")
            return resolved

        if state_part in STATE_NAMES:
            resolved = f"{city_part.title()}, {STATE_NAMES[state_part]}"
            if resolved != original:
                logger.info(f"Normalised state in '{original}' → '{resolved}'")
            return resolved

    # ── 5a. Full normalized string is a state name (e.g. "north carolina")
    #      → redirect to anchor city BEFORE directional stripping.
    if normalized in STATE_NAMES:
        state_name = normalized.title()
        resolved = STATE_TO_ANCHOR.get(state_name, state_name)
        logger.info(f"Resolved state name '{original}' → '{resolved}'")
        return resolved

    # ── 5. Directional prefix + name ──────────────────────────────────
    city_resolved = _strip_directional_prefix(normalized)
    if city_resolved and city_resolved != normalized:
        if city_resolved in STATE_ABBREV_VARIANTS:
            state_name = ABBREV_TO_STATE[STATE_ABBREV_VARIANTS[city_resolved]]
            resolved = STATE_TO_ANCHOR.get(state_name, state_name)
            logger.info(f"Resolved directional+abbrev '{original}' → '{resolved}'")
            return resolved
        if city_resolved in STATE_NAMES:
            resolved = STATE_TO_ANCHOR.get(city_resolved.title(), city_resolved.title())
            logger.info(f"Resolved directional+state '{original}' → '{resolved}'")
            return resolved
        if city_resolved in COLLOQUIAL_REGIONS:
            resolved = COLLOQUIAL_REGIONS[city_resolved]
            logger.info(f"Resolved directional+colloq '{original}' → '{resolved}'")
            return resolved

        stripped_further = _strip_fuzzy_words(city_resolved)
        better = stripped_further if stripped_further and stripped_further != city_resolved else None
        if better:
            if better in STATE_ABBREV_VARIANTS:
                state_name = ABBREV_TO_STATE[STATE_ABBREV_VARIANTS[better]]
                resolved = STATE_TO_ANCHOR.get(state_name, state_name)
            elif better in STATE_NAMES:
                resolved = STATE_TO_ANCHOR.get(better.title(), better.title())
            elif better in COLLOQUIAL_REGIONS:
                resolved = COLLOQUIAL_REGIONS[better]
            else:
                resolved = better.title()
        else:
            resolved = city_resolved.title()
        if resolved != original:
            logger.info(f"Stripped directional prefix: '{original}' → '{resolved}'")
        return resolved

    # ── 6. Strip fuzzy filler words ───────────────────────────────────
    stripped = _strip_fuzzy_words(normalized)
    if stripped and stripped != normalized:
        if stripped in STATE_ABBREV_VARIANTS:
            state_name = ABBREV_TO_STATE[STATE_ABBREV_VARIANTS[stripped]]
            resolved = STATE_TO_ANCHOR.get(state_name, state_name)
            logger.info(f"Stripped filler from '{original}' → '{resolved}'")
            return resolved
        if stripped in STATE_NAMES:
            resolved = STATE_TO_ANCHOR.get(stripped.title(), stripped.title())
            logger.info(f"Stripped filler from '{original}' → '{resolved}'")
            return resolved
        if stripped in COLLOQUIAL_REGIONS:
            resolved = COLLOQUIAL_REGIONS[stripped]
            logger.info(f"Stripped filler from '{original}' → '{resolved}'")
            return resolved
        resolved = stripped.title()
        logger.info(f"Stripped filler from '{original}' → '{resolved}'")
        return resolved

    # ── 7. Nothing worked — return original ───────────────────────────
    logger.debug(f"Unable to resolve location '{original}' — using as-is")

    # ── 8. Bare state name → anchor city ─────────────────────────────
    # If someone typed a state name directly ("Georgia", "georgia", etc.)
    # _is_valid_format may have passed it through, but HomeHarvest will
    # time out on bare state-level queries. Convert to a major city.
    original_title = original.strip().title()
    if original_title in STATE_TO_ANCHOR:
        resolved = STATE_TO_ANCHOR[original_title]
        logger.info(f"Converted bare state name '{original}' → '{resolved}'")
        return resolved

    return original


def resolve_with_details(raw_location: str) -> dict:
    """Return resolution detail dict including original, resolved, method & changed."""
    original = raw_location.strip()
    resolved = resolve_location(original)
    changed = resolved.lower() != original.lower()
    method = _detect_method(original, resolved)
    return {
        "original": original,
        "resolved": resolved,
        "method": method,
        "changed": changed,
    }


# ═════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ═════════════════════════════════════════════════════════════════════════


def _normalize(s: str) -> str:
    """Lower-case, collapse whitespace, strip leading/trailing punctuation only."""
    s = s.lower().strip()
    s = s.strip(".,;:!?")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _is_valid_format(normalized: str) -> bool:
    """Heuristic: does the string already look like a usable HomeHarvest location?"""
    if ZIP_PATTERN.match(normalized):
        return True
    # "City, ST" pattern
    comma_match = re.match(r"^(.+?),\s*([a-z]{2})$", normalized)
    if comma_match:
        state_part = comma_match.group(2).upper()
        if state_part in VALID_STATE_CODES:
            return True
    # A single word that is NOT an abbreviation or colloquial term — likely a city name
    if " " not in normalized and "," not in normalized:
        if normalized not in STATE_ABBREV_VARIANTS and normalized not in COLLOQUIAL_REGIONS and normalized not in STATE_NAMES:
            return True
    return False


def _strip_directional_prefix(s: str) -> str:
    """Remove a directional prefix if present."""
    for prefix in DIRECTIONAL_PREFIXES:
        if s.startswith(prefix):
            stripped = s[len(prefix):].strip()
            if stripped:
                return stripped
    return s


def _strip_fuzzy_words(s: str) -> str:
    """Remove trailing fuzzy/filler words."""
    words = s.split()
    if not words:
        return s
    while words and words[-1] in FUZZY_WORDS:
        words.pop()
    return " ".join(words) if words else s


def _detect_method(original: str, resolved: str) -> str:
    """Identify which resolution method was used."""
    orig_lower = original.lower().strip()
    if orig_lower == resolved.lower():
        return "unchanged" if orig_lower not in COLLOQUIAL_REGIONS else "colloquial_match"
    if orig_lower in COLLOQUIAL_REGIONS:
        return "colloquial_match"
    if _normalize(orig_lower) in STATE_ABBREV_VARIANTS:
        return "abbreviation_expansion"
    if _strip_directional_prefix(_normalize(orig_lower)) != _normalize(orig_lower):
        return "directional_prefix_stripped"
    if _strip_fuzzy_words(_normalize(orig_lower)) != _normalize(orig_lower):
        return "filler_words_stripped"
    return "unknown_resolution"
