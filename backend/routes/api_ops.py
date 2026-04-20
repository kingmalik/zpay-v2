"""
Operational endpoints placeholder.
/today and /health live in api_data.py (registered first, take priority).
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["ops"])


@router.get("/debug/firstalt-profile/{driver_id}")
async def debug_firstalt_profile(driver_id: int, request: Request):
    """Return raw FirstAlt driver profile JSON — for field discovery only."""
    import os
    secret = request.headers.get("X-Internal-Secret", "")
    if secret != os.environ.get("ZPAY_INTERNAL_SECRET", ""):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    from backend.services import firstalt_service
    try:
        profile = firstalt_service.get_driver_profile(driver_id)
        return {"driver_id": driver_id, "profile": profile}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
