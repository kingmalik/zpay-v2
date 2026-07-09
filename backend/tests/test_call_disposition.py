"""
Tests for POST /dispatch/notifications/{id}/disposition

Run with:
    PYTHONPATH=. pytest backend/tests/test_call_disposition.py -x -v

Stub-session style (matches test_reliability_drilldown.py) — no Postgres.
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.routes.dispatch_overrides import (
    DispositionBody,
    VALID_DISPOSITIONS,
    record_call_disposition,
)


def _fake_notif(notif_id: int = 1):
    notif = MagicMock()
    notif.id = notif_id
    notif.person_id = 7
    notif.trip_ref = "12345"
    notif.source = "firstalt"
    notif.pickup_time = "07:45 AM"
    notif.trip_status = "SCHEDULED"
    notif.snoozed_until = None
    notif.manually_resolved_at = None
    notif.manually_resolved_by = None
    notif.last_escalated_at = None
    notif.dedup_suppressed = False
    notif.dedup_primary_notif_id = None
    return notif


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("disposition", VALID_DISPOSITIONS)
def test_valid_dispositions_write_event(disposition):
    db = MagicMock()
    notif = _fake_notif()
    with patch("backend.routes.dispatch_overrides._notif_or_404", return_value=notif), \
         patch("backend.routes.dispatch_overrides._write_event") as mock_write:
        mock_write.return_value = MagicMock(id=99)
        resp = _run(record_call_disposition(1, DispositionBody(disposition=disposition), db))

    assert resp.status_code == 200
    mock_write.assert_called_once()
    args = mock_write.call_args[0]
    assert args[2] == "call_disposition"
    assert args[3]["disposition"] == disposition
    db.commit.assert_called_once()


def test_invalid_disposition_rejected():
    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        _run(record_call_disposition(1, DispositionBody(disposition="maybe"), db))
    assert exc.value.status_code == 422
    db.commit.assert_not_called()


def test_note_is_included_in_payload():
    db = MagicMock()
    notif = _fake_notif()
    with patch("backend.routes.dispatch_overrides._notif_or_404", return_value=notif), \
         patch("backend.routes.dispatch_overrides._write_event") as mock_write:
        mock_write.return_value = MagicMock(id=99)
        _run(record_call_disposition(
            1, DispositionBody(disposition="answered", note="5 min out"), db,
        ))
    assert mock_write.call_args[0][3]["note"] == "5 min out"


def test_missing_notification_404s():
    db = MagicMock()
    with patch(
        "backend.routes.dispatch_overrides._notif_or_404",
        side_effect=HTTPException(status_code=404, detail="not found"),
    ):
        with pytest.raises(HTTPException) as exc:
            _run(record_call_disposition(999, DispositionBody(disposition="answered"), db))
    assert exc.value.status_code == 404
