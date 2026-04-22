"""
Simple in-memory rate limiting for send-* endpoints.

Tracks (user_id, onboarding_id, action) with 60-second cooldown per action.
Designed for low-QPS scenarios (payroll operations), not high-traffic APIs.
"""

import time
import logging
from typing import Dict, Tuple

_logger = logging.getLogger("zpay.rate_limit")

# Format: (user_id, onboarding_id, action) -> timestamp of last request
_rate_limit_tracker: Dict[Tuple[int, int, str], float] = {}

COOLDOWN_SECONDS = 60


def check_rate_limit(user_id: int, onboarding_id: int, action: str) -> Tuple[bool, int]:
    """
    Check if the request should be rate-limited.

    Args:
        user_id: ID of the user making the request
        onboarding_id: ID of the onboarding record being acted on
        action: Name of the action (e.g., "send-consent", "send-ed-drug-consent")

    Returns:
        Tuple of (is_allowed: bool, seconds_until_retry: int)
        If is_allowed=False, seconds_until_retry is the time to wait
    """
    key = (user_id, onboarding_id, action)
    now = time.time()

    if key in _rate_limit_tracker:
        last_request = _rate_limit_tracker[key]
        elapsed = now - last_request
        if elapsed < COOLDOWN_SECONDS:
            seconds_until_retry = int(COOLDOWN_SECONDS - elapsed) + 1
            _logger.info(
                "[rate-limit] Blocked: user_id=%d onboarding_id=%d action=%s (retry in %d seconds)",
                user_id,
                onboarding_id,
                action,
                seconds_until_retry,
            )
            return False, seconds_until_retry

    # Request allowed — update tracker
    _rate_limit_tracker[key] = now
    return True, 0
