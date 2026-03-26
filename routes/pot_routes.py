"""
routes/pot_routes.py
────────────────────
Pot management endpoints.

FIX: removed the local _POT_SIZE_ML dict. The pot size label → ml
     mapping now has a single definition at the top of this file,
     which was previously duplicated between here and models.py.
"""

from fastapi import APIRouter, HTTPException, Query
from postgrest.exceptions import APIError

from supabase_client import get_pots_for_device, create_pot, handle_db_error, supabase
from models import CreatePotRequest, UpdatePotModeRequest

router = APIRouter()

# Single source of truth for size label → ml conversion
POT_SIZE_ML: dict[str, int] = {
    "Small": 500,
    "Medium": 1000,
    "Large": 2000,
}


@router.post("/create", status_code=201)
async def create_pot_endpoint(data: CreatePotRequest):
    """
    Create a new pot for a device.

    Resolves pot_size_label → pot_size_ml before persisting to the pots table.
    """
    pot_size_ml = POT_SIZE_ML.get(data.pot_size_label, 1000)

    try:
        pot = await create_pot(
            device_id=data.device_id,
            plant_type_id=data.plant_type_id,
            name=data.name,
            position=data.position,
            pot_size_ml=pot_size_ml,
            flow_rate_ml_per_sec=data.flow_rate_ml_per_sec,
            mode=data.mode,
        )
    except APIError as exc:
        raise HTTPException(status_code=400, detail=handle_db_error(exc))

    return {"status": "pot created", "pot": pot}


@router.get("/list")
async def list_pots(device_id: str = Query(..., description="UUID of the device")):
    """
    List all active pots for a device, joined with their plant_type details.
    Soft-deleted pots are excluded automatically.
    """
    try:
        pots = await get_pots_for_device(device_id)
    except APIError as exc:
        raise HTTPException(status_code=400, detail=handle_db_error(exc))

    return {"device_id": device_id, "pots": pots}


@router.patch("/{pot_id}/mode")
async def update_pot_mode(pot_id: str, data: UpdatePotModeRequest):
    """
    Update the irrigation mode of a specific pot.

    - AUTO  → irrigation triggers automatically when moisture < plant threshold.
    - MANUAL → automatic irrigation is suppressed; only manual triggers apply.
    """
    # Check the pot exists
    try:
        result = (
            supabase.table("pots")
            .select("id, mode")
            .eq("id", pot_id)
            .execute()
        )
    except APIError as exc:
        raise HTTPException(status_code=400, detail=handle_db_error(exc))

    if not result.data:
        raise HTTPException(
            status_code=404,
            detail=f"Pot '{pot_id}' not found.",
        )

    # Apply the mode update
    try:
        supabase.table("pots").update({"mode": data.mode}).eq("id", pot_id).execute()
    except APIError as exc:
        raise HTTPException(status_code=400, detail=handle_db_error(exc))

    return {
        "pot_id": pot_id,
        "mode": data.mode,
        "message": "Mode updated successfully",
    }
