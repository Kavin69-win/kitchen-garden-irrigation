"""
supabase_client.py
──────────────────
Central Supabase access layer for the Smart Irrigation System.

UPDATED (kitchen garden):
  - fetch_pots_by_ids now selects temperature_min and temperature_max
    from plant_types so the sensor route can check temperature alerts.
  - get_pots_for_device also includes the new temperature columns.
"""
from dotenv import load_dotenv
import os

load_dotenv()
import asyncio
import os
from typing import Any

from supabase import create_client, Client
from postgrest.exceptions import APIError
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Client initialisation
# ---------------------------------------------------------------------------

def _get_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Set it in your .env file or deployment environment."
        )
    return value


def get_client() -> Client:
    url = _get_env("SUPABASE_URL")
    key = _get_env("SUPABASE_KEY")
    return create_client(url, key)


supabase: Client = get_client()


# ---------------------------------------------------------------------------
# Internal helper: run sync Supabase query off the event loop
# ---------------------------------------------------------------------------

async def _run(query) -> Any:
    """Offload a synchronous supabase-py .execute() to a thread-pool worker."""
    return await asyncio.to_thread(query.execute)


# ---------------------------------------------------------------------------
# Device operations
# ---------------------------------------------------------------------------

async def get_devices_for_user(owner_id: str) -> list[dict]:
    """Return all active (non-soft-deleted) devices owned by owner_id."""
    response = await _run(
        supabase.table("devices")
        .select("*")
        .eq("owner_id", owner_id)
        .is_("deleted_at", "null")
    )
    return response.data


async def get_device_by_token(device_token: str) -> dict | None:
    """Look up a device by its hardware token (X-Device-Token header)."""
    response = await _run(
        supabase.table("devices")
        .select("*")
        .eq("device_token", device_token)
        .is_("deleted_at", "null")
        .maybe_single()
    )
    return response.data


# ---------------------------------------------------------------------------
# Pot operations
# ---------------------------------------------------------------------------

async def get_pots_for_device(device_id: str) -> list[dict]:
    """Return all active pots belonging to device_id, joined with plant_types.

    UPDATED: includes temperature_min and temperature_max from plant_types.
    """
    response = await _run(
        supabase.table("pots")
        .select(
            "*, plant_types("
            "id, name, min_moisture, max_moisture, "
            "temperature_min, temperature_max"   # UPDATED
            ")"
        )
        .eq("device_id", device_id)
        .is_("deleted_at", "null")
        .order("position", desc=False)
    )
    return response.data


async def fetch_pots_by_ids(pot_ids: list[str]) -> list[dict]:
    """Bulk-fetch multiple pots with their plant_type in a single query.

    UPDATED: selects temperature_min and temperature_max so the sensor
    route can validate ambient temperature against plant thresholds.
    """
    response = await _run(
        supabase.table("pots")
        .select(
            "id, mode, pot_size_ml, flow_rate_ml_per_sec, "
            "plant_types("
            "id, name, min_moisture, max_moisture, "
            "temperature_min, temperature_max"   # UPDATED
            ")"
        )
        .in_("id", pot_ids)
        .is_("deleted_at", "null")
    )
    return response.data


async def create_pot(
    device_id: str,
    plant_type_id: str | None,
    name: str | None,
    position: int | None,
    pot_size_ml: int,
    flow_rate_ml_per_sec: float,
    mode: str,
) -> dict:
    """Insert a new pot row and return the created record."""
    payload: dict[str, Any] = {
        "device_id": device_id,
        "pot_size_ml": pot_size_ml,
        "flow_rate_ml_per_sec": flow_rate_ml_per_sec,
        "mode": mode,
    }
    if plant_type_id is not None:
        payload["plant_type_id"] = plant_type_id
    if name is not None:
        payload["name"] = name
    if position is not None:
        payload["position"] = position

    response = await _run(supabase.table("pots").insert(payload))
    return response.data[0]


# ---------------------------------------------------------------------------
# Plant type operations
# ---------------------------------------------------------------------------

async def get_all_plant_types() -> list[dict]:
    """Return the full plant_types lookup table (all columns)."""
    response = await _run(
        supabase.table("plant_types").select("*").order("name")
    )
    return response.data


async def get_plant_type(plant_type_id: str) -> dict | None:
    """Fetch a single plant_type by UUID."""
    response = await _run(
        supabase.table("plant_types")
        .select("*")
        .eq("id", plant_type_id)
        .maybe_single()
    )
    return response.data


# ---------------------------------------------------------------------------
# Sensor reading operations
# ---------------------------------------------------------------------------

async def insert_sensor_reading(
    device_id: str,
    temperature: float | None,
    humidity: float | None,
) -> dict:
    """Insert a temperature/humidity reading and return the created row."""
    payload: dict[str, Any] = {"device_id": device_id}
    if temperature is not None:
        payload["temperature"] = temperature
    if humidity is not None:
        payload["humidity"] = humidity

    response = await _run(supabase.table("sensor_readings").insert(payload))
    return response.data[0]


async def insert_pot_moisture_readings_bulk(rows: list[dict]) -> list[dict]:
    """Bulk-insert pot_moisture_readings in one round-trip.

    Each row must contain: pot_id, sensor_reading_id, moisture (percentage).
    """
    response = await _run(
        supabase.table("pot_moisture_readings").insert(rows)
    )
    return response.data


async def insert_pot_moisture_reading(
    pot_id: str,
    sensor_reading_id: str,
    moisture: float,
) -> dict:
    """Insert a single per-pot moisture reading (convenience wrapper)."""
    rows = await insert_pot_moisture_readings_bulk([{
        "pot_id": pot_id,
        "sensor_reading_id": sensor_reading_id,
        "moisture": moisture,
    }])
    return rows[0]


# ---------------------------------------------------------------------------
# Irrigation / pump operations
# ---------------------------------------------------------------------------

async def create_pump_event(
    device_id: str,
    duration_seconds: int,
    trigger_source: str = "AUTO",
) -> dict:
    """Log a pump activation event and return the created row."""
    response = await _run(
        supabase.table("pump_events").insert({
            "device_id": device_id,
            "duration_seconds": duration_seconds,
            "trigger_source": trigger_source,
        })
    )
    return response.data[0]


async def create_watering_event(
    pot_id: str,
    pump_event_id: str | None,
    open_time_seconds: int,
    duration_seconds: int,
) -> dict:
    """Log a per-pot watering event linked to a pump_event row."""
    payload: dict[str, Any] = {
        "pot_id": pot_id,
        "open_time_seconds": open_time_seconds,
        "duration_seconds": duration_seconds,
    }
    if pump_event_id is not None:
        payload["pump_event_id"] = pump_event_id

    response = await _run(supabase.table("watering_events").insert(payload))
    return response.data[0]


async def get_pump_history(device_id: str, limit: int = 20) -> list[dict]:
    """Return the most recent pump_events for a device."""
    response = await _run(
        supabase.table("pump_events")
        .select("*")
        .eq("device_id", device_id)
        .order("started_at", desc=True)
        .limit(limit)
    )
    return response.data


# ---------------------------------------------------------------------------
# Shared error helper
# ---------------------------------------------------------------------------

def handle_db_error(exc: APIError) -> dict:
    """Convert a postgrest APIError into a JSON-serialisable dict."""
    return {
        "db_error": exc.message,
        "code": exc.code,
        "details": exc.details,
    }
