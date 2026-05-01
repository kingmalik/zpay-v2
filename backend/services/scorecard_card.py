"""
backend/services/scorecard_card.py
===================================
Helper for generating public driver scorecard links.

Phase 10 (SMS/email cron) will import build_card_link() to include in
outbound messages. This module is intentionally thin — just URL construction.

Usage
-----
    from backend.services.scorecard_card import build_card_link

    url = build_card_link(person_id=42)
    # → "https://frontend-ruddy-ten-82.vercel.app/driver/42/scorecard"
"""

import os

# Default matches the current Vercel deploy. Override with PUBLIC_BASE_URL env
# var in Railway/Vercel so Phase 10 cron always produces the right domain.
_DEFAULT_BASE = "https://frontend-ruddy-ten-82.vercel.app"


def build_card_link(person_id: int) -> str:
    """Return the public scorecard URL for a driver.

    Args:
        person_id: The driver's person_id from the person table.

    Returns:
        Fully-qualified public URL, e.g.
        "https://frontend-ruddy-ten-82.vercel.app/driver/42/scorecard"
    """
    base = os.environ.get("PUBLIC_BASE_URL", _DEFAULT_BASE).rstrip("/")
    return f"{base}/driver/{person_id}/scorecard"
