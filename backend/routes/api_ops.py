"""
Operational endpoints placeholder.
/today and /health live in api_data.py (registered first, take priority).
"""
from fastapi import APIRouter

router = APIRouter(tags=["ops"])
