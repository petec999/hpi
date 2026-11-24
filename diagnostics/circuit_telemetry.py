"""Read-only derived HaierPi circuit diagnostics for PR #7.

All temperatures in degrees Celsius, pressures in MPa.
None of these values is a control or safety decision.
"""
from dataclasses import dataclass
from math import isfinite
from typing import Optional


@dataclass(frozen=True)
class CircuitSample:
    twi: float  # water entering heat pump, return
    two: float  # water leaving heat pump, supply
    tao: float  # outside ambient from outdoor unit
    tsat_ps_actual: float  # evaporating saturation temperature
    tsat_pd_actual: float  # condensing saturation temperature
    td: float  # discharge temperature
    ps_actual: float  # suction pressure MPa
    pd_actual: float  # discharge pressure MPa
    compressor_actual_hz: float
    compressor_target_hz: float
    eev_level: Optional[float] = None


def _num(value, lower, upper):
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError("Missing, nonnumeric or nonfinite circuit measurement")
    if not lower <= value <= upper:
        raise ValueError("Circuit measurement outside sanity limits")
    return float(value)


def derive(sample: CircuitSample, *, r141_fresh: bool, r241_fresh: bool):
    """Return six additional metrics or None while either block is stale.

    Sanity bounds are broad input-validation guards, NOT operating specifications.
    Sensor signs are preserved. Division by suction pressure is excluded.
    """
    if r141_fresh is not True or r241_fresh is not True:
        return None
    twi = _num(sample.twi, -40, 100)
    two = _num(sample.two, -40, 100)
    tao = _num(sample.tao, -60, 70)
    evap = _num(sample.tsat_ps_actual, -80, 90)
    cond = _num(sample.tsat_pd_actual, -60, 120)
    td = _num(sample.td, -60, 160)
    ps = _num(sample.ps_actual, 0, 10)
    pd = _num(sample.pd_actual, 0, 10)
    fact = _num(sample.compressor_actual_hz, 0, 250)
    fset = _num(sample.compressor_target_hz, 0, 250)
    if sample.eev_level is not None:
        _num(sample.eev_level, 0, 10000)
    return {
        "water_delta_t": round(two - twi, 2),
        "saturation_lift": round(cond - evap, 2),
        "ambient_evaporating_approach": round(tao - evap, 2),
        "discharge_condensing_gap": round(td - cond, 2),
        "pressure_delta_mpa": round(pd - ps, 4),
        "compressor_frequency_error_hz": round(fset - fact, 2),
    }
