"""
models.py
─────────
Pydantic v2 request models for the Smart Irrigation API.

UPDATED (kitchen garden):
  - PotMoistureInput now accepts raw_moisture (raw ADC integer) instead
    of a pre-converted percentage.  Conversion happens server-side via
    sensor_calibration.convert_raw_moisture() before any DB writes.
  - SensorDataRequest: temperature field retained for plant threshold
    checking.  The route will compare it against each plant's
    temperature_min / temperature_max.
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pot models
# ---------------------------------------------------------------------------

class CreatePotRequest(BaseModel):
    device_id: str = Field(..., description="UUID of the owning device")
    plant_type_id: str | None = Field(None, description="UUID of the plant type")
    name: str | None = Field(None, description="Human-friendly pot name")
    position: int | None = Field(None, ge=1, description="Valve slot (1-indexed)")
    pot_size_label: Literal["Small", "Medium", "Large"] = Field(
        "Medium", description="Pot size shortcut (resolved to ml server-side)"
    )
    flow_rate_ml_per_sec: float = Field(
        20.0, gt=0, description="Valve flow rate in ml/s"
    )
    mode: Literal["AUTO", "MANUAL"] = Field("AUTO")


# ---------------------------------------------------------------------------
# Sensor models
# ---------------------------------------------------------------------------

class PotMoistureInput(BaseModel):
    pot_id: str = Field(..., description="UUID of the pot")

    # UPDATED: accepts raw ADC integer from the ESP32.
    # Valid hardware range for a 12-bit ESP32 ADC is 0–4095.
    # The route converts this to a percentage before storage.
    raw_moisture: int = Field(
        ...,
        ge=0,
        le=4095,
        description=(
            "Raw capacitive sensor ADC reading (0–4095). "
            "Dry soil ≈ 3000, wet soil ≈ 1200. "
            "Converted server-side to a 0–100% percentage."
        ),
    )


class SensorDataRequest(BaseModel):
    device_id: str = Field(..., description="UUID of the reporting device")
    temperature: float | None = Field(
        None,
        ge=-40,
        le=125,
        description="Ambient temperature in °C (used for plant threshold alerts)",
    )
    humidity: float | None = Field(None, ge=0, le=100)
    pots: list[PotMoistureInput] = Field(
        default_factory=list,
        description="Per-pot raw ADC moisture readings in this batch",
    )


# ---------------------------------------------------------------------------
# Irrigation / pump models
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Pot mode update model
# ---------------------------------------------------------------------------

class UpdatePotModeRequest(BaseModel):
    mode: Literal["AUTO", "MANUAL"] = Field(
        ..., description="Irrigation mode for the pot"
    )


# ---------------------------------------------------------------------------
# Irrigation / pump models
# ---------------------------------------------------------------------------

class PumpControlRequest(BaseModel):
    device_id: str = Field(..., description="UUID of the device to control")
    action: Literal["ON", "OFF"] = Field(..., description="Desired pump state")
    duration: int = Field(0, ge=0, description="Run time in seconds (used when action=ON)")
