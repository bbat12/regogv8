"""
County Permit Scraper — analyzes building permit signals for properties.

Two-tier approach for V1:
1. Keyword-based permit inference from the listing description
   (catches red flags like "unpermitted addition", "code violation")
2. County-specific web scraping framework for high-value metros
   (Dallas, Houston, Phoenix, etc. via public Accela/portal scraping)

The DB schema stores results as JSON in the `permit_flags` column:
  {
    "unpermitted_additions": bool,
    "recent_permits": [...],
    "code_violations": [...],
    "permit_risk": "low"|"medium"|"high"|"unknown"
  }
"""

import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ─── Keyword-based permit inference ───────────────────────────────────────

# Keywords in listing descriptions that suggest permit issues
UNPERMITTED_SIGNALS = [
    "unpermitted", "no permit", "without permit", "unapproved",
    "added without permit", "illegal addition", "non-permitted",
    "unpermitted addition", "unpermitted work", "unpermitted conversion",
]

CODE_VIOLATION_SIGNALS = [
    "code violation", "building code", "code issues", "code problems",
    "red tag", "red-tagged", "condemned", "uninhabitable",
    "notice of violation", "stop work", "cease and desist",
]

RENOVATION_PERMIT_SIGNALS = [
    "permit", "permitted", "permits", "building permit",
    "approved plans", "permit filed", "permit issued",
]


def infer_permits_from_description(description: Optional[str]) -> dict:
    """
    Analyze a listing description for permit-related signals.

    Returns dict with:
        unpermitted_additions: bool
        code_violations: list[str]
        recent_permits: list[str]
        permit_risk: str
        has_permits: bool
    """
    if not description:
        return {
            "unpermitted_additions": False,
            "code_violations": [],
            "recent_permits": [],
            "permit_risk": "unknown",
            "has_permits": False,
        }

    text = description.lower()
    violations = []
    permits = []
    unpermitted = False

    # Check for unpermitted work signals
    for signal in UNPERMITTED_SIGNALS:
        if signal in text:
            unpermitted = True
            violations.append(f"Possible unpermitted work detected: '{signal}'")

    # Check for code violation signals
    for signal in CODE_VIOLATION_SIGNALS:
        if signal in text:
            violations.append(f"Code issue flagged: '{signal}'")

    # Check for mention of permits (positive signal — work was permitted)
    for signal in RENOVATION_PERMIT_SIGNALS:
        if signal in text and signal not in UNPERMITTED_SIGNALS:
            permits.append(f"Permit mentioned: '{signal}'")

    # Determine risk level
    if unpermitted or violations:
        permit_risk = "high"
    elif permits:
        permit_risk = "low"
    else:
        permit_risk = "unknown"

    return {
        "unpermitted_additions": unpermitted,
        "code_violations": violations,
        "recent_permits": permits,
        "permit_risk": permit_risk,
        "has_permits": len(permits) > 0,
    }


# ─── County-specific permit portal scraping ──────────────────────────────

# Registry of county permit portal URLs and search patterns
# For V1, this covers major counties with known public portals
COUNTY_PORTALS: dict[str, dict] = {
    "Dallas County": {
        "url": "https://aca-prod.accela.com/DALLASTX/Welcome.aspx",
        "type": "accela",
        "notes": "City of Dallas Accela portal — requires session-based search",
    },
    "Harris County": {
        "url": "https://www.hctx.net/permits",
        "type": "custom",
        "notes": "Harris County permit search",
    },
    "Maricopa County": {
        "url": "https://www.maricopa.gov/1855/Building-Permits",
        "type": "custom",
        "notes": "Maricopa County building permits",
    },
    "Tarrant County": {
        "url": "https://www.tarrantcounty.com/permits",
        "type": "custom",
        "notes": "Tarrant County permit search",
    },
}

# Cache for county scraped results
_county_permit_cache: dict[str, dict] = {}


def scrape_county_permits(
    county: Optional[str],
    address: Optional[str],
    city: Optional[str],
) -> dict:
    """
    Attempt to scrape permit data from a county's public portal.

    For V1, this is a best-effort scraper. Most county portals use
    complex web applications (Accela, etc.) that resist scraping.
    Returns whatever data is available or empty results.

    Args:
        county: County name (e.g. "Dallas County").
        address: Property street address.
        city: Property city.

    Returns:
        Dict with permit findings or empty if unavailable.
    """
    if not county or not address:
        return {"scraped_permits": [], "scrape_status": "skipped"}

    cache_key = f"{county}:{address}"
    if cache_key in _county_permit_cache:
        return _county_permit_cache[cache_key]

    portal = COUNTY_PORTALS.get(county)
    if not portal:
        logger.debug(f"No permit portal configured for {county}")
        return {"scraped_permits": [], "scrape_status": "no_portal"}

    logger.info(f"Attempting permit lookup for {address} via {county} portal")

    # For V1, most Accela portals require interactive sessions (CAPTCHA, JS)
    # that can't be easily scraped. Return empty and log the limitation.
    # Future: use Playwright for JS-heavy Accela portals.
    if portal["type"] == "accela":
        logger.debug(
            f"Accela portal requires interactive browser — "
            f"skipping automated scrape for {address}"
        )
        _county_permit_cache[cache_key] = {
            "scraped_permits": [],
            "scrape_status": "accela_requires_browser",
        }
        return _county_permit_cache[cache_key]

    # For simpler portals, attempt an HTTP GET and parse
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        response = httpx.get(
            portal["url"],
            headers=headers,
            timeout=10,
            follow_redirects=True,
        )

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            page_text = soup.get_text().lower()

            # Look for address match in page content
            addr_parts = address.lower().split()
            if any(part in page_text for part in addr_parts[:3]):
                logger.info(f"Found potential permit data for {address} on {county} portal")
                result = {
                    "scraped_permits": ["See county portal for details"],
                    "scrape_status": "page_found",
                }
                _county_permit_cache[cache_key] = result
                return result

        logger.debug(f"No permit data found for {address} on {county} portal")
        _county_permit_cache[cache_key] = {
            "scraped_permits": [],
            "scrape_status": "not_found",
        }
        return _county_permit_cache[cache_key]

    except Exception as e:
        logger.debug(f"Error scraping {county} portal for {address}: {e}")
        _county_permit_cache[cache_key] = {
            "scraped_permits": [],
            "scrape_status": f"error: {e}",
        }
        return _county_permit_cache[cache_key]


# ─── Main entry point ────────────────────────────────────────────────────

def fetch_permits(
    address: Optional[str],
    zip_code: Optional[str],
    county: Optional[str] = None,
    city: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """
    Fetch permit-related data for a property.

    Combines:
    1. Keyword inference from listing description
    2. County portal scraping (best-effort)

    Args:
        address: Property street address.
        zip_code: ZIP code.
        county: County name (e.g. "Dallas County").
        city: Property city.
        description: Listing description text.

    Returns:
        Dict with permit_flags suitable for DB storage:
            unpermitted_additions: bool
            recent_permits: list[str]
            code_violations: list[str]
            permit_risk: str
    """
    # 1. Keyword inference from description
    desc_result = infer_permits_from_description(description)

    # 2. County portal scraping
    portal_result = scrape_county_permits(county, address, city)

    # 3. Combine results
    result = {
        "unpermitted_additions": desc_result.get("unpermitted_additions", False),
        "recent_permits": (
            desc_result.get("recent_permits", [])
            + portal_result.get("scraped_permits", [])
        ),
        "code_violations": desc_result.get("code_violations", []),
        "permit_risk": desc_result.get("permit_risk", "unknown"),
    }

    # Elevate risk if county scraping found issues
    if portal_result.get("scrape_status") == "page_found" and result["permit_risk"] == "unknown":
        result["permit_risk"] = "medium"

    # Deduplicate recent_permits
    result["recent_permits"] = list(set(result["recent_permits"]))

    return result


def clear_cache():
    """Clear the in-memory permit cache."""
    _county_permit_cache.clear()
    logger.debug("Permit scraper cache cleared")
