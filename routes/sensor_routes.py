"""
routes/sensor_routes.py
───────────────────────
Sensor data ingestion and irrigation decision logic.

UPDATED (kitchen garden):
  - Accepts raw_moisture (raw ADC integer) from ESP32 instead of a
    pre-converted percentage.
  - Converts each raw value to a percentage using
    sensor_calibration.convert_raw_moisture() before storing or
    comparing against plant thresholds.
  - Temperature is now validated against each plant's temperature_min
    and temperature_max.  If the ambient temperature is outside the
    plant's safe range, a notification is added (watering still
    proceeds — you may want to suppress it for extreme heat, but
    that policy decision is left to the operator).
  - Watering only triggers when: moisture_percent < plant.min_moisture
    (unchanged logic, now operating on converted percentages).

Flow for POST /sensor/sensor-data:
  1. Convert each raw ADC reading to a moisture percentage.
  2. Insert one sensor_readings row (temperature + humidity).
  3. Bulk-fetch all pot configs + plant_type thresholds.
  4. Bulk-insert converted moisture percentages into pot_moisture_readings.
  5. For each AUTO pot:
       a. Check temperature against plant thresholds → notification if out of range.
       b. If moisture_percent < min_moisture → queue watering.
  6. Persist pump_event + watering_events for queued pots.
  7. Return the valve schedule to the ESP32.
"""

import math
from fastapi import APIRouter, HTTPException
from postgrest.exceptions import APIError

from sensor_calibration import convert_raw_moisture, CalibrationError
from supabase_client import (
    insert_sensor_reading,
    fetch_pots_by_ids,
    insert_pot_moisture_readings_bulk,
    create_pump_event,
    create_watering_event,
    handle_db_error,
)
from models import SensorDataRequest

router = APIRouter()


# ---------------------------------------------------------------------------
# Temperature alert helper
# ---------------------------------------------------------------------------

def _temperature_alert(
    plant_name: str,
    temperature: float,
    temp_min: int | None,
    temp_max: int | None,
) -> str | None:
    """
    Return an alert string if temperature is outside the plant's safe range,
    or None if everything is fine / no temperature data is available.
    """
    if temperature is None or temp_min is None or temp_max is None:
        return None
    if temperature < temp_min:
        return (
            f"⚠️ Temperature alert for {plant_name}: "
            f"{temperature:.1f}°C is below minimum {temp_min}°C"
        )
    if temperature > temp_max:
        return (
            f"⚠️ Temperature alert for {plant_name}: "
            f"{temperature:.1f}°C exceeds maximum {temp_max}°C"
        )
    return None


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/sensor-data")
async def receive_sensor_data(data: SensorDataRequest):
    """
    Accept a sensor batch from an ESP32 device.

    Each pot entry carries a raw ADC moisture value (raw_moisture).
    The backend converts it to a percentage, stores it, and decides
    whether to water based on the plant's moisture threshold.
    """

    # ── Step 1: convert raw ADC readings → percentages ────────────────────────
    conversion_errors: list[str] = []
    converted_pots: list[dict] = []   # {pot_id, moisture_pct}

    for pot_input in data.pots:
        try:
            moisture_pct = convert_raw_moisture(pot_input.raw_moisture)
        except CalibrationError as exc:
            conversion_errors.append(
                f"Pot {pot_input.pot_id}: invalid raw ADC value "
                f"{pot_input.raw_moisture} – {exc}"
            )
            continue
        converted_pots.append({
            "pot_id": pot_input.pot_id,
            "moisture_pct": moisture_pct,
            "raw_moisture": pot_input.raw_moisture,
        })

    # ── Step 2: persist the environmental reading ─────────────────────────────
    try:
        sensor_row = await insert_sensor_reading(
            device_id=data.device_id,
            temperature=data.temperature,
            humidity=data.humidity,
        )
    except APIError as exc:
        raise HTTPException(status_code=400, detail=handle_db_error(exc))

    sensor_reading_id: str = sensor_row["id"]

    if not converted_pots:
        return {
            "status": "success",
            "sensor_reading_id": sensor_reading_id,
            "pump": {"status": "OFF", "total_duration": 0, "pump_event_id": None},
            "valves": [],
            "notifications": [],
            "warnings": conversion_errors or None,
        }

    # ── Step 3: bulk-fetch all pot configs in ONE query ───────────────────────
    pot_ids = [p["pot_id"] for p in converted_pots]
    try:
        pot_rows = await fetch_pots_by_ids(pot_ids)
    except APIError as exc:
        raise HTTPException(status_code=400, detail=handle_db_error(exc))

    pot_map: dict[str, dict] = {p["id"]: p for p in pot_rows}

    # ── Step 4: bulk-insert converted moisture percentages ────────────────────
    moisture_rows = []
    moisture_errors: list[str] = []

    for cp in converted_pots:
        if cp["pot_id"] not in pot_map:
            moisture_errors.append(f"Pot {cp['pot_id']}: not found or deleted")
            continue
        moisture_rows.append({
            "pot_id": cp["pot_id"],
            "sensor_reading_id": sensor_reading_id,
            "moisture": cp["moisture_pct"],   # stored as percentage
        })

    if moisture_rows:
        try:
            await insert_pot_moisture_readings_bulk(moisture_rows)
        except APIError as exc:
            moisture_errors.append(f"Bulk moisture insert failed: {exc.message}")

    # ── Step 5: irrigation + temperature decisions ────────────────────────────
    watering_queue: list[dict] = []
    notifications: list[str] = []

    for cp in converted_pots:
        pot = pot_map.get(cp["pot_id"])
        if not pot:
            continue

        plant_type = pot.get("plant_types")
        if not plant_type:
            continue

        plant_name   = plant_type.get("name", "Unknown plant")
        mode         = pot["mode"]
        min_moisture = plant_type["min_moisture"]
        pot_size_ml  = pot["pot_size_ml"]
        flow_rate    = pot["flow_rate_ml_per_sec"]
        moisture_pct = cp["moisture_pct"]

        # Temperature alert — notify but do not suppress watering
        alert = _temperature_alert(
            plant_name=plant_name,
            temperature=data.temperature,
            temp_min=plant_type.get("temperature_min"),
            temp_max=plant_type.get("temperature_max"),
        )
        if alert:
            notifications.append(alert)

        # Watering decision: trigger only when moisture < min_moisture
        if mode == "AUTO" and moisture_pct < min_moisture:
            deficit = min_moisture - moisture_pct
            water_needed_ml = (deficit / 100) * pot_size_ml
            duration_sec = math.ceil(water_needed_ml / flow_rate)

            watering_queue.append({
                "pot_id": cp["pot_id"],
                "duration_seconds": duration_sec,
            })
            notifications.append(
                f"💧 {plant_name} (pot {cp['pot_id']}) will be watered "
                f"for {duration_sec}s "
                f"(moisture {moisture_pct:.1f}% < threshold {min_moisture}%, "
                f"raw ADC = {cp['raw_moisture']})"
            )

    # ── Step 6: persist pump + watering events ────────────────────────────────
    valves: list[dict] = []
    pump_event_id: str | None = None
    total_pump_time = sum(t["duration_seconds"] for t in watering_queue)

    if watering_queue:
        try:
            pump_row = await create_pump_event(
                device_id=data.device_id,
                duration_seconds=total_pump_time,
                trigger_source="AUTO",
            )
            pump_event_id = pump_row["id"]
        except APIError as exc:
            raise HTTPException(status_code=500, detail=handle_db_error(exc))

        current_offset = 0
        for task in watering_queue:
            try:
                await create_watering_event(
                    pot_id=task["pot_id"],
                    pump_event_id=pump_event_id,
                    open_time_seconds=current_offset,
                    duration_seconds=task["duration_seconds"],
                )
            except APIError as exc:
                notifications.append(
                    f"Warning: failed to log watering event for pot "
                    f"{task['pot_id']}: {exc.message}"
                )

            valves.append({
                "pot_id": task["pot_id"],
                "open_time": current_offset,
                "duration": task["duration_seconds"],
            })
            current_offset += task["duration_seconds"]

    # ── Step 7: response ──────────────────────────────────────────────────────
    response_body: dict = {
        "status": "success",
        "sensor_reading_id": sensor_reading_id,
        "pump": {
            "status": "ON" if total_pump_time > 0 else "OFF",
            "total_duration": total_pump_time,
            "pump_event_id": pump_event_id,
        },
        "valves": valves,
        "notifications": notifications,
        "converted_moisture": [
            {"pot_id": cp["pot_id"], "raw": cp["raw_moisture"], "pct": cp["moisture_pct"]}
            for cp in converted_pots
        ],
    }

    all_warnings = conversion_errors + moisture_errors
    if all_warnings:
        response_body["warnings"] = all_warnings

    return response_body
