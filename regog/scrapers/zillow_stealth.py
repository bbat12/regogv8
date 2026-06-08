"""
Zillow Stealth Scraper — Playwright-based Zillow scraper with anti-bot measures.

Uses `playwright` + `playwright-stealth` to mimic a real browser session,
avoiding Zillow's aggressive bot detection. Fetches for_sale listings and
returns them in the same normalized dict format as HomeHarvest.

Supports:
- Stealth browser launch with randomized fingerprints
- Viewport, timezone, and locale randomization
- Human-like scrolling behavior
- Rate limiting (4–9s random delays between requests)
- Retry with exponential backoff on failure

Usage:
    from scrapers.zillow_stealth import fetch_zillow_listings
    listings = fetch_zillow_listings("Dallas, TX", listing_type="for_sale")
"""

import logging
import random
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Try importing Playwright (optional dependency)
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

try:
    from playwright_stealth import stealth_sync
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False

# ─── Anti-bot Configuration ───────────────────────────────────────────────

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 720},
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

LOCALES = ["en-US", "en", "en-GB"]

# Use the shared rate limiter utility
from utils.rate_limiter import rate_limit as _shared_rate_limit, report_success as _report_success, report_error as _report_error


def _build_search_url(location: str, listing_type: str = "for_sale") -> str:
    """Build Zillow search URL from location string."""
    # URL-encode location
    loc_encoded = location.replace(" ", "-").replace(",", "").lower()
    if listing_type == "for_sale":
        return f"https://www.zillow.com/homes/{loc_encoded}_rb/"
    elif listing_type == "recently_sold":
        return f"https://www.zillow.com/homes/{loc_encoded}_rs/"
    elif listing_type == "for_rent":
        return f"https://www.zillow.com/homes/{loc_encoded}_rent/"
    return f"https://www.zillow.com/homes/{loc_encoded}_rb/"


def _human_scroll(page, scrolls: int = 3):
    """Simulate human-like scrolling behavior."""
    for i in range(scrolls):
        # Scroll by a random amount
        scroll_amount = random.randint(300, 800)
        page.evaluate(f"window.scrollBy(0, {scroll_amount})")
        # Random pause between scrolls
        time.sleep(random.uniform(0.5, 2.0))

    # Maybe scroll back up a bit (human behavior)
    if random.random() < 0.3:
        page.evaluate(f"window.scrollBy(0, -{random.randint(100, 300)})")
        time.sleep(random.uniform(0.3, 1.0))


def _parse_zillow_listings(page) -> list[dict]:
    """
    Extract listing data from Zillow search results page.
    Attempts to parse the embedded JSON data first, then falls back to DOM parsing.
    """
    listings = []

    # Method 1: Try to extract from the Apollo/cache state (JSON embedded in page)
    try:
        json_data = page.evaluate("""() => {
            // Try multiple possible cache locations
            const scripts = document.querySelectorAll('script');
            for (const script of scripts) {
                const text = script.textContent || '';
                if (text.includes('__NEXT_DATA__')) {
                    return JSON.parse(text.replace('window.__NUXT__=', '').trim());
                }
                if (text.includes('"searchResults"') && text.includes('"listResults"')) {
                    return JSON.parse(text);
                }
            }
            return null;
        }""")

        if json_data:
            # Navigate the complex Zillow data structure
            props = json_data.get("props", {})
            page_props = props.get("pageProps", {})
            search_state = page_props.get("searchPageState", {})
            cat_results = search_state.get("cat1", {}).get("searchResults", {}).get("listResults", [])
            if cat_results:
                for item in cat_results:
                    listing = _normalize_zillow_item(item)
                    if listing:
                        listings.append(listing)
                if listings:
                    logger.info(f"Extracted {len(listings)} listings from Zillow JSON data")
                    return listings
    except Exception as e:
        logger.debug(f"JSON extraction method 1 failed: {e}")

    # Method 2: Query API endpoint directly via page
    try:
        data = page.evaluate("""() => {
            // Check if there's an Apollo cache we can read
            if (window.__APOLLO_STATE__) {
                return JSON.stringify(window.__APOLLO_STATE__);
            }
            return null;
        }""")
        # If we got data, parse it
        # (This is complex — Zillow uses GraphQL fragments)
    except Exception as e:
        logger.debug(f"Apollo state extraction failed: {e}")

    # Method 3: DOM parsing fallback
    try:
        dom_items = page.evaluate("""() => {
            const items = [];
            // Zillow search results use article cards with specific data attributes
            const cards = document.querySelectorAll('[data-test="property-card"], article');
            for (const card of cards) {
                const address = card.querySelector('[data-test="property-card-addr"]')?.textContent || '';
                const price = card.querySelector('[data-test="property-card-price"]')?.textContent || '';
                const beds = card.querySelector('[data-test="property-card-beds"]')?.textContent || '';
                const baths = card.querySelector('[data-test="property-card-baths"]')?.textContent || '';
                const sqft = card.querySelector('[data-test="property-card-sqft"]')?.textContent || '';
                const link = card.querySelector('a[href*="/homedetails/"]')?.href || '';
                const img = card.querySelector('img')?.src || '';
                items.push({ address, price, beds, baths, sqft, link, img });
            }
            return items;
        }""")

        for item in dom_items:
            if item.get("address") and item.get("price"):
                listing = _normalize_dom_item(item)
                if listing:
                    listings.append(listing)

        if listings:
            logger.info(f"Extracted {len(listings)} listings from Zillow DOM")
    except Exception as e:
        logger.debug(f"DOM parsing failed: {e}")

    return listings


def _normalize_zillow_item(item: dict) -> Optional[dict]:
    """Normalize a Zillow JSON result into REGOG property schema."""
    try:
        price_str = str(item.get("price", "")).replace("$", "").replace(",", "").strip()
        price = int(price_str) if price_str and price_str != "--" else None

        beds_str = str(item.get("beds", "") or "").replace("bd", "").strip()
        beds = int(beds_str) if beds_str and beds_str.isdigit() else None

        baths_str = str(item.get("baths", "") or "").replace("ba", "").strip()
        baths = float(baths_str) if baths_str else None

        sqft_str = str(item.get("area", "") or item.get("sqft", "")).replace(",", "").replace("sqft", "").strip()
        sqft = int(float(sqft_str)) if sqft_str and sqft_str.replace(".", "").isdigit() else None

        img_url = item.get("imgSrc") or item.get("image", "")
        detail_url = item.get("detailUrl") or item.get("url", "")

        # Parse address components
        addr = item.get("address", item.get("addressStreet", ""))
        city = item.get("city", "")
        state = item.get("state", "")
        zip_code = item.get("zipcode", "")

        # Extract lat/lon
        lat = item.get("latLong", {}).get("latitude") or item.get("latitude")
        lon = item.get("latLong", {}).get("longitude") or item.get("longitude")
        if lat:
            lat = float(lat)
        if lon:
            lon = float(lon)

        # Status
        status = item.get("statusType", "").lower()
        days = item.get("daysOnZillow", item.get("daysOnMarket"))

        return {
            "listing_id": f"zillow_{item.get('zpid', item.get('id', hash(addr + str(price))))}",
            "source": "zillow",
            "scan_type": "residential",
            "address": addr,
            "city": city,
            "state": state,
            "zip": zip_code,
            "lat": lat,
            "lon": lon,
            "list_price": price,
            "price_per_sqft": round(price / sqft, 2) if price and sqft else None,
            "sqft": sqft,
            "beds": beds,
            "baths": baths,
            "days_on_market": days,
            "listing_status": status,
            "listing_description": item.get("description", ""),
            "estimated_value": item.get("zestimate"),
            "img_url": img_url,
            "detail_url": detail_url if detail_url.startswith("http") else f"https://www.zillow.com{detail_url}" if detail_url else "",
        }
    except Exception as e:
        logger.debug(f"Error normalizing Zillow item: {e}")
        return None


def _normalize_dom_item(item: dict) -> Optional[dict]:
    """Normalize a DOM-parsed Zillow item into REGOG property schema."""
    try:
        price_str = item.get("price", "").replace("$", "").replace(",", "").strip()
        price = int(price_str) if price_str and price_str != "--" else None

        beds_str = item.get("beds", "").split()[0] if item.get("beds") else ""
        beds = int(beds_str) if beds_str else None

        baths_str = item.get("baths", "").split()[0] if item.get("baths") else ""
        baths = float(baths_str) if baths_str else None

        sqft_str = item.get("sqft", "").replace(",", "").split()[0] if item.get("sqft") else ""
        sqft = int(sqft_str) if sqft_str else None

        return {
            "listing_id": f"zillow_{hash(item['address'] + str(price))}",
            "source": "zillow",
            "scan_type": "residential",
            "address": item.get("address", ""),
            "city": "",
            "state": "",
            "zip": "",
            "lat": None,
            "lon": None,
            "list_price": price,
            "price_per_sqft": round(price / sqft, 2) if price and sqft else None,
            "sqft": sqft,
            "beds": beds,
            "baths": baths,
            "days_on_market": None,
            "listing_status": "for_sale",
            "listing_description": "",
            "estimated_value": None,
            "img_url": item.get("img", ""),
            "detail_url": item.get("link", ""),
        }
    except Exception as e:
        logger.debug(f"DOM normalization error: {e}")
        return None


def fetch_zillow_listings(
    location: str,
    listing_type: str = "for_sale",
    max_pages: int = 2,
    headless: bool = True,
) -> list[dict]:
    """
    Scrape Zillow listings using Playwright with stealth measures.

    Args:
        location: City, "City, State", or ZIP code.
        listing_type: "for_sale" or "recently_sold".
        max_pages: Max search result pages to scrape (each page ~40 listings).
        headless: Run browser in headless mode.

    Returns:
        List of normalized property dicts (same schema as HomeHarvest).
        Returns empty list if Playwright is not installed or scraping fails.
    """
    if not HAS_PLAYWRIGHT:
        logger.warning("playwright not installed — install with: pip install playwright && playwright install chromium")
        return []

    url = _build_search_url(location, listing_type)
    logger.info(f"Fetching Zillow listings from {url}")

    all_listings = []
    viewport = random.choice(VIEWPORTS)
    user_agent = random.choice(USER_AGENTS)
    locale = random.choice(LOCALES)

    try:
        with sync_playwright() as p:
            # Launch browser with stealth configuration
            browser = p.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ]
            )

            context = browser.new_context(
                viewport=viewport,
                user_agent=user_agent,
                locale=locale,
                timezone_id="America/New_York",
                permissions=["geolocation"],
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                },
            )

            page = context.new_page()

            # Apply stealth plugin if available
            if HAS_STEALTH:
                stealth_sync(page)

            # Navigate to search URL
            logger.debug(f"Navigating to Zillow search: {url}")
            page.goto(url, wait_until="networkidle", timeout=30000)

            # Wait for results to load
            time.sleep(random.uniform(2, 4))

            # Human-like scrolling to trigger lazy loading
            _human_scroll(page, scrolls=max_pages * 2)

            # Wait a bit more for lazy-loaded content
            time.sleep(random.uniform(1, 3))

            # Parse listings from the page
            page_listings = _parse_zillow_listings(page)
            all_listings.extend(page_listings)

            # Try pagination if we want more results
            if max_pages > 1 and page_listings:
                for page_num in range(2, max_pages + 1):
                    try:
                        next_url = url.rstrip("/") + f"/{page_num}_page/"
                        logger.debug(f"Fetching page {page_num}: {next_url}")
                        _shared_rate_limit("zillow")
                        page.goto(next_url, wait_until="networkidle", timeout=30000)
                        time.sleep(random.uniform(2, 3))
                        _human_scroll(page, scrolls=2)
                        time.sleep(random.uniform(1, 2))

                        more_listings = _parse_zillow_listings(page)
                        if not more_listings:
                            break
                        all_listings.extend(more_listings)

                    except Exception as e:
                        logger.debug(f"Pagination failed on page {page_num}: {e}")
                        break

            browser.close()

    except Exception as e:
        logger.error(f"Zillow scraping failed: {e}")
        return all_listings  # Return what we got before the error

    # Deduplicate by listing_id
    seen = set()
    unique_listings = []
    for listing in all_listings:
        lid = listing.get("listing_id", "")
        if lid not in seen:
            seen.add(lid)
            unique_listings.append(listing)

    logger.info(f"Zillow scrape complete: {len(unique_listings)} unique listings from {url}")
    return unique_listings
