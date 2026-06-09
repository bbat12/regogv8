"""
Listing Filter — detects and flags junk/trap listings before scoring.

Filters out:
  - Auction listings (foreclosure auctions, opening bids, online auctions)
  - Bait prices (extremely low prices with no real data, $1, $10 "attention" listings)
  - Burned down / fire-damaged structures (burnt, burned, structure fire)
  - Demolition required / teardowns (demolish, scrape, knock down)
  - Land masquerading as houses (style=single_family but description says "land only")
  - Vacant lot pretending to be a property

Each filter returns a reason string or None if the listing is acceptable.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Auction Detection ─────────────────────────────────────────────────────

_AUCTION_KEYWORDS = [
    "foreclosure auction",
    "online auction",
    "auction ends",
    "opening bid",
    "starting bid",
    "minimum bid",
    "bankruptcy sale",
    "trustee sale",
    "sheriff sale",
    "foreclosure sale",
    "public auction",
    "sells at auction",
    "sold at auction",
    "court ordered",
    "lender auction",
]


def check_auction(description: Optional[str], list_price: Optional[int]) -> Optional[str]:
    """Check if a listing is an auction. Returns reason or None."""
    desc = (description or "").lower()

    # Check for auction keywords
    for kw in _AUCTION_KEYWORDS:
        if kw in desc:
            return f"auction listing ({kw})"

    # If description mentions auction and price is unusually low (< $5K), flag it
    if list_price and list_price < 5000 and "auction" in desc:
        return f"auction listing (price=${list_price}, description mentions auction)"

    # "opening bid" is a strong signal regardless of price
    if "opening bid" in desc:
        return "auction listing (opening bid)"

    return None


# ─── Bait Price Detection ─────────────────────────────────────────────────

_BAIT_KEYWORDS = [
    "for investment only",
    "for qualified investors only",
    "not for sale",
    "do not disturb",
    "do not trespass",
    "for attribution",
    "check out this",
    "click here to",
    "call for price",
    "call for details",
    "coming soon listing",  # Not actually for sale yet
]

_MIN_LIST_PRICE = 1000  # Anything below $1K is suspicious unless it's land


def check_bait_price(description: Optional[str], list_price: Optional[int], sqft: Optional[int], style: Optional[str]) -> Optional[str]:
    """Check for bait-and-switch or attention-grabbing prices."""
    desc = (description or "").lower()

    # Below minimum realistic price
    if list_price and list_price < _MIN_LIST_PRICE:
        return f"bait price (${list_price} — below ${_MIN_LIST_PRICE} minimum)"

    # Suspiciously low price for a residential property with no data
    if list_price and list_price < 10000 and style and style.upper() in ("SINGLE_FAMILY", "CONDOS", "TOWNHOMES"):
        # These are likely auctions or bait — unless they have good sqft data
        if not sqft or sqft < 100:
            return f"bait price (${list_price} for {style} with no sqft data)"

    # General bait keywords in description
    for kw in _BAIT_KEYWORDS:
        if kw in desc:
            return f"bait listing ({kw})"

    return None


# ─── Burned / Fire Damage Detection ──────────────────────────────────────

_BURN_KEYWORDS = [
    "burnt",
    "burned down",
    "burned house",
    "burnt structure",
    "fire damaged",
    "fire-damaged",
    "burnt building",
    "total fire loss",
    "fire loss",
    "structure fire",
    "burned to the ground",
    "completely burned",
    "destroyed by fire",
    "fire destroyed",
    "fire gutted",
    "gutted by fire",
    "smoke damaged",
    "extensive fire",
    "fire damage",
    "smoke damage",
]


def check_burned(description: Optional[str], brain_classification: Optional[str]) -> Optional[str]:
    """Check for fire-damaged or burned structures."""
    desc = (description or "").lower()

    # If the brain already flagged it as fire_damage, double-check with stricter rules
    if brain_classification == "fire_damage":
        return "fire damaged structure"

    for kw in _BURN_KEYWORDS:
        if kw in desc:
            return f"burned/damaged ({kw})"

    return None


# ─── Demolition / Teardown Detection ─────────────────────────────────────

_DEMO_KEYWORDS = [
    "must demolish",
    "needs to be demolished",
    "requires demolition",
    "demolition required",
    "structural damage",
    "unsafe structure",
    "condemned",
    "condemned property",
    "habitability",
    "uninhabitable",
    "beyond repair",
    "cannot be repaired",
    "total gut",
    "needs total gut",
]


def check_demolition(description: Optional[str], brain_classification: Optional[str]) -> Optional[str]:
    """Check for demolition-required or condemned properties."""
    desc = (description or "").lower()

    if brain_classification == "teardown":
        return "teardown required"

    for kw in _DEMO_KEYWORDS:
        if kw in desc:
            return f"demolition/condemned ({kw})"

    return None


# ─── Land / Lot Masquerading Detection ───────────────────────────────────

_LAND_AS_HOUSE_KEYWORDS = [
    "buildable lot",
    "land only",
    "land value",
    "vacant lot",
    "lot for sale",
    "empty lot",
    "undeveloped land",
    "raw land",
    "building lot",
    "just the land",
    "selling land only",
    "lot for building",
    "improved lot",
    "for land value",
]


def check_land_masquerade(description: Optional[str], style: Optional[str], sqft: Optional[int]) -> Optional[str]:
    """Check if a residential-style listing is actually a land/lot."""
    if not style:
        return None

    style_upper = style.upper()
    # Only check single_family / condos / townhomes listings that might be land
    if style_upper not in ("SINGLE_FAMILY", "CONDOS", "TOWNHOMES", "CONDO", "TOWNHOUSE"):
        return None

    desc = (description or "").lower()

    for kw in _LAND_AS_HOUSE_KEYWORDS:
        if kw in desc:
            return f"land masquerading as {style} ({kw})"

    # No sqft and no beds for a "house" that mentions lot/land
    if not sqft and (not desc or any(w in desc for w in ["lot", "land", "acre", "building site"])):
        return f"listed as {style} but appears to be land (no sqft, description suggests lot)"

    return None


# ─── Main Filter ──────────────────────────────────────────────────────────

# Severity levels — determines what action to take
# 'skip': completely remove from results
# 'flag': keep but add a filter flag
SEVERITY_SKIP = "skip"
SEVERITY_FLAG = "flag"


def filter_listing(
    description: Optional[str] = None,
    list_price: Optional[int] = None,
    sqft: Optional[int] = None,
    style: Optional[str] = None,
    brain_classification: Optional[str] = None,
) -> Optional[dict]:
    """
    Run all filters on a listing. Returns a result dict if the listing
    should be flagged/skipped, or None if the listing is clean.

    Returns:
        {
            "action": "skip" | "flag",
            "reason": "human-readable explanation",
            "filter_type": "auction" | "bait" | "burned" | "demolition" | "land_masquerade"
        }
    """
    # Check auction (always skip)
    reason = check_auction(description, list_price)
    if reason:
        return {"action": SEVERITY_SKIP, "reason": reason, "filter_type": "auction"}

    # Check bait price (always skip)
    reason = check_bait_price(description, list_price, sqft, style)
    if reason:
        return {"action": SEVERITY_SKIP, "reason": reason, "filter_type": "bait"}

    # Check burned/fire damage (flag — still show but mark as damaged)
    # Don't completely remove these since they could still be deals for the right buyer
    reason = check_burned(description, brain_classification)
    if reason:
        return {"action": SEVERITY_FLAG, "reason": reason, "filter_type": "burned"}

    # Check demolition/condemned (flag — similar reasoning)
    reason = check_demolition(description, brain_classification)
    if reason:
        return {"action": SEVERITY_FLAG, "reason": reason, "filter_type": "demolition"}

    # Check land masquerade (flag — important to know but could still be a deal)
    reason = check_land_masquerade(description, style, sqft)
    if reason:
        return {"action": SEVERITY_FLAG, "reason": reason, "filter_type": "land_masquerade"}

    return None
