"""Home Assistant weather normalization and lightweight forecast cache."""
from __future__ import annotations

from datetime import datetime
import logging
import math
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import DistanceConverter, TemperatureConverter
from homeassistant.const import UnitOfLength, UnitOfTemperature

from .const import CONF_WEATHER, CONF_WORK_WEATHER, FORECAST_REFRESH
from .models import WeatherPoint

_LOGGER = logging.getLogger(__name__)


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _bounded(value: Any, minimum: float, maximum: float) -> float | None:
    """Return a finite provider number only when it is physically plausible."""
    number = _float(value)
    if number is None or not minimum <= number <= maximum:
        return None
    return number


def _wind_to_kmh(value: Any, unit: str | None) -> float | None:
    number = _bounded(value, 0.0, 500.0)
    if number is None:
        return None
    normalized = (unit or "km/h").strip().lower()
    converted: float | None = None
    if normalized in {"km/h", "kmh", "kph"}:
        converted = number
    elif normalized in {"m/s", "mps"}:
        converted = number * 3.6
    elif normalized in {"mph", "mi/h"}:
        converted = number * 1.609344
    elif normalized in {"ft/s", "fps"}:
        converted = number * 1.09728
    elif normalized in {"kn", "kt", "knot", "knots"}:
        converted = number * 1.852
    if normalized in {"beaufort", "bft", "bf"}:
        # Standard empirical Beaufort equivalent: v = 0.836 * B^(3/2) m/s.
        if number > 12.0:
            return None
        beaufort = number
        converted = 0.836 * (beaufort ** 1.5) * 3.6
    if converted is not None:
        return converted if converted <= 500.0 else None
    # Unknown units must never be treated as km/h silently.
    return None


def _temperature_to_c(value: Any, unit: str | None) -> float | None:
    number = _float(value)
    if number is None:
        return None
    if not unit or unit == UnitOfTemperature.CELSIUS:
        return number if -100.0 <= number <= 70.0 else None
    try:
        converted = float(TemperatureConverter.convert(number, unit, UnitOfTemperature.CELSIUS))
        return converted if math.isfinite(converted) and -100.0 <= converted <= 70.0 else None
    except (HomeAssistantError, TypeError, ValueError):
        return None



def _precipitation_to_mm(value: Any, unit: str | None) -> float | None:
    number = _bounded(value, 0.0, 10000.0)
    if number is None:
        return None
    from_unit = unit or UnitOfLength.MILLIMETERS
    try:
        converted = float(DistanceConverter.convert(number, from_unit, UnitOfLength.MILLIMETERS))
        return converted if math.isfinite(converted) and 0.0 <= converted <= 10000.0 else None
    except (HomeAssistantError, TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = dt_util.parse_datetime(value)
    else:
        return None
    if result is None:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=dt_util.UTC)
    return dt_util.as_local(result)


def current_weather(hass: HomeAssistant, entity_id: str) -> WeatherPoint | None:
    """Read the current weather state without network I/O."""
    state = hass.states.get(entity_id)
    if state is None or state.state in {"unknown", "unavailable"}:
        return None
    attrs = state.attributes
    unit = attrs.get("temperature_unit") or hass.config.units.temperature_unit
    temp = _temperature_to_c(attrs.get("temperature"), unit)
    if temp is None:
        return None
    wind_unit = attrs.get("wind_speed_unit")
    precipitation_unit = attrs.get("precipitation_unit") or hass.config.units.accumulated_precipitation_unit
    return WeatherPoint(
        dt=dt_util.now(),
        temperature_c=temp,
        humidity=_bounded(attrs.get("humidity"), 0.0, 100.0),
        wind_kmh=_wind_to_kmh(attrs.get("wind_speed"), wind_unit),
        gust_kmh=_wind_to_kmh(attrs.get("wind_gust_speed"), wind_unit),
        cloud_coverage=_bounded(attrs.get("cloud_coverage"), 0.0, 100.0),
        precipitation_probability=_bounded(attrs.get("precipitation_probability"), 0.0, 100.0),
        precipitation_mm=_precipitation_to_mm(attrs.get("precipitation"), precipitation_unit),
        condition=state.state,
    )


def indoor_temperature_c(
    hass: HomeAssistant,
    entity_id: str | None,
    fallback_c: float,
) -> float:
    """Return configured indoor temperature or the explicit fallback."""
    if not entity_id:
        return fallback_c
    state = hass.states.get(entity_id)
    if state is None or state.state in {"unknown", "unavailable"}:
        return fallback_c
    number = _float(state.state)
    if number is None:
        return fallback_c
    unit = state.attributes.get("unit_of_measurement") or hass.config.units.temperature_unit
    converted = _temperature_to_c(number, unit)
    return fallback_c if converted is None else converted


def normalize_forecast(
    hass: HomeAssistant,
    entity_id: str,
    raw_items: Any,
) -> list[WeatherPoint]:
    """Normalize up to 24 hourly provider points into stable engine units."""
    if not isinstance(raw_items, list):
        return []
    state = hass.states.get(entity_id)
    attrs = state.attributes if state else {}
    temp_unit = attrs.get("temperature_unit") or hass.config.units.temperature_unit
    wind_unit = attrs.get("wind_speed_unit")
    precipitation_unit = attrs.get("precipitation_unit") or hass.config.units.accumulated_precipitation_unit
    result: list[WeatherPoint] = []
    for raw in raw_items[:24]:
        if not isinstance(raw, dict):
            continue
        dt = _parse_dt(raw.get("datetime"))
        temp = _temperature_to_c(raw.get("temperature"), temp_unit)
        if dt is None or temp is None:
            continue
        result.append(
            WeatherPoint(
                dt=dt,
                temperature_c=temp,
                humidity=_bounded(raw.get("humidity"), 0.0, 100.0),
                wind_kmh=_wind_to_kmh(raw.get("wind_speed"), wind_unit),
                gust_kmh=_wind_to_kmh(raw.get("wind_gust_speed"), wind_unit),
                cloud_coverage=_bounded(raw.get("cloud_coverage"), 0.0, 100.0),
                precipitation_probability=_bounded(raw.get("precipitation_probability"), 0.0, 100.0),
                precipitation_mm=_precipitation_to_mm(raw.get("precipitation"), precipitation_unit),
                condition=raw.get("condition") if isinstance(raw.get("condition"), str) else None,
            )
        )
    result.sort(key=lambda item: item.dt)
    return result


async def _fetch_hourly(hass: HomeAssistant, entity_id: str) -> list[WeatherPoint]:
    """Use Home Assistant's public weather.get_forecasts action."""
    try:
        response = await hass.services.async_call(
            "weather",
            "get_forecasts",
            {"type": "hourly"},
            target={"entity_id": entity_id},
            blocking=True,
            return_response=True,
        )
    except (HomeAssistantError, ValueError) as err:
        _LOGGER.debug("Hourly forecast unavailable for %s: %s", entity_id, err)
        return []
    if not isinstance(response, dict):
        return []
    payload = response.get(entity_id)
    if not isinstance(payload, dict):
        return []
    return normalize_forecast(hass, entity_id, payload.get("forecast"))


class JackenWeatherCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Refresh only the hourly forecast; current states remain live."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"JackenBerater {entry.entry_id}",
            update_interval=FORECAST_REFRESH,
        )
        self.entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        home_entity = str(self.entry.data[CONF_WEATHER])
        home = await _fetch_hourly(self.hass, home_entity)
        if not home:
            # A forecast is valuable but not mandatory: current-only advice is
            # still useful. Only fail if even the current weather is unavailable.
            if current_weather(self.hass, home_entity) is None:
                raise UpdateFailed(f"Weather entity {home_entity} is unavailable")

        work_entity = self.entry.data.get(CONF_WORK_WEATHER)
        work: list[WeatherPoint] = []
        if isinstance(work_entity, str) and work_entity and work_entity != home_entity:
            work = await _fetch_hourly(self.hass, work_entity)
        elif work_entity == home_entity:
            work = list(home)

        return {
            "home_forecast": home,
            "work_forecast": work,
            "updated": dt_util.now(),
        }
