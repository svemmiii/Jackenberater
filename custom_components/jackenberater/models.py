"""Small data models used by JackenBerater."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class WeatherPoint:
    """Normalized weather observation/forecast point."""

    dt: datetime
    temperature_c: float
    humidity: float | None = None
    wind_kmh: float | None = None
    gust_kmh: float | None = None
    cloud_coverage: float | None = None
    precipitation_probability: float | None = None
    precipitation_mm: float | None = None
    condition: str | None = None


@dataclass(slots=True)
class ThermalResult:
    """One thermal assessment."""

    effective_temperature_c: float
    jacket: str
    wind_penalty_c: float
    transition_penalty_c: float
    solar_gain_c: float
    rain_penalty_c: float
    humidity_adjustment_c: float
    threshold_margin_c: float
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Recommendation:
    """Complete card recommendation."""

    jacket_now: str
    jacket_later: str
    later_at: datetime | None
    rain_status: str
    display_mode: str
    horizon_hours: int
    effective_now_c: float
    min_effective_c: float
    max_effective_c: float
    confidence: float
    reasons: list[str]
    current_temperature_c: float
    current_wind_kmh: float | None
    current_gust_kmh: float | None
    current_condition: str | None
    transition_penalty_c: float
    current_wind_penalty_c: float = 0.0
    later_temperature_c: float | None = None
    later_wind_kmh: float | None = None
    later_gust_kmh: float | None = None
    later_condition: str | None = None
    later_effective_c: float | None = None
    later_wind_penalty_c: float | None = None
    work_context: bool = False
    work_jacket: str | None = None
    work_start: datetime | None = None
    work_name: str | None = None
    calendar_context: bool = False
    source: str = "home"

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("later_at", "work_start"):
            value = result.get(key)
            if isinstance(value, datetime):
                result[key] = value.isoformat()
        return result
