"""
Shared scoring utilities.
"""

from config import TIER_THRESHOLDS, RESIDENTIAL_WEIGHTS, LAND_WEIGHTS, COMMERCIAL_WEIGHTS


def assign_tier(score: float) -> str:
    """Assign a lead tier based on score threshold."""
    for tier_name, threshold in sorted(
        TIER_THRESHOLDS.items(), key=lambda x: x[1], reverse=True
    ):
        if score >= threshold:
            return tier_name
    return "SKIP"


def parse_flags(flags_value):
    """
    Parse brain_red_flags or brain_green_flags from either a JSON string or a list.
    These fields may be stored as JSON strings in the DB or Python lists in memory.
    """
    if isinstance(flags_value, list):
        return flags_value
    if isinstance(flags_value, str):
        import json
        try:
            return json.loads(flags_value)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def apply_comp_fallback(property_dict: dict, scores: dict) -> dict:
    """
    Apply fallback scoring when comp_count is 0.

    When there are no comparable sold properties:
      1. If estimated_value exists, use it as a proxy for price deviation
         (compares list_price vs estimated value)
      2. If no estimated_value either, set _cap_at_risky flag so the caller
         limits the total score below NEUTRAL threshold.

    IMPORTANT: All metadata fields use the "_fb_" prefix so they can be
    filtered out when summing numeric scores.

    Args:
        property_dict: The property being scored.
        scores: The current scores dict (mutated in-place).

    Returns:
        Updated scores dict. Numeric score fields are safe to sum;
        metadata fields have '_fb_' prefix and should be excluded from sum.
    """
    comp_count = property_dict.get("comp_count", 0)

    # Handle None or 0
    if comp_count is None:
        comp_count = 0

    if comp_count > 0:
        return scores  # Real comps available — no fallback needed

    # --- No comps available — apply fallback ---

    list_price = property_dict.get("list_price")
    estimated_value = property_dict.get("estimated_value")

    if (
        estimated_value
        and list_price
        and float(estimated_value) > 0
        and float(list_price) > 0
    ):
        # Use estimated_value as a proxy for "fair market value"
        est_deviation = ((float(list_price) - float(estimated_value)) / float(estimated_value)) * 100

        scores["_fb_source"] = "estimated_value"

        # If the existing price_deviation score is 0 (no comp data),
        # replace it with the estimated_value proxy
        existing_price = scores.get("price_deviation", 0)
        if existing_price == 0:
            if est_deviation <= 0:
                # Listed below estimated value = good deal
                proxy_score = max(0.0, min(40.0, (-est_deviation / 50.0) * 40.0))
                scores["price_deviation"] = proxy_score
            else:
                # Listed above estimated value = overpriced
                proxy_score = max(-10.0, -(est_deviation / 50.0) * 10.0)
                scores["price_deviation"] = proxy_score

            scores["_fb_deviation_pct"] = round(est_deviation, 2)

        return scores

    # --- No comps AND no estimated_value ---
    scores["_fb_cap_at_risky"] = True

    return scores


def apply_confidence_cap(property_dict: dict, scores: dict) -> dict:
    """
    Apply a 10-point cap reduction to the price_deviation score component
    when comp_confidence_label is "LOW". A LOW confidence comp should not
    be worth full points even if the deviation looks extreme.

    Only modifies EXISTING numeric scores via the _fb_ prefix for safe
    filtering when summing. Does NOT add non-numeric keys to scores.

    Args:
        property_dict: The property being scored (contains comp_confidence_*).
        scores: The current scores dict (mutated in-place).

    Returns:
        Updated scores dict with capped price_deviation if applicable.
    """
    conf_label = property_dict.get("comp_confidence_label")

    if conf_label == "LOW":
        # Cap price_deviation (residential/commercial) or price_per_acre_deviation (land)
        for key in ("price_deviation", "price_per_acre_deviation"):
            if key in scores:
                current = scores[key]
                if current > 10:
                    scores[key] = 10.0

    return scores


def cap_score_if_no_comps(total: float, scores: dict) -> tuple[float, str | None]:
    """
    Cap the total score if we had no comp data at all.

    When there are no comps AND no estimated_value to proxy,
    the maximum possible score is 30 (RISKY tier). We cannot
    determine if a property is a deal without pricing data.

    Args:
        total: The raw total score.
        scores: The scores dict (checked for _fb_cap_at_risky flag).

    Returns:
        Tuple of (capped_total, tier_override_flag or None).
    """
    if scores.get("_fb_cap_at_risky"):
        max_no_comp = 30  # Below NEUTRAL threshold (35)
        if total > max_no_comp:
            return max_no_comp, "capped"
    return total, None
