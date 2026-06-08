"""
The Brain — property classification using keyword/regex matching.
No LLM required for V1. Scans listing descriptions for signals.
"""

import re
import json
from typing import Optional

from config import (
    CLASSIFICATION_KEYWORDS,
    SELLER_MOTIVATION_KEYWORDS,
    RED_FLAG_KEYWORDS,
    GREEN_FLAG_KEYWORDS,
)


def classify_property(
    address: str,
    scan_type: str,
    list_price: Optional[int],
    sqft: Optional[int],
    year_built: Optional[int],
    days_on_market: Optional[int],
    description: Optional[str],
) -> dict:
    """
    Analyze a property listing using keyword matching and return a classification result.

    Returns dict with:
        classification: str
        confidence: float
        red_flags: list[str]
        green_flags: list[str]
        seller_motivation: str
        estimated_condition: str
        is_luxury: bool
        notes: str
    """
    text = (description or "").lower()
    full_text = f"{address or ''} {text}".lower()

    # ─── Classification via keyword matching ──────────────────────────────────
    classification = "standard"
    confidence = 0.5
    matched_keywords = []

    # Check fire_damage first (highest priority)
    for kw in CLASSIFICATION_KEYWORDS.get("fire_damage", []):
        if kw in text:
            classification = "fire_damage"
            matched_keywords.append(kw)
            confidence = min(1.0, confidence + 0.3)

    # Check teardown
    if classification == "standard":
        for kw in CLASSIFICATION_KEYWORDS.get("teardown", []):
            if kw in text:
                classification = "teardown"
                matched_keywords.append(kw)
                confidence = min(1.0, confidence + 0.3)

    # Check distressed
    if classification == "standard":
        for kw in CLASSIFICATION_KEYWORDS.get("distressed", []):
            if kw in text:
                classification = "distressed"
                matched_keywords.append(kw)
                confidence = min(1.0, confidence + 0.25)

    # Check vacant
    if classification == "standard":
        for kw in CLASSIFICATION_KEYWORDS.get("vacant", []):
            if kw in text:
                classification = "vacant"
                matched_keywords.append(kw)
                confidence = min(1.0, confidence + 0.2)

    # Check luxury (only for standard or if no other match)
    if classification == "standard" or classification == "vacant":
        for kw in CLASSIFICATION_KEYWORDS.get("luxury", []):
            if kw in text:
                classification = "luxury" if classification == "standard" else classification
                matched_keywords.append(kw)
                confidence = min(1.0, confidence + 0.2)

    # Land override
    if scan_type == "land":
        classification = "land_only"
        confidence = 1.0

    # ─── Seller Motivation ────────────────────────────────────────────────────
    seller_motivation = "low"
    for kw in SELLER_MOTIVATION_KEYWORDS.get("high", []):
        if kw in text:
            seller_motivation = "high"
            matched_keywords.append(kw)
            break
    if seller_motivation == "low":
        for kw in SELLER_MOTIVATION_KEYWORDS.get("medium", []):
            if kw in text:
                seller_motivation = "medium"
                matched_keywords.append(kw)
                break

    # ─── Red Flags ────────────────────────────────────────────────────────────
    red_flags = []
    for kw in RED_FLAG_KEYWORDS:
        if kw in text:
            red_flags.append(kw)

    # ─── Green Flags ──────────────────────────────────────────────────────────
    green_flags = []
    for kw in GREEN_FLAG_KEYWORDS:
        if kw in text:
            green_flags.append(kw)

    # ─── Estimated Condition ──────────────────────────────────────────────────
    condition_map = {
        "luxury": "excellent",
        "standard": "good",
        "vacant": "fair",
        "distressed": "poor",
        "teardown": "uninhabitable",
        "fire_damage": "uninhabitable",
        "land_only": "good",
    }
    estimated_condition = condition_map.get(classification, "fair")

    # ─── Luxury flag ──────────────────────────────────────────────────────────
    is_luxury = classification == "luxury" or any(
        kw in full_text for kw in CLASSIFICATION_KEYWORDS.get("luxury", [])
    )

    # ─── Notes ────────────────────────────────────────────────────────────────
    notes_parts = []
    if classification != "standard":
        notes_parts.append(f"Classified as '{classification}'")
    if red_flags:
        notes_parts.append(f"Red flags: {', '.join(red_flags[:3])}")
    if green_flags:
        notes_parts.append(f"Opportunities: {', '.join(green_flags[:3])}")
    if seller_motivation == "high":
        notes_parts.append("High seller motivation detected")
    notes = "; ".join(notes_parts) if notes_parts else "Standard listing, no special signals"

    return {
        "classification": classification,
        "confidence": round(confidence, 2),
        "red_flags": red_flags,
        "green_flags": green_flags,
        "seller_motivation": seller_motivation,
        "motivation_signals": matched_keywords,
        "estimated_condition": estimated_condition,
        "is_luxury": is_luxury,
        "notes": notes,
    }
