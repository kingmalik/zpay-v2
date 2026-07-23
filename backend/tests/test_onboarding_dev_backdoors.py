"""
Tests for the S6 security-cleanup fix: dev-only onboarding backdoors
(token=="dev" on /join, /join/.../step, dev-skip-step, dev-skip-all) must be
gated on BOTH ZPAY_ALLOW_DEV_TOOLS=1 AND "not production" — defense in depth
so a stray ZPAY_ALLOW_DEV_TOOLS=1 left set in a Railway env can't reopen a
"skip onboarding" backdoor in prod.

This targets backend.routes.onboarding._dev_tools_allowed() directly (module
reload + monkeypatched env), rather than booting the full app, since the
production flag is computed once at import time (same pattern as app.py /
middleware/csrf.py / middleware/security_headers.py / routes/auth.py).

Run in isolation:
    PYTHONPATH=/path/to/zpay-v2-fresh pytest backend/tests/test_onboarding_dev_backdoors.py -v
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault(
    "ZPAY_SECRET_KEY",
    "test-secret-dev-backdoors-long-enough-to-pass",
)
os.environ.setdefault("DATABASE_URL", "sqlite://")


def _reload_onboarding_module():
    """Import (or re-import) backend.routes.onboarding so module-level
    _is_production picks up the currently-patched environment."""
    import backend.routes.onboarding as onboarding_mod
    importlib.reload(onboarding_mod)
    return onboarding_mod


class TestDevToolsGating:
    def teardown_method(self):
        # Restore a clean default state for any test file run after this one
        # in the same session (defensive — this file is meant to run in isolation).
        for var in ("ZPAY_ALLOW_DEV_TOOLS", "ZPAY_PRODUCTION", "RAILWAY_ENVIRONMENT"):
            os.environ.pop(var, None)
        _reload_onboarding_module()

    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("ZPAY_ALLOW_DEV_TOOLS", raising=False)
        monkeypatch.delenv("ZPAY_PRODUCTION", raising=False)
        monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
        mod = _reload_onboarding_module()
        assert mod._dev_tools_allowed() is False

    def test_enabled_in_dev_when_flag_explicitly_set(self, monkeypatch):
        monkeypatch.setenv("ZPAY_ALLOW_DEV_TOOLS", "1")
        monkeypatch.delenv("ZPAY_PRODUCTION", raising=False)
        monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
        mod = _reload_onboarding_module()
        assert mod._dev_tools_allowed() is True

    def test_blocked_in_production_via_railway_environment_even_if_flag_set(self, monkeypatch):
        monkeypatch.setenv("ZPAY_ALLOW_DEV_TOOLS", "1")
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        mod = _reload_onboarding_module()
        assert mod._dev_tools_allowed() is False

    def test_blocked_in_production_via_zpay_production_even_if_flag_set(self, monkeypatch):
        monkeypatch.setenv("ZPAY_ALLOW_DEV_TOOLS", "1")
        monkeypatch.setenv("ZPAY_PRODUCTION", "1")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
        mod = _reload_onboarding_module()
        assert mod._dev_tools_allowed() is False

    def test_flag_alone_without_prod_vars_is_sufficient_for_dev(self, monkeypatch):
        """Sanity check — dev tools must still work in a real local/dev shell
        with no RAILWAY_ENVIRONMENT / ZPAY_PRODUCTION at all."""
        monkeypatch.setenv("ZPAY_ALLOW_DEV_TOOLS", "1")
        monkeypatch.delenv("ZPAY_PRODUCTION", raising=False)
        monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
        mod = _reload_onboarding_module()
        assert mod._dev_tools_allowed() is True
