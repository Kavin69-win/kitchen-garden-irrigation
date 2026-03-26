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

from supabase_client import get_pots_for_device, create_pot, handle_db_error
from models import CreatePotRequest

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
