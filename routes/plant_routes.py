"""
routes/plant_routes.py
──────────────────────
Plant type reference data endpoints.

Previously: this file was empty (plant types lived as a hardcoded dict
inside sensor_routes.py as PLANT_TYPES).

Now: all plant type data is fetched from the plant_types table in Supabase.
The table is seeded by the schema migration with three default entries:
  - Cactus / Succulent
  - Tropical Foliage
  - General Potted Plant
"""

from fastapi import APIRouter, HTTPException
from postgrest.exceptions import APIError

from supabase_client import get_all_plant_types, get_plant_type, handle_db_error

router = APIRouter()


@router.get("/")
async def list_plant_types():
    """Return all plant types (public, no auth required)."""
    try:
        plant_types = await get_all_plant_types()
    except APIError as exc:
        raise HTTPException(status_code=500, detail=handle_db_error(exc))

    return {"plant_types": plant_types}


@router.get("/{plant_type_id}")
async def get_plant_type_detail(plant_type_id: str):
    """Return a single plant type by UUID."""
    try:
        plant_type = await get_plant_type(plant_type_id)
    except APIError as exc:
        raise HTTPException(status_code=400, detail=handle_db_error(exc))

    if not plant_type:
        raise HTTPException(status_code=404, detail="Plant type not found")

    return plant_type
