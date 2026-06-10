"""
LoopNet authenticated scraper — manual-login flow + scrape-with-session.

Usage:
    # Phase 1: manual login (requires Xvfb + interactive display)
    DISPLAY=:99 Xvfb :99 -screen 0 1024x768x24 &
    python -m scrapers.loopnet_auth login

    # Phase 2: scrape commercial listings using saved state
    python -m scrapers.loopnet_auth scrape "https://www.loopnet.com/search/commercial-real-estate/chicago-il/for-sale/"
"""

import json
import os
import random
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SESSION_PATH = PROJECT_ROOT / "loopnet_session.json"

# Anti-bot fingerprinting
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]
LOCALES = ["en-US", "en"]


def launch_browser(p, headless: bool = True):
    """Launch chromium with stealth applied. Use headless=False for the manual login."""
    browser = p.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context = browser.new_context(
        viewport=random.choice(VIEWPORTS),
        user_agent=random.choice(USER_AGENTS),
        locale=random.choice(LOCALES),
        timezone_id="America/Chicago",
    )
    Stealth().apply_stealth_sync(context)
    return browser, context


def phase_login(login_url: str = "https://www.loopnet.com/auth/signin",
                timeout_seconds: int = 300,
                poll_interval: int = 2) -> bool:
    """
    Open LoopNet login page in a non-headless browser and wait for the user
    to log in manually. Once the URL no longer contains '/login', save the
    storage state to SESSION_PATH and return True.
    """
    print(f"[login] launching non-headless browser (DISPLAY={os.environ.get('DISPLAY')})")
    print(f"[login] navigate to: {login_url}")
    print(f"[login] waiting up to {timeout_seconds}s for manual login (poll every {poll_interval}s)")
    print(f"[login] session will be saved to: {SESSION_PATH}")

    t0 = time.time()
    with sync_playwright() as p:
        browser, context = launch_browser(p, headless=False)
        page = context.new_page()
        page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        print(f"[login] page loaded — please log in manually in the popup window")

        # Poll until URL no longer contains /login (or timeout)
        while time.time() - t0 < timeout_seconds:
            time.sleep(poll_interval)
            current_url = page.url
            if "/login" not in current_url.lower():
                elapsed = time.time() - t0
                print(f"[login] login detected after {elapsed:.0f}s — current URL: {current_url}")
                # Save the storage state
                context.storage_state(path=str(SESSION_PATH))
                print(f"[login] session saved to {SESSION_PATH}")
                browser.close()
                return True

        elapsed = time.time() - t0
        print(f"[login] TIMEOUT after {elapsed:.0f}s — user did not log in")
        browser.close()
        return False


def phase_scrape(target_url: str,
                 session_path: Path = SESSION_PATH,
                 max_wait_ms: int = 15000) -> list[dict]:
    """
    Headless scrape using the saved session state. Extracts first page of
    listing titles + asking prices.
    """
    if not session_path.exists():
        print(f"[scrape] no session file at {session_path} — run `python -m scrapers.loopnet_auth login` first")
        return []

    print(f"[scrape] loading session from {session_path}")
    print(f"[scrape] target URL: {target_url}")

    with sync_playwright() as p:
        browser, context = launch_browser(p, headless=True)
        # Inject the saved storage state (cookies + localStorage)
        context.add_cookies(_load_cookies(session_path))
        # Restore localStorage too
        for origin_url, storage in _load_local_storage(session_path).items():
            page = context.new_page()
            page.goto(origin_url, wait_until="domcontentloaded", timeout=15000)
            for k, v in storage.items():
                page.evaluate(f"localStorage.setItem({k!r}, {v!r})")
            page.close()

        page = context.new_page()
        page.goto(target_url, wait_until="domcontentloaded", timeout=30000)

        # Wait for listing cards
        try:
            page.wait_for_selector(
                'a[href*="/listing/"], [class*="listing"], article',
                timeout=max_wait_ms,
            )
            print(f"[scrape] listing cards appeared")
        except Exception as e:
            print(f"[scrape] selector timeout: {e}")
            print(f"[scrape] page title: {page.title()}")
            body_preview = page.inner_text("body", timeout=5000)[:300]
            print(f"[scrape] body preview: {body_preview!r}")
            browser.close()
            return []

        # Give the page a moment to settle
        time.sleep(2)

        # Extract listings — try common selectors
        cards = page.evaluate(
            """() => {
                const results = [];
                // LoopNet listing cards are <a> tags with /listing/ in the href
                const links = document.querySelectorAll('a[href*="/listing/"]');
                for (const a of links) {
                    const title = a.getAttribute('title') || a.textContent.trim().split('\\n')[0].trim();
                    const href = a.href;
                    if (!title) continue;
                    // Try to find a price in nearby text
                    const card = a.closest('article, [class*="listing"], [class*="card"], div');
                    const priceEl = card ? card.querySelector('[class*="price"]') : null;
                    const price = priceEl ? priceEl.textContent.trim() : '';
                    results.push({ title: title.substring(0, 200), price, href });
                }
                return results;
            }"""
        )

        # Deduplicate by href
        seen = set()
        unique = []
        for c in cards:
            if c["href"] not in seen and c["title"]:
                seen.add(c["href"])
                unique.append(c)

        browser.close()
        return unique


def _load_cookies(session_path: Path) -> list[dict]:
    with open(session_path) as f:
        state = json.load(f)
    return state.get("cookies", [])


def _load_local_storage(session_path: Path) -> dict[str, dict]:
    with open(session_path) as f:
        state = json.load(f)
    origins = state.get("origins", [])
    return {o["origin"]: o.get("localStorage", []) for o in origins}


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m scrapers.loopnet_auth login                    # manual login flow")
        print("  python -m scrapers.loopnet_auth scrape <url>             # scrape using saved session")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "login":
        timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 300
        ok = phase_login(timeout_seconds=timeout)
        sys.exit(0 if ok else 1)
    elif cmd == "scrape":
        if len(sys.argv) < 3:
            print("Provide a URL to scrape")
            sys.exit(1)
        url = sys.argv[2]
        listings = phase_scrape(url)
        # Print first 3 as JSON
        out = listings[:3]
        print(f"\n[scrape] {len(listings)} total listings, printing first 3:")
        print(json.dumps(out, indent=2))
        if not listings:
            sys.exit(2)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
