"""
Rate Limiter — per-source request throttling with exponential backoff.

Usage:
    from utils.rate_limiter import rate_limit, wait_if_needed

    # Before each request:
    rate_limit("realtor")

    # Or check without waiting:
    if wait_if_needed("assessor"):
        make_request()
    else:
        # Wait longer or skip
        pass

The rate limiter tracks:
- Minimum/maximum delay between requests (per source)
- Maximum requests per hour (per source)
- Exponential backoff on errors (per domain)
"""

import logging
import random
import time
from typing import Optional
from dataclasses import dataclass, field

from config import RATE_LIMITS

logger = logging.getLogger(__name__)

# ─── Per-source state ────────────────────────────────────────────────────

_source_state: dict[str, "SourceState"] = {}


@dataclass
class SourceState:
    """Tracks rate limiting state for a single data source."""
    name: str
    last_request_time: float = 0.0
    request_timestamps: list[float] = field(default_factory=list)
    backoff_count: int = 0
    consecutive_errors: int = 0


def _get_state(source: str) -> SourceState:
    """Get or create the state tracker for a source."""
    if source not in _source_state:
        _source_state[source] = SourceState(name=source)
    return _source_state[source]


# ─── Public API ──────────────────────────────────────────────────────────

def rate_limit(source: str) -> None:
    """
    Apply rate limiting for a given source before making a request.

    Args:
        source: Source name key (e.g. 'realtor', 'redfin', 'zillow', 'assessor').
                Must exist in config.RATE_LIMITS.

    Raises:
        ValueError: If source is not in RATE_LIMITS config.
    """
    limits = _get_limits(source)
    state = _get_state(source)
    now = time.time()

    # 1. Enforce minimum delay since last request
    elapsed = now - state.last_request_time
    delay_min = limits.get("delay_min", 1)
    if elapsed < delay_min:
        wait = delay_min - elapsed
        time.sleep(wait)

    # 2. Enforce hourly cap
    # Clean old timestamps (older than 1 hour)
    state.request_timestamps = [t for t in state.request_timestamps if now - t < 3600]

    max_per_hour = limits.get("max_per_hour", 200)
    if len(state.request_timestamps) >= max_per_hour:
        # Wait until the oldest timestamp falls out of the window
        oldest = state.request_timestamps[0]
        wait = oldest + 3600 - now
        if wait > 0:
            logger.warning(
                f"Rate limit hit for '{source}' — {max_per_hour}/hour — "
                f"waiting {wait:.0f}s..."
            )
            time.sleep(wait)

    # 3. Random jitter within configured range
    delay_max = limits.get("delay_max", delay_min + 2)
    jitter = random.uniform(0, delay_max - delay_min)
    if jitter > 0:
        time.sleep(jitter)

    # 4. Apply exponential backoff if we've had errors
    if state.consecutive_errors > 0:
        backoff = _calculate_backoff(state.consecutive_errors, limits)
        if backoff > 0:
            logger.debug(
                f"Backoff for '{source}': {backoff:.1f}s "
                f"({state.consecutive_errors} consecutive errors)"
            )
            time.sleep(backoff)

    # Update state
    state.last_request_time = time.time()
    state.request_timestamps.append(state.last_request_time)


def report_success(source: str) -> None:
    """Report a successful request — resets the error counter."""
    state = _get_state(source)
    state.consecutive_errors = 0
    state.backoff_count = 0


def report_error(source: str) -> None:
    """Report a failed request — increments the error counter for backoff."""
    state = _get_state(source)
    state.consecutive_errors += 1
    state.backoff_count += 1


def reset(source: Optional[str] = None) -> None:
    """
    Reset rate limiter state for a source (or all sources).

    Args:
        source: Source name to reset, or None to reset all.
    """
    if source:
        _source_state.pop(source, None)
    else:
        _source_state.clear()
    logger.debug(f"Rate limiter reset for {'all sources' if not source else source}")


# ─── Internal Helpers ────────────────────────────────────────────────────

def _get_limits(source: str) -> dict:
    """Get rate limit config for a source, with defaults."""
    limits = RATE_LIMITS.get(source)
    if not limits:
        limits = {"delay_min": 2, "delay_max": 5, "max_per_hour": 200}
    return limits


def _calculate_backoff(consecutive_errors: int, limits: dict) -> float:
    """
    Calculate exponential backoff delay.

    Base: delay_min * 2^(errors - 1)
    Cap: 60 seconds max

    Args:
        consecutive_errors: Number of consecutive errors.
        limits: Source rate limit config.

    Returns:
        Backoff delay in seconds.
    """
    base_delay = limits.get("delay_min", 2)
    backoff = base_delay * (2 ** (consecutive_errors - 1))
    jitter = random.uniform(0, 0.5 * backoff)  # 50% jitter
    return min(backoff + jitter, 60.0)
