"""
routes/device_routes.py
───────────────────────
Device management endpoints.

Previously: device data existed only as keys in the POTS mock dict.
Now: full CRUD against the devices table in Supabase.
"""

from fastapi import APIRouter, HTTPException, Query
from postgrest.exceptions import APIError

from supabase_client import get_devices_for_user, handle_db_error

router = APIRouter()


@router.get("/")
async def list_devices(owner_id: str = Query(..., description="UUID of the user")):
    """
    Return all active devices registered to *owner_id*.

    Soft-deleted devices (deleted_at IS NOT NULL) are excluded.
    """
    try:
        devices = await get_devices_for_user(owner_id)
    except APIError as exc:
        raise HTTPException(status_code=400, detail=handle_db_error(exc))

    return {"owner_id": owner_id, "devices": devices}
