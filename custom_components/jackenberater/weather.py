"""Home Assistant weather normalization and lightweight forecast cache."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import math
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import DistanceConverter, TemperatureConverter
from homeassistant.const import UnitOfLength, UnitOfTemperature

from .const import FORECAST_FAILURE_RETRY, FORECAST_REFRESH
from .models import WeatherPoint
from .time_utils import instant_key

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ForecastFetchResult:
    """One hourly forecast fetch with transport/result success separated."""

    points: list[WeatherPoint]
    success: bool



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
        try:
            result = dt_util.parse_datetime(value)
        except (TypeError, ValueError):
            return None
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
        dew_point_c=_temperature_to_c(attrs.get("dew_point"), unit),
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
    for raw in raw_items:
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
                dew_point_c=_temperature_to_c(raw.get("dew_point"), temp_unit),
                wind_kmh=_wind_to_kmh(raw.get("wind_speed"), wind_unit),
                gust_kmh=_wind_to_kmh(raw.get("wind_gust_speed"), wind_unit),
                cloud_coverage=_bounded(raw.get("cloud_coverage"), 0.0, 100.0),
                precipitation_probability=_bounded(raw.get("precipitation_probability"), 0.0, 100.0),
                precipitation_mm=_precipitation_to_mm(raw.get("precipitation"), precipitation_unit),
                condition=raw.get("condition") if isinstance(raw.get("condition"), str) else None,
            )
        )
    result.sort(key=lambda item: instant_key(item.dt))

    # Providers occasionally emit the same real instant more than once (for
    # example after timezone/DST normalization or transient API duplication).
    # One instant must count only once for trend confirmation. If duplicates
    # disagree, prefer the point carrying more usable provider fields; on an
    # equal completeness score the later provider item wins, which also gives a
    # deterministic policy for corrected duplicate rows.
    def completeness(point: WeatherPoint) -> int:
        return sum(
            value is not None
            for value in (
                point.humidity,
                point.dew_point_c,
                point.wind_kmh,
                point.gust_kmh,
                point.cloud_coverage,
                point.precipitation_probability,
                point.precipitation_mm,
                point.condition,
            )
        )

    by_instant: dict[datetime, WeatherPoint] = {}
    scores: dict[datetime, int] = {}
    for point in result:
        key = instant_key(point.dt)
        score = completeness(point)
        if key not in by_instant or score >= scores[key]:
            by_instant[key] = point
            scores[key] = score
    return [by_instant[key] for key in sorted(by_instant)][:24]


async def _fetch_hourly(hass: HomeAssistant, entity_id: str) -> ForecastFetchResult:
    """Use Home Assistant's public weather.get_forecasts action.

    An empty successful forecast is different from a transport/provider failure.
    Callers use this distinction to retry failures quickly without pretending a
    failed request produced a fresh empty forecast.
    """
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
        return ForecastFetchResult([], False)
    if not isinstance(response, dict):
        return ForecastFetchResult([], False)
    payload = response.get(entity_id)
    if not isinstance(payload, dict):
        return ForecastFetchResult([], False)
    raw_forecast = payload.get("forecast")
    if not isinstance(raw_forecast, list):
        return ForecastFetchResult([], False)
    normalized = normalize_forecast(hass, entity_id, raw_forecast)
    # A provider is allowed to return an actually empty forecast. A non-empty
    # payload whose every row is invalid, however, is a malformed/failed fetch
    # from JackenBerater's point of view and should use the short retry path.
    if raw_forecast and not normalized:
        return ForecastFetchResult([], False)
    return ForecastFetchResult(normalized, True)


class JackenWeatherCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Refresh only the hourly forecast; current states remain live."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"JackenBerater {entry.entry_id}",
            update_interval=FORECAST_REFRESH,
        )
        self.entry = entry
        self._profile_forecasts: dict[str, tuple[datetime, ForecastFetchResult]] = {}

    async def async_forecast_for(self, entity_id: str) -> ForecastFetchResult:
        """Return the server-cached hourly forecast for one profile entity.

        v0.5.0 deliberately has no integration-wide Home/Work weather owner.
        Every personal profile names the entities it needs and all UIs consume
        the same entity-keyed cache through the server-side advice path.
        """
        entity_id = str(entity_id or "").strip()
        if not entity_id.startswith("weather."):
            return ForecastFetchResult([], False)

        cached = self._profile_forecasts.get(entity_id)
        now = dt_util.now()
        if cached is not None:
            cached_at, result = cached
            ttl = FORECAST_REFRESH if result.success else FORECAST_FAILURE_RETRY
            if timedelta(0) <= now - cached_at < ttl:
                return ForecastFetchResult(list(result.points), result.success)

        result = await _fetch_hourly(self.hass, entity_id)
        self._profile_forecasts[entity_id] = (now, result)
        return ForecastFetchResult(list(result.points), result.success)

    async def _async_update_data(self) -> dict[str, Any]:
        """Maintain coordinator health without polling any personal weather.

        Forecast network calls are demand-driven by ``async_forecast_for``.
        The coordinator refresh clock only prunes expired cache entries so a
        stale legacy ConfigEntry can never cause hidden duplicate Home/Work
        requests after profiles have become the source of truth.
        """
        now = dt_util.now()
        self._profile_forecasts = {
            entity_id: cached
            for entity_id, cached in self._profile_forecasts.items()
            if timedelta(0) <= now - cached[0]
            < (FORECAST_REFRESH if cached[1].success else FORECAST_FAILURE_RETRY)
        }
        return {
            "forecast_fetch_failed": False,
            "updated": now,
        }
