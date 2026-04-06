"""
Role-based access control utility.

Usage in routes:
    from backend.utils.roles import require_role

    @router.post("/admin/something")
    def admin_action(request: Request, _=Depends(require_role("admin"))):
        ...
"""

from fastapi import Request, HTTPException


def require_role(*allowed_roles: str):
    """FastAPI dependency that checks user role from session."""
    def _check(request: Request):
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        role = user.get("role", "viewer")
        if role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return _check
