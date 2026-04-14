"""
Role-based permission helpers.

Use like:

    from fastapi import Depends
    from backend.utils.permissions import require_admin, require_manager_or_admin

    @router.get("/team", dependencies=[Depends(require_admin)])
    async def list_team(...):
        ...

Or imperatively inside a route:

    from backend.utils.permissions import get_current_user, check_role

    user = get_current_user(request)
    check_role(user, "admin")

Roles hierarchy (strings):
    admin      — full access (Malik)
    operator   — full access minus explicit admin-only (Mom)
    associate  — scoped to their assigned tasks + role view (new hires)

The `request.state.user` is set by the auth middleware after it verifies
the session cookie.
"""

from __future__ import annotations

from typing import Iterable

from fastapi import HTTPException, Request, status


_ROLE_RANK = {"associate": 1, "operator": 2, "admin": 3}


def get_current_user(request: Request) -> dict:
    """Return the authenticated user dict from the request, or 401 if none."""
    user = getattr(request.state, "user", None)
    if not user or not isinstance(user, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    return user


def check_role(user: dict, *allowed_roles: str) -> None:
    """Raise 403 unless user.role is in allowed_roles."""
    role = (user.get("role") or "").lower()
    if role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires role: {', '.join(allowed_roles)}.",
        )


def require_role(*allowed_roles: str):
    """
    Dependency factory. Usage:
        @router.get("/x", dependencies=[Depends(require_role('admin'))])
    """
    def _dep(request: Request) -> dict:
        user = get_current_user(request)
        check_role(user, *allowed_roles)
        return user
    return _dep


# Convenience dependencies
def require_admin(request: Request) -> dict:
    user = get_current_user(request)
    check_role(user, "admin")
    return user


def require_manager_or_admin(request: Request) -> dict:
    """Mom or Malik. Gates everything that's not associate-scoped."""
    user = get_current_user(request)
    check_role(user, "admin", "operator")
    return user


def require_any_role(request: Request) -> dict:
    """Any authenticated user — enforces login but no role restriction."""
    return get_current_user(request)


def is_admin(user: dict) -> bool:
    return (user.get("role") or "").lower() == "admin"


def is_operator(user: dict) -> bool:
    return (user.get("role") or "").lower() == "operator"


def is_associate(user: dict) -> bool:
    return (user.get("role") or "").lower() == "associate"


def role_at_least(user: dict, minimum: str) -> bool:
    """True if user.role ≥ minimum in the hierarchy."""
    have = _ROLE_RANK.get((user.get("role") or "").lower(), 0)
    need = _ROLE_RANK.get(minimum.lower(), 0)
    return have >= need
