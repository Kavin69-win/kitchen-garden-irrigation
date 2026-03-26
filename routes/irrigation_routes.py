"""
routes/irrigation_routes.py
────────────────────────────
Manual irrigation / pump control endpoints.

FIX: GET /pump/history used supabase.table() directly (bypassing the
     asyncio.to_thread wrapper in supabase_client).  Replaced with a
     dedicated helper so all DB access goes through the same non-blocking
     path.
"""

from fastapi import APIRouter, HTTPException, Query
from postgrest.exceptions import APIError

from supabase_client import (
    create_pump_event,
    get_pump_history,       # FIX: use helper instead of raw supabase.table()
    handle_db_error,
)
from models import PumpControlRequest

router = APIRouter()


@router.post("/pump/control", status_code=200)
async def control_pump(data: PumpControlRequest):
    """
    Send a manual pump command for a specific device.

    action=ON  → inserts a pump_events row (trigger_source='MANUAL').
    action=OFF → acknowledged only; ESP32 firmware handles the stop.
    """
    if data.action == "ON":
        if data.duration <= 0:
            raise HTTPException(
                status_code=422,
                detail="duration must be > 0 when action is ON",
            )
        try:
            pump_event = await create_pump_event(
                device_id=data.device_id,
                duration_seconds=data.duration,
                trigger_source="MANUAL",
            )
        except APIError as exc:
            raise HTTPException(status_code=400, detail=handle_db_error(exc))

        return {
            "message": f"Pump turned ON for {data.duration} seconds",
            "pump_event": pump_event,
        }

    # action == "OFF" (guaranteed by Literal type in PumpControlRequest)
    return {
        "message": "Pump OFF command acknowledged",
        "device_id": data.device_id,
    }


@router.get("/pump/history")
async def pump_history(
    device_id: str = Query(..., description="UUID of the device"),
    limit: int = Query(20, ge=1, le=100, description="Max events to return"),
):
    """Return the most recent pump_events for a device."""
    try:
        events = await get_pump_history(device_id=device_id, limit=limit)
    except APIError as exc:
        raise HTTPException(status_code=400, detail=handle_db_error(exc))

    return {"device_id": device_id, "pump_events": events}
