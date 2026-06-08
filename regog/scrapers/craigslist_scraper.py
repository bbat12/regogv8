"""
Craigslist housing scraper — finds FSBO and motivated seller listings.
No API key. Pure httpx + BeautifulSoup.
Provides a supplemental source of off-market / FSBO deals.
"""

import re
import time
import random
import hashlib
import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from utils.rate_limiter import rate_limit, report_success, report_error

logger = logging.getLogger(__name__)

# Craigslist city subdomain map (add more as needed)
CL_CITY_MAP = {
    "dallas": "dallas", "houston": "houston", "austin": "austin",
    "san antonio": "sanantonio", "fort worth": "dfw",
    "chicago": "chicago", "los angeles": "losangeles", "new york": "newyork",
    "phoenix": "phoenix", "denver": "denver",
    "atlanta": "atlanta", "miami": "miami", "seattle": "seattle",
    "portland": "portland", "las vegas": "lasvegas", "nashville": "nashville",
    "orlando": "orlando", "tampa": "tampa", "charlotte": "charlotte",
    "raleigh": "raleigh", "indianapolis": "indianapolis", "columbus": "columbus",
    "salt lake city": "saltlakecity", "kansas city": "kansascity",
    "san diego": "sandiego", "san francisco": "sfbay", "sanjose": "sfbay",
    "boston": "boston", "detroit": "detroit", "philadelphia": "philadelphia",
    "minneapolis": "minneapolis", "st louis": "stlouis", "baltimore": "baltimore",
}


def get_cl_subdomain(location: str) -> Optional[str]:
    """Get the Craigslist subdomain for a city."""
    city = location.split(",")[0].lower().strip()
    return CL_CITY_MAP.get(city)


def scrape_craigslist_housing(
    location: str,
    price_max: int = None,
    scan_type: str = "residential",
    limit: int = 100,
) -> list[dict]:
    """
    Scrape Craigslist housing posts for motivated seller / FSBO listings.
    Returns normalized property dicts compatible with REGOG pipeline.

    Args:
        location: City name (e.g. "Dallas, TX")
        price_max: Maximum listing price filter
        scan_type: 'residential', 'land', or 'commercial'
        limit: Max listings to return

    Returns:
        List of normalized property dicts
    """
    subdomain = get_cl_subdomain(location)
    if not subdomain:
        logger.info(f"[Craigslist] No subdomain mapping for: {location}")
        return []

    # CL categories: reo = real estate by owner, rea = land, reb = commercial
    category_map = {"residential": "reo", "land": "rea", "commercial": "reb"}
    category = category_map.get(scan_type, "reo")

    url = f"https://{subdomain}.craigslist.org/search/{category}"
    params = {"sort": "date"}
    if price_max:
        params["max_price"] = price_max

    results = []

    try:
        rate_limit("craigslist")
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = httpx.get(url, params=params, headers=headers, timeout=15, follow_redirects=True)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # CL has multiple listing layouts — try the current one
        posts = soup.select("li.cl-search-result") or soup.select(".result-row") or soup.select(".cl-static-search-result")

        for post in posts[:limit]:
            try:
                prop = _parse_cl_post(post, location, scan_type, subdomain)
                if prop:
                    results.append(prop)
            except Exception:
                continue

        report_success("craigslist")
    except Exception as e:
        report_error("craigslist")
        logger.warning(f"[Craigslist] Error: {e}")

    return results


def _parse_cl_post(post, location: str, scan_type: str, subdomain: str) -> Optional[dict]:
    """Parse a single Craigslist post element into a property dict."""
    # Try multiple selectors for title/price
    title_el = (
        post.select_one(".cl-app-anchor .label")
        or post.select_one(".result-title")
        or post.select_one("a[href*='dallas.craigslist']")
        or post.select_one("a[href*='realestate']")
        or post.select_one("a")
    )
    if not title_el:
        return None
    title = title_el.get_text(strip=True)
    if not title:
        return None

    price_el = post.select_one(".priceinfo") or post.select_one(".result-price") or post.select_one(".price")
    price_text = ""
    if price_el:
        price_text = price_el.get_text(strip=True).replace("$", "").replace(",", "")
    price = int(price_text) if price_text.isdigit() else None

    if not price:
        return None

    # Get the link
    href = title_el.get("href", "")
    if isinstance(href, list):
        href = href[0] if href else ""
    if href and not href.startswith("http"):
        href = f"https://{subdomain}.craigslist.org{href}"

    # Extract beds/baths/sqft from housing meta
    beds_el = post.select_one(".housing") or post.select_one(".meta")
    beds = baths = sqft = None
    if beds_el:
        housing_text = beds_el.get_text()
        bed_match = re.search(r"(\d+)br", housing_text)
        bath_match = re.search(r"([\d.]+)ba", housing_text)
        sqft_match = re.search(r"([\d,]+)ft", housing_text)
        beds = int(bed_match.group(1)) if bed_match else None
        baths = float(bath_match.group(1)) if bath_match else None
        sqft = int(sqft_match.group(1).replace(",", "")) if sqft_match else None

    city = location.split(",")[0].strip()
    state = location.split(",")[1].strip() if "," in location else ""

    # Craigslist titles often contain seller motivation signals
    # These will be caught by the Brain classifier during pipeline processing
    return {
        "listing_id": f"cl_{hashlib.md5((title + str(price)).encode()).hexdigest()[:12]}",
        "source": "craigslist",
        "scan_type": scan_type,
        "style": "SINGLE_FAMILY",
        "address": title,
        "city": city,
        "state": state,
        "list_price": price,
        "beds": beds,
        "baths": baths,
        "sqft": sqft,
        "property_url": href,
        "listing_status": "for_sale",
        "listing_description": title,
    }
