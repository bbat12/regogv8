"""
LoopNet authenticated scraper — credentials login + scrape-with-session.

Usage:
    # Preferred: headless email/password login (LoopNet has no 2FA)
    python -m scrapers.loopnet_auth login-credentials user@example.com mypassword

    # Re-login using saved loopnet_credentials.json
    python -m scrapers.loopnet_auth login-credentials

    # Legacy: manual login (requires Xvfb + interactive display)
    DISPLAY=:99 Xvfb :99 -screen 0 1024x768x24 &
    python -m scrapers.loopnet_auth login

    # Scrape commercial listings using saved session
    python -m scrapers.loopnet_auth scrape "https://www.loopnet.com/search/commercial-real-estate/chicago-il/for-sale/"

If the LOOPNET_PROXY env var is set (e.g. http://user:pass@host:port), all
browser traffic is routed through it — needed when the local egress IP is on
Akamai's denylist (see REGOG_REBUILD_V8.md §15).
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
CREDENTIALS_PATH = PROJECT_ROOT / "loopnet_credentials.json"

SIGNIN_URL = "https://www.loopnet.com/auth/signin"

# Cookies that mark an authenticated LoopNet session. Mirrors
# EXPECTED_LOOPNET_COOKIES in web/app.py (the cookie-paste fallback).
EXPECTED_COOKIES = [
    "SessionFarm_GUID",
    "UserPreferences",
    "UserInfo_AssociateID",
]

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


def _proxy_config() -> dict | None:
    """Build a Playwright proxy dict from the LOOPNET_PROXY env var, if set."""
    raw = os.environ.get("LOOPNET_PROXY", "").strip()
    if not raw:
        return None
    from urllib.parse import urlsplit
    parts = urlsplit(raw)
    proxy: dict = {"server": f"{parts.scheme or 'http'}://{parts.hostname}"}
    if parts.port:
        proxy["server"] += f":{parts.port}"
    if parts.username:
        proxy["username"] = parts.username
    if parts.password:
        proxy["password"] = parts.password
    return proxy


def launch_browser(p, headless: bool = True):
    """Launch chromium with stealth applied. Use headless=False for the manual login."""
    browser = p.chromium.launch(
        headless=headless,
        proxy=_proxy_config(),
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


class LoopNetLoginError(Exception):
    """Credentials login failed. `reason` is one of:
    'blocked' (Akamai IP denylist), 'bad_credentials', 'form_not_found',
    'timeout'."""

    def __init__(self, message: str, reason: str = "timeout"):
        super().__init__(message)
        self.reason = reason


def _is_access_denied(page) -> bool:
    """Detect Akamai's 403 'Access Denied' interstitial."""
    try:
        title = (page.title() or "").lower()
        if "access denied" in title:
            return True
        body = page.inner_text("body", timeout=3000).lower()
        return "errors.edgesuite.net" in body or "you don't have permission to access" in body
    except Exception:
        return False


def _fill_first_visible(page, selectors: list[str], value: str, timeout_ms: int = 4000) -> bool:
    """Fill the first selector that resolves to a visible input. Returns False if none match."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout_ms)
            loc.click()
            loc.fill(value)
            return True
        except Exception:
            continue
    return False


EMAIL_SELECTORS = [
    'input[type="email"]',
    'input[name="username"]',
    'input[name="email"]',
    'input[name="emailAddress"]',
    "#email",
    "#username",
    'input[autocomplete="username"]',
]
PASSWORD_SELECTORS = [
    'input[type="password"]',
    'input[name="password"]',
    "#password",
]
SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Sign In")',
    'button:has-text("Log In")',
    'button:has-text("Continue")',
]

# Phrases LoopNet shows on a rejected login. Checked against visible body text.
BAD_CREDENTIALS_PHRASES = [
    "incorrect", "invalid", "doesn't match", "does not match",
    "couldn't find", "could not find", "no account", "try again",
]


def login_with_credentials(email: str,
                           password: str,
                           headless: bool = True,
                           session_path: Path = SESSION_PATH,
                           timeout_seconds: int = 60) -> dict:
    """
    Log in to LoopNet with email + password (LoopNet has no 2FA) using a
    headless stealth browser, then save the session cookies to `session_path`
    in the same format produced by /api/loopnet/save-cookie:

        {cookies, cookie_string, saved_at, missing_expected, expected_cookies}

    Returns the saved session dict. Raises LoopNetLoginError on failure —
    callers can branch on `.reason` ('blocked' means the egress IP is on
    Akamai's denylist and no credentials will ever work from this machine).
    """
    print(f"[login-credentials] logging in as {email} (headless={headless})")
    with sync_playwright() as p:
        browser, context = launch_browser(p, headless=headless)
        try:
            page = context.new_page()
            resp = page.goto(SIGNIN_URL, wait_until="domcontentloaded", timeout=30000)

            if (resp and resp.status == 403) or _is_access_denied(page):
                raise LoopNetLoginError(
                    "LoopNet (Akamai) blocks this machine's IP before login is even "
                    "possible. Run REGOG from a clean IP (local machine / small VM) "
                    "or set LOOPNET_PROXY to a residential proxy.",
                    reason="blocked",
                )

            if not _fill_first_visible(page, EMAIL_SELECTORS, email):
                raise LoopNetLoginError(
                    "Could not find the email field on the LoopNet sign-in page — "
                    "the page layout may have changed.",
                    reason="form_not_found",
                )

            # LoopNet may use a one-page form or a two-step (email → continue →
            # password) flow. If no password field is visible yet, submit the
            # email first and wait for the password step.
            if not _fill_first_visible(page, PASSWORD_SELECTORS, password, timeout_ms=2000):
                for sel in SUBMIT_SELECTORS:
                    try:
                        page.locator(sel).first.click(timeout=2000)
                        break
                    except Exception:
                        continue
                if not _fill_first_visible(page, PASSWORD_SELECTORS, password, timeout_ms=8000):
                    raise LoopNetLoginError(
                        "Could not find the password field on the LoopNet sign-in "
                        "page — the page layout may have changed.",
                        reason="form_not_found",
                    )

            for sel in SUBMIT_SELECTORS:
                try:
                    page.locator(sel).first.click(timeout=2000)
                    break
                except Exception:
                    continue
            else:
                page.keyboard.press("Enter")

            # Poll for the authenticated-session cookie (or a rejection message).
            t0 = time.time()
            while time.time() - t0 < timeout_seconds:
                time.sleep(2)
                cookie_names = {c["name"] for c in context.cookies()}
                if "UserInfo_AssociateID" in cookie_names:
                    break
                if "signin" not in page.url.lower() and "login" not in page.url.lower():
                    break
                try:
                    body = page.inner_text("body", timeout=3000).lower()
                    if any(phrase in body for phrase in BAD_CREDENTIALS_PHRASES):
                        raise LoopNetLoginError(
                            "LoopNet rejected the email/password combination.",
                            reason="bad_credentials",
                        )
                except LoopNetLoginError:
                    raise
                except Exception:
                    pass
            else:
                raise LoopNetLoginError(
                    f"Login did not complete within {timeout_seconds}s — no "
                    f"authenticated cookie appeared and the page stayed on "
                    f"{page.url}.",
                    reason="timeout",
                )

            cookies = {
                c["name"]: c["value"]
                for c in context.cookies()
                if "loopnet.com" in c.get("domain", "")
            }
            session = _build_session(cookies)
            with open(session_path, "w") as f:
                json.dump(session, f, indent=2)
            print(f"[login-credentials] success — saved {len(cookies)} cookies "
                  f"to {session_path} (missing expected: {session['missing_expected'] or 'none'})")
            return session
        finally:
            browser.close()


def _build_session(cookies: dict) -> dict:
    """Build the on-disk session format from a {name: value} cookie dict."""
    missing = [c for c in EXPECTED_COOKIES if c not in cookies]
    return {
        "cookies": cookies,
        "cookie_string": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "missing_expected": missing,
        "expected_cookies": list(EXPECTED_COOKIES),
    }


def save_credentials(email: str, password: str,
                     credentials_path: Path = CREDENTIALS_PATH) -> None:
    """Persist credentials (0600, gitignored) so the scraper can re-login
    automatically when the session goes stale."""
    with open(credentials_path, "w") as f:
        json.dump({"email": email, "password": password}, f, indent=2)
    os.chmod(credentials_path, 0o600)


def load_credentials(credentials_path: Path = CREDENTIALS_PATH) -> dict:
    """Return {"email": ..., "password": ...} or {} if absent/invalid."""
    if not credentials_path.exists():
        return {}
    try:
        with open(credentials_path) as f:
            data = json.load(f)
        if data.get("email") and data.get("password"):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


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
    session = _load_session(session_path)
    if not session.get("cookie_string"):
        # No usable session — try an automatic credentials login before giving up.
        creds = load_credentials()
        if creds:
            print(f"[scrape] no usable session at {session_path} — attempting "
                  f"credentials re-login as {creds['email']}")
            try:
                session = login_with_credentials(
                    creds["email"], creds["password"], session_path=session_path
                )
            except LoopNetLoginError as e:
                print(f"[scrape] credentials re-login failed ({e.reason}): {e}")
                return []
        else:
            print(f"[scrape] no session at {session_path} — log in with email/"
                  f"password via the REGOG UI (or `python -m scrapers.loopnet_auth "
                  f"login-credentials <email> <password>`)")
            return []

    print(f"[scrape] loading session from {session_path}")
    print(f"[scrape] target URL: {target_url}")

    with sync_playwright() as p:
        browser, context = launch_browser(p, headless=True)
        cookie_string = session["cookie_string"]
        print(f"[scrape] loaded {len(session.get('cookies', {}))} cookies from {session_path}")

        # Set the Cookie header on ALL LoopNet requests via extra HTTP headers.
        # This is the primary path — Playwright forwards it on every navigation
        # and XHR/fetch the page issues, matching the "Cookie header" request.
        context.set_extra_http_headers({"Cookie": cookie_string})
        # Also inject the cookies into the browser context so client-side JS
        # that reads document.cookie still works.
        context.add_cookies(_session_to_cookies(session))

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


def _load_session(session_path: Path = SESSION_PATH) -> dict:
    """
    Load the new-format LoopNet session file produced by web/app.py's
    /api/loopnet/save-cookie endpoint.

    File shape:
        {
            "cookies":          {"SessionFarm_GUID": "...", "TDID": "...", ...},
            "cookie_string":    "SessionFarm_GUID=...; TDID=...; ...",
            "saved_at":         "2026-...",
            "missing_expected": [...],
            "expected_cookies": [...],
        }

    Returns {} on missing / invalid / empty file.
    """
    if not session_path.exists():
        return {}
    try:
        with open(session_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[scrape] failed to read session file {session_path}: {e}")
        return {}


def _session_to_cookies(session: dict, domain: str = ".loopnet.com") -> list[dict]:
    """Convert a new-format session dict to Playwright cookie dicts."""
    # 10 years from now — effectively a permanent session. LoopNet itself
    # will invalidate the cookies server-side when they expire.
    far_future = int(time.time()) + 60 * 60 * 24 * 365 * 10
    cookies: list[dict] = []
    for name, value in (session.get("cookies") or {}).items():
        cookies.append({
            "name": name,
            "value": value,
            "domain": domain,
            "path": "/",
            "expires": far_future,
            "httpOnly": False,
            "secure": False,
            "sameSite": "Lax",
        })
    return cookies


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m scrapers.loopnet_auth login-credentials [email] [password]   # headless email/password login")
        print("  python -m scrapers.loopnet_auth login                    # manual login flow (legacy)")
        print("  python -m scrapers.loopnet_auth scrape <url>             # scrape using saved session")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "login-credentials":
        if len(sys.argv) >= 4:
            email, password = sys.argv[2], sys.argv[3]
            save_credentials(email, password)
            print(f"[login-credentials] credentials saved to {CREDENTIALS_PATH}")
        else:
            creds = load_credentials()
            if not creds:
                print(f"No credentials given and none saved at {CREDENTIALS_PATH}")
                print("Usage: python -m scrapers.loopnet_auth login-credentials <email> <password>")
                sys.exit(1)
            email, password = creds["email"], creds["password"]
        try:
            login_with_credentials(email, password)
            sys.exit(0)
        except LoopNetLoginError as e:
            print(f"[login-credentials] FAILED ({e.reason}): {e}")
            sys.exit(1)
    elif cmd == "login":
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
