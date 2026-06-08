"""
Shared scoring utilities.
"""

from config import TIER_THRESHOLDS


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
