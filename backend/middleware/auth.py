"""
Multi-user auth middleware — DB-backed with env-var fallback.

Primary path: looks up users in the `user_account` table (added in migration
x3y4z5a6b7c8). Each user has a role (admin / operator / associate) that
downstream routes can gate on via backend.utils.permissions.require_role.

Fallback path: if the DB isn't reachable OR a username isn't found in DB,
falls back to the legacy env-var registry (ZPAY_PASSWORD_HASH_MALIK / MOM).
This keeps production running through the cutover. Remove the fallback
once the DB path is verified live.

Session cookie contents (unchanged shape, plus user_id):
  { user_id, username, display_name, color, initials, role }
"""

import os
import json
import logging
import bcrypt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

logger = logging.getLogger("zpay.auth")

COOKIE_NAME = "zpay_session"
MAX_AGE = 30 * 24 * 60 * 60  # 30 days

PUBLIC_PREFIXES = (
    "/login",
    "/static",
    "/health",
    "/out",
    "/api/data/paychex-bot/store-session",
    "/api/data/onboarding/join",      # legacy / direct frontend path
    "/api/v1/onboarding/join",        # proxied path Railway actually sees
    "/api/data/onboarding/apply",     # self-service driver signup
    "/api/v1/onboarding/apply",       # proxied path Railway actually sees
    "/api/v1/onboarding/webhook",     # Adobe Sign webhook (no session)
    "/api/v1/error-report",           # Frontend crash reports (no session — page may be broken)
    "/webhooks/whatsapp",             # Twilio WhatsApp webhook (no session)
    "/webhooks/adobe-sign",           # Adobe Sign drug test consent webhook (no session)
    "/dispatch/monitor/diag",         # Public read-only scheduler diagnostic — no secrets, GET only
)

_WEAK_SECRET = "change-me-in-production-zpay-2026"

# ── Env-var fallback user registry ────────────────────────────
# Only used if the DB lookup fails (e.g. during the initial migration window
# or in a fresh dev env). Once Phase 1 is verified live this block can be
# deleted safely.
def _get_env_users() -> dict:
    return {
        "malik": {
            "user_id": None,   # env-fallback users have no DB row
            "username": "malik",
            "full_name": "Malik Milion",
            "display_name": os.environ.get("ZPAY_DISPLAY_MALIK", "Malik"),
            "password_hash": os.environ.get("ZPAY_PASSWORD_HASH_MALIK", ""),
            "role": "admin",
            "color": "#4facfe",
            "initials": "M",
        },
        "mom": {
            "user_id": None,
            "username": "mom",
            "full_name": "Zubeda Adem",
            "display_name": os.environ.get("ZPAY_DISPLAY_MOM", "Mom"),
            "password_hash": os.environ.get("ZPAY_PASSWORD_HASH_MOM", ""),
            "role": "operator",   # Mom is operator, not admin
            "color": "#764ba2",
            "initials": "♡",
        },
    }


# Legacy alias (do not remove while other modules still import it)
def get_users() -> dict:
    """Env-based user registry — legacy fallback only. Returns safe dicts (no password_hash)."""
    return {
        k: {kk: vv for kk, vv in v.items() if kk != "password_hash"}
        for k, v in _get_env_users().items()
    }


def _lookup_user_in_db(username: str) -> dict | None:
    """
    Fetch a user from the user_account table. Returns a dict with the same
    shape as _get_env_users entries (includes password_hash), or None if
    the DB is unreachable or the username doesn't exist.
    """
    try:
        from backend.db import SessionLocal
        from backend.db.models import UserAccount
    except Exception as e:
        logger.debug("DB imports unavailable for user lookup: %s", e)
        return None

    db = None
    try:
        db = SessionLocal()
        row = (
            db.query(UserAccount)
            .filter(UserAccount.username == username.lower().strip())
            .filter(UserAccount.active == True)  # noqa: E712
            .first()
        )
        if not row:
            return None
        return {
            "user_id": row.user_id,
            "username": row.username,
            "full_name": row.full_name,
            "display_name": row.display_name,
            "password_hash": row.password_hash or "",
            "role": row.role,
            "color": row.color,
            "initials": row.initials,
        }
    except Exception as e:
        logger.warning("DB user lookup failed for %s: %s — falling back to env", username, e)
        return None
    finally:
        if db:
            db.close()


def _stamp_login(user_id: int | None) -> None:
    """Update last_login_at for a DB user. Best-effort, never raises."""
    if not user_id:
        return
    try:
        from datetime import datetime, timezone
        from backend.db import SessionLocal
        from backend.db.models import UserAccount
        db = SessionLocal()
        try:
            db.query(UserAccount).filter(UserAccount.user_id == user_id).update(
                {"last_login_at": datetime.now(timezone.utc)}
            )
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.debug("last_login stamp failed for user_id=%s: %s", user_id, e)

def _get_signer() -> URLSafeTimedSerializer:
    secret = os.environ.get("ZPAY_SECRET_KEY", "")
    if not secret or secret == _WEAK_SECRET:
        raise RuntimeError(
            "ZPAY_SECRET_KEY is missing or set to the default. "
            "Generate a strong key: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
        )
    return URLSafeTimedSerializer(secret)

def verify_session(cookie_value: str) -> dict | None:
    """Return user dict if valid, else None."""
    try:
        data = _get_signer().loads(cookie_value, max_age=MAX_AGE)
        if isinstance(data, dict) and "username" in data:
            return data
        return None
    except (BadSignature, SignatureExpired):
        return None

def create_session(
    username: str,
    display_name: str,
    color: str,
    initials: str,
    role: str = "associate",
    user_id: int | None = None,
) -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "display_name": display_name,
        "color": color,
        "initials": initials,
        "role": role,
    }
    return _get_signer().dumps(payload)


def authenticate(username: str, password: str) -> dict | None:
    """
    Return a safe user dict (no password_hash) if credentials match.
    Tries DB first, then falls back to env-var registry.
    """
    uname = username.lower().strip()
    pwd = password.strip().encode("utf-8")

    # 1) DB lookup (preferred)
    db_user = _lookup_user_in_db(uname)
    if db_user and db_user.get("password_hash"):
        try:
            if bcrypt.checkpw(pwd, db_user["password_hash"].encode("utf-8")):
                _stamp_login(db_user.get("user_id"))
                return {k: v for k, v in db_user.items() if k != "password_hash"}
        except (ValueError, TypeError) as e:
            logger.error("Bcrypt verification error for DB user %s: %s", uname, e)

    # 2) Env-var fallback
    env_users = _get_env_users()
    env_user = env_users.get(uname)
    if not env_user:
        return None
    stored_hash = env_user.get("password_hash", "")
    if not stored_hash:
        logger.warning("No password hash configured for env-user: %s", uname)
        return None
    try:
        if bcrypt.checkpw(pwd, stored_hash.encode("utf-8")):
            logger.info("User %s authenticated via ENV fallback (DB miss)", uname)
            return {k: v for k, v in env_user.items() if k != "password_hash"}
    except (ValueError, TypeError) as e:
        logger.error("Bcrypt verification error for env-user %s: %s", uname, e)
    return None


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path

        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        cookie = request.cookies.get(COOKIE_NAME)
        user = verify_session(cookie) if cookie else None
        if user:
            request.state.user = user
            return await call_next(request)

        return RedirectResponse(url="/login", status_code=302)
