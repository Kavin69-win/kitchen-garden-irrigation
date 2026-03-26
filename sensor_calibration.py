"""
sensor_calibration.py
─────────────────────
Capacitive soil moisture sensor calibration for the ESP32 ADC.

Hardware context
────────────────
The system uses a capacitive soil moisture sensor wired to an ESP32
analogue pin.  The ESP32 ADC produces a 12-bit integer (0–4095).

Typical readings for this sensor:
  Dry soil  ≈ 3000  (air / bone-dry soil)
  Wet soil  ≈ 1200  (fully saturated soil)

Because capacitive sensors produce LOWER values when wetter (more
capacitance = longer RC time-constant = lower ADC reading), the
conversion must invert the scale.

Conversion formula
──────────────────
    moisture_percent = (DRY - raw) / (DRY - WET) × 100

Clamped to [0, 100] to handle out-of-range hardware readings.

Calibration
───────────
  raw = 3000  →   0 %  (dry)
  raw = 2100  →  50 %
  raw = 1200  → 100 %  (saturated)

Usage
─────
    from sensor_calibration import convert_raw_moisture, CalibrationError

    pct = convert_raw_moisture(2100)   # → 50.0
    pct = convert_raw_moisture(3000)   # →  0.0
    pct = convert_raw_moisture(1200)   # → 100.0
    pct = convert_raw_moisture(500)    # → 100.0  (clamped)
    pct = convert_raw_moisture(9999)   # raises CalibrationError
"""


# ---------------------------------------------------------------------------
# Calibration constants — adjust these if you recalibrate your sensor
# ---------------------------------------------------------------------------

ADC_DRY: int = 3000   # raw ADC value in completely dry soil / open air
ADC_WET: int = 1200   # raw ADC value in fully saturated soil
ADC_RANGE: int = ADC_DRY - ADC_WET          # = 1800
ADC_MAX_VALID: int = 4095                    # 12-bit ESP32 ADC ceiling


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class CalibrationError(ValueError):
    """Raised when a raw ADC value is outside the hardware range."""


def convert_raw_moisture(raw_value: int | float) -> float:
    """
    Convert a raw capacitive sensor ADC reading to a moisture percentage.

    Parameters
    ----------
    raw_value : int | float
        Raw ADC output from the ESP32 (expected range: 0–4095).

    Returns
    -------
    float
        Soil moisture as a percentage in [0.0, 100.0].

    Raises
    ------
    CalibrationError
        If raw_value is outside the valid ADC hardware range (0–4095).

    Examples
    --------
    >>> convert_raw_moisture(3000)
    0.0
    >>> convert_raw_moisture(2100)
    50.0
    >>> convert_raw_moisture(1200)
    100.0
    >>> convert_raw_moisture(500)   # below WET → clamped to 100
    100.0
    """
    raw = float(raw_value)

    if not (0 <= raw <= ADC_MAX_VALID):
        raise CalibrationError(
            f"Raw ADC value {raw_value} is outside the valid range "
            f"[0, {ADC_MAX_VALID}]. Check sensor wiring."
        )

    moisture = (ADC_DRY - raw) / ADC_RANGE * 100.0

    # Clamp to [0, 100] — readings outside calibrated range are still
    # physically meaningful (very dry or very wet).
    return max(0.0, min(100.0, round(moisture, 2)))


def batch_convert(raw_values: list[int | float]) -> list[float]:
    """
    Convert a list of raw ADC readings to moisture percentages.

    Parameters
    ----------
    raw_values : list[int | float]
        List of raw ADC readings, one per pot.

    Returns
    -------
    list[float]
        Corresponding moisture percentages in the same order.

    Raises
    ------
    CalibrationError
        If any value is outside the hardware ADC range.
    """
    return [convert_raw_moisture(v) for v in raw_values]


# ---------------------------------------------------------------------------
# Self-test (run directly: python sensor_calibration.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_cases = [
        (3000,  0.0,   "dry boundary"),
        (2100, 50.0,   "midpoint"),
        (1200, 100.0,  "wet boundary"),
        (500,  100.0,  "below WET (clamped)"),
        (3500,   0.0,  "above DRY (clamped)"),
    ]

    print(f"{'Raw':>6}  {'Expected':>10}  {'Got':>10}  {'Pass':>5}  Note")
    print("-" * 55)
    all_pass = True
    for raw, expected, note in test_cases:
        result = convert_raw_moisture(raw)
        ok = abs(result - expected) < 0.01
        all_pass = all_pass and ok
        print(f"{raw:>6}  {expected:>10.2f}  {result:>10.2f}  {'✅' if ok else '❌':>5}  {note}")

    print()
    print("All tests passed ✅" if all_pass else "SOME TESTS FAILED ❌")
