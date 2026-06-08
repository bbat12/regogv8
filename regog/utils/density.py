"""
Market Density Detection — classifies ZIP codes as urban, suburban, or rural
based on the first 3 digits (ZIP prefix). Uses a static lookup so no API
calls are needed. Falls back to 'suburban' if the ZIP is not found.
"""

from typing import Optional

# High-density (urban) ZIP prefixes — major metro cores
_URBAN_PREFIXES: set[str] = {
    "100",  # NYC (Manhattan)
    "101",  # NYC (Manhattan)
    "102",  # NYC (Manhattan)
    "900",  # Los Angeles
    "901",  # Los Angeles
    "902",  # LA metro (Beverly Hills, Santa Monica)
    "606",  # Chicago
    "607",  # Chicago metro
    "941",  # San Francisco
    "331",  # Miami
    "332",  # Miami
    "021",  # Boston
    "022",  # Boston
    "980",  # Seattle metro (Bellevue, Redmond)
    "981",  # Seattle
    "802",  # Denver
    "770",  # Houston
    "772",  # Houston
    "300",  # Atlanta metro
    "303",  # Atlanta
    "311",  # Atlanta
    "852",  # Phoenix metro (Scottsdale, Mesa, Tempe)
    "850",  # Phoenix
    "191",  # Philadelphia
    "192",  # Philadelphia
    "972",  # Portland
    "891",  # Las Vegas
    "889",  # Las Vegas
    "787",  # Austin
    "733",  # Austin
    "750",  # Dallas metro (Plano, Richardson)
    "751",  # Dallas metro
    "752",  # Dallas
    "753",  # Dallas
    "441",  # Cleveland
    "442",  # Cleveland metro
    "481",  # Detroit metro (Ann Arbor)
    "482",  # Detroit
    "483",  # Detroit metro
    "554",  # Minneapolis
    "612",  # Minneapolis (area code overlap — actually 554xx is Minneapolis)
    "946",  # Oakland
    "947",  # Berkeley
    "951",  # San Jose
    "112",  # Brooklyn
    "113",  # Queens
    "114",  # Queens
    "116",  # Queens
    "104",  # Bronx
    "103",  # Staten Island
    "110",  # Queens/Nassau border
    "111",  # Queens
    "115",  # Nassau County (dense suburban, borderline urban)
}

# Low-density (rural) ZIP prefixes — mostly farmland, mountains, desert
_RURAL_PREFIXES: set[str] = {
    # Montana
    "590", "591", "592", "593", "594", "595", "596", "597", "598", "599",
    # Wyoming
    "820", "821", "822", "823", "824", "825", "826", "827", "828", "829",
    "830", "831",
    # Idaho (rural)
    "832", "833", "834", "835", "836", "837", "838",
    # South Dakota
    "570", "571", "572", "573", "574", "575", "576", "577",
    # North Dakota
    "580", "581", "582", "583", "584", "585", "586", "587", "588",
    # Nevada (rural)
    "893", "894", "895", "896", "897", "898",
    # Hawaii / Alaska (rural)
    "967", "968", "969",
    "995", "996", "997", "998", "999",
    # Nebraska panhandle
    "691", "692", "693",
    # West Virginia (mostly rural)
    "247", "248", "249", "250", "251", "252", "253", "254", "255", "256",
    "257", "258", "259", "260", "261", "262", "263", "264", "265", "266",
    "267", "268",
    # Maine (rural)
    "039", "040", "041", "042", "043", "044", "045", "046", "047", "048",
    "049",
    # Mississippi delta / rural
    "386", "387", "388", "389", "390", "391", "392", "393", "394", "395",
    "396", "397",
    # New Mexico (mostly rural)
    "870", "871", "873", "874", "875", "877", "878", "879", "880", "881",
    "882", "883", "884",
    # Kentucky (rural)
    "412", "413", "414", "415", "416", "417", "418", "420", "421",
    # Arkansas (rural)
    "716", "717", "718", "719", "720", "721", "722", "723", "724", "725",
    "726", "727", "728", "729",
    # Iowa (rural)
    "500", "501", "502", "503", "504", "505", "506", "507", "508", "509",
    "510", "511", "512", "513", "514", "515", "516", "517", "518", "519",
    "520", "521", "522", "523", "524", "525", "526", "527", "528",
}


def get_market_density(zip_code: Optional[str]) -> str:
    """
    Classify a ZIP code as 'urban', 'suburban', or 'rural' based on
    its first 3 digits (ZIP prefix).

    Uses a hardcoded static lookup — no API calls needed.

    Args:
        zip_code: 5-digit ZIP code string (e.g. "10001", "75001").
                  Can be None or empty.

    Returns:
        'urban', 'suburban', or 'rural'.
        Falls back to 'suburban' if the ZIP is None, empty, or not found.
    """
    if not zip_code:
        return "suburban"

    # Extract first 3 digits
    prefix = zip_code.strip()[:3]

    if not prefix.isdigit():
        return "suburban"

    if prefix in _URBAN_PREFIXES:
        return "urban"

    if prefix in _RURAL_PREFIXES:
        return "rural"

    # Northeast corridor (0xx, 1xx) that isn't explicitly urban → suburban
    if prefix.startswith(("0", "1")):
        return "suburban"

    return "suburban"
