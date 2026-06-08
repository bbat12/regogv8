"""
Redfin Playwright scraper — agent-browsing fallback for listings.
No API key required. Uses stealth browsing as a fallback when HomeHarvest data is stale.
"""

import time
import random
import json
import re
import logging
from typing import Optional

from utils.rate_limiter import rate_limit, report_success, report_error

logger = logging.getLogger(__name__)

REDFIN_BASE = "https://www.redfin.com"

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    sync_playwright = None  # type: ignore


def build_redfin_url(location: str, price_max: int = None, scan_type: str = "residential") -> str:
    """Build a Redfin search URL for agent browsing."""
    # Encode city, state into Redfin's path format
    location_slug = location.replace(", ", "/").replace(" ", "-")
    base = f"{REDFIN_BASE}/city/{location_slug}"
    filters = []
    if price_max:
        filters.append(f"max-price={price_max}")
    if scan_type == "land":
        filters.append("property-type=land")
    filter_str = ",".join(filters)
    return f"{base}/filter/{filter_str}" if filter_str else base


def scrape_redfin_listings(
    location: str,
    price_max: int = None,
    scan_type: str = "residential",
    limit: int = 50,
) -> list[dict]:
    """
    Agent-browse Redfin for listings. Returns normalized property dicts.
    Slower than HomeHarvest but provides more current data as a supplement.
    """
    if not HAS_PLAYWRIGHT:
        logger.warning("Playwright not installed — cannot use Redfin scraper")
        return []

    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="en-US",
            )
            page = context.new_page()

            try:
                url = build_redfin_url(location, price_max, scan_type)
                rate_limit("redfin")
                page.goto(url, wait_until="networkidle", timeout=30000)
                time.sleep(random.uniform(2, 4))

                # Try embedded JSON data first (more reliable than DOM parsing)
                script_content = page.evaluate("""
                    () => {
                        const scripts = document.querySelectorAll('script');
                        for (const s of scripts) {
                            if (s.textContent.includes('"homeData"')) return s.textContent;
                        }
                        return null;
                    }
                """)

                if script_content:
                    match = re.search(r'window\.__reactServerPageProps\s*=\s*({.+?});', script_content, re.DOTALL)
                    if match:
                        try:
                            data = json.loads(match.group(1))
                            homes = data.get("searchPageState", {}).get("cat1", {}).get("searchResults", {}).get("homeData", [])
                            for h in homes[:limit]:
                                prop = _normalize_redfin_card(h, location, scan_type)
                                if prop:
                                    results.append(prop)
                        except json.JSONDecodeError:
                            pass

                # Fallback: DOM scraping of listing cards
                if not results:
                    cards = page.query_selector_all('[data-rf-test-id="abp-homecard"]')
                    for card in cards[:limit]:
                        try:
                            prop = _parse_redfin_card_dom(card, location, scan_type)
                            if prop:
                                results.append(prop)
                        except Exception:
                            continue

                report_success("redfin")
            except Exception as e:
                report_error("redfin")
                logger.warning(f"[Redfin] Scrape error: {e}")
            finally:
                browser.close()
    except Exception as e:
        logger.warning(f"[Redfin] Playwright launch error: {e}")

    return results


def _normalize_redfin_card(card_data: dict, location: str, scan_type: str) -> Optional[dict]:
    """Normalize a Redfin homeData card to REGOG schema."""
    try:
        hd = card_data.get("homeData", card_data)
        price = hd.get("priceInfo", {}).get("amount") or hd.get("price")
        if not price:
            return None

        address_info = hd.get("addressInfo", {})
        full_address = address_info.get("formattedStreetLine") or address_info.get("street", "")
        city = address_info.get("city", "")
        state = address_info.get("state", "")
        zip_code = address_info.get("zip", "")

        url = hd.get("url", "")
        if url and not url.startswith("http"):
            url = f"https://www.redfin.com{url}"

        beds = hd.get("beds") or hd.get("numBeds")
        baths = hd.get("baths") or hd.get("numBathrooms")
        sqft = hd.get("sqFt", {}).get("value") if isinstance(hd.get("sqFt"), dict) else hd.get("sqft")
        dom = hd.get("dom") or hd.get("daysOnMarket")

        lat = hd.get("latLong", {}).get("latitude") if isinstance(hd.get("latLong"), dict) else None
        lon = hd.get("latLong", {}).get("longitude") if isinstance(hd.get("latLong"), dict) else None

        property_type = hd.get("propertyType", "SINGLE_FAMILY")

        return {
            "listing_id": f"redfin_{hd.get('mlsId', {}).get('value', '') or hd.get('listingId', '')}",
            "source": "redfin",
            "scan_type": scan_type,
            "style": property_type,
            "address": full_address,
            "city": city,
            "state": state,
            "zip": zip_code,
            "lat": lat,
            "lon": lon,
            "list_price": int(price) if price else None,
            "beds": int(beds) if beds else None,
            "baths": float(baths) if baths else None,
            "sqft": int(sqft) if sqft else None,
            "days_on_market": int(dom) if dom else None,
            "property_url": url,
            "listing_status": "for_sale",
        }
    except Exception:
        return None


def _parse_redfin_card_dom(card, location: str, scan_type: str) -> Optional[dict]:
    """DOM fallback parser for Redfin listing cards."""
    try:
        price_el = card.query_selector('[data-rf-test-id="abp-price"]') or card.query_selector('.homecardV2Price')
        if not price_el:
            return None
        price_text = price_el.inner_text().replace("$", "").replace(",", "").strip()
        price = int(float(price_text)) if price_text.replace(".", "").isdigit() else None

        addr_el = card.query_selector('[data-rf-test-id="abp-streetLine"]') or card.query_selector('.homeAddressV2')
        address = addr_el.inner_text().strip() if addr_el else ""

        url_el = card.query_selector("a")
        url = url_el.get_attribute("href") if url_el else None
        if url and not url.startswith("http"):
            url = f"https://www.redfin.com{url}"

        stats = card.query_selector_all('.HomeStatsV2 .stat') if card.query_selector_all else []
        beds = baths = sqft = None
        for stat in stats:
            text = stat.inner_text()
            if "bed" in text.lower():
                try:
                    beds = int(text.split()[0])
                except (ValueError, IndexError):
                    pass
            elif "bath" in text.lower():
                try:
                    baths = float(text.split()[0])
                except (ValueError, IndexError):
                    pass
            elif "sq ft" in text.lower():
                try:
                    sqft = int(text.replace(",", "").split()[0])
                except (ValueError, IndexError):
                    pass

        return {
            "listing_id": f"redfin_dom_{hash(address + str(price))}",
            "source": "redfin",
            "scan_type": scan_type,
            "style": "SINGLE_FAMILY",
            "address": address,
            "city": location.split(",")[0].strip() if "," in location else location,
            "state": location.split(",")[1].strip() if "," in location else "",
            "list_price": price,
            "beds": beds,
            "baths": baths,
            "sqft": sqft,
            "property_url": url,
            "listing_status": "for_sale",
        }
    except Exception:
        return None
