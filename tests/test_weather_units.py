from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).parents[1] / "custom_components" / "jackenberater"
PKG = "jackenberater_weather_testpkg"

package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PKG, package)

# Minimal Home Assistant import stubs: these tests target the pure normalization
# helpers without pretending to run a Home Assistant instance.
ha = types.ModuleType("homeassistant")
sys.modules.setdefault("homeassistant", ha)

config_entries = types.ModuleType("homeassistant.config_entries")
config_entries.ConfigEntry = type("ConfigEntry", (), {})
sys.modules[config_entries.__name__] = config_entries

core = types.ModuleType("homeassistant.core")
core.HomeAssistant = type("HomeAssistant", (), {})
sys.modules[core.__name__] = core

exceptions = types.ModuleType("homeassistant.exceptions")
exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
sys.modules[exceptions.__name__] = exceptions

helpers = types.ModuleType("homeassistant.helpers")
sys.modules[helpers.__name__] = helpers
coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

class DummyCoordinator:
    def __init__(self, hass, *args, **kwargs):
        self.hass = hass
        self.config_entry = kwargs.get("config_entry")

    @classmethod
    def __class_getitem__(cls, item):
        return cls

coordinator.DataUpdateCoordinator = DummyCoordinator
coordinator.UpdateFailed = type("UpdateFailed", (Exception,), {})
sys.modules[coordinator.__name__] = coordinator

util = types.ModuleType("homeassistant.util")
sys.modules[util.__name__] = util
ha_dt = types.ModuleType("homeassistant.util.dt")
ha_dt.UTC = timezone.utc
ha_dt.parse_datetime = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
ha_dt.as_local = lambda value: value
ha_dt.now = lambda: datetime.now(timezone.utc)
sys.modules[ha_dt.__name__] = ha_dt
util.dt = ha_dt

units = types.ModuleType("homeassistant.util.unit_conversion")
class DummyDistanceConverter:
    @staticmethod
    def convert(value, from_unit, to_unit):
        if from_unit == "in" and to_unit == "mm":
            return value * 25.4
        if from_unit == to_unit:
            return value
        raise ValueError
class DummyTemperatureConverter:
    @staticmethod
    def convert(value, from_unit, to_unit):
        if from_unit == "°F" and to_unit == "°C":
            return (value - 32) * 5 / 9
        if from_unit == to_unit:
            return value
        raise ValueError
units.DistanceConverter = DummyDistanceConverter
units.TemperatureConverter = DummyTemperatureConverter
sys.modules[units.__name__] = units

ha_const = types.ModuleType("homeassistant.const")
ha_const.UnitOfLength = type("UnitOfLength", (), {"MILLIMETERS": "mm"})
ha_const.UnitOfTemperature = type("UnitOfTemperature", (), {"CELSIUS": "°C"})
sys.modules[ha_const.__name__] = ha_const


def load(name: str):
    fullname = f"{PKG}.{name}"
    if fullname in sys.modules:
        return sys.modules[fullname]
    spec = importlib.util.spec_from_file_location(fullname, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# Relative imports used by weather.py.
for dep in ("const", "models"):
    load(dep)
weather = load("weather")


def test_wind_units_include_ft_s_and_beaufort():
    assert abs(weather._wind_to_kmh(10, "ft/s") - 10.9728) < 1e-6
    assert 33 < weather._wind_to_kmh(5, "Beaufort") < 34


def test_unknown_wind_unit_is_rejected_not_assumed_kmh():
    assert weather._wind_to_kmh(68, "mystery") is None


def test_precipitation_inches_convert_to_mm():
    assert abs(weather._precipitation_to_mm(1, "in") - 25.4) < 1e-9


def test_unknown_temperature_unit_is_rejected():
    assert weather._temperature_to_c(68, "mystery") is None


def test_non_finite_and_implausible_weather_values_are_rejected():
    for value in (float("inf"), float("-inf"), float("nan")):
        assert weather._float(value) is None
        assert weather._temperature_to_c(value, "°C") is None
        assert weather._wind_to_kmh(value, "km/h") is None
        assert weather._precipitation_to_mm(value, "mm") is None
    assert weather._temperature_to_c(71, "°C") is None
    assert weather._temperature_to_c(-101, "°C") is None
    assert weather._bounded(101, 0, 100) is None
    assert weather._bounded(-1, 0, 100) is None
    assert weather._wind_to_kmh(-1, "km/h") is None
    assert weather._wind_to_kmh(13, "Beaufort") is None
    assert weather._precipitation_to_mm(-1, "mm") is None


def test_normalize_forecast_sorts_before_24_point_limit():
    entity_id = "weather.test"
    state = types.SimpleNamespace(attributes={
        "temperature_unit": "°C",
        "wind_speed_unit": "km/h",
        "precipitation_unit": "mm",
    })
    hass = types.SimpleNamespace(
        states=types.SimpleNamespace(get=lambda requested: state if requested == entity_id else None),
        config=types.SimpleNamespace(
            units=types.SimpleNamespace(
                temperature_unit="°C", accumulated_precipitation_unit="mm"
            )
        ),
    )
    raw = [
        {"datetime": f"2026-09-06T{hour:02d}:00:00+00:00", "temperature": hour}
        for hour in range(23, -1, -1)
    ]
    raw.extend([
        {"datetime": "2026-09-07T00:00:00+00:00", "temperature": 24},
        {"datetime": "2026-09-07T01:00:00+00:00", "temperature": 25},
    ])
    normalized = weather.normalize_forecast(hass, entity_id, raw)
    assert len(normalized) == 24
    assert normalized[0].dt.isoformat() == "2026-09-06T00:00:00+00:00"
    assert normalized[-1].dt.isoformat() == "2026-09-06T23:00:00+00:00"


def test_coordinator_skips_work_forecast_when_work_mode_is_disabled():
    import asyncio

    calls = []
    original_fetch = weather._fetch_hourly
    original_current = weather.current_weather

    async def fetch(_hass, entity_id):
        calls.append(entity_id)
        return [types.SimpleNamespace(dt=datetime.now(timezone.utc))]

    weather._fetch_hourly = fetch
    weather.current_weather = lambda *_args, **_kwargs: None
    entry = types.SimpleNamespace(
        entry_id="entry",
        data={
            weather.CONF_WEATHER: "weather.home",
            weather.CONF_WORK_WEATHER: "weather.work",
            weather.CONF_WORK_MODE: weather.WORK_MODE_NONE,
        },
    )
    coordinator = weather.JackenWeatherCoordinator(types.SimpleNamespace(), entry)
    try:
        result = asyncio.run(coordinator._async_update_data())
    finally:
        weather._fetch_hourly = original_fetch
        weather.current_weather = original_current
    assert coordinator.config_entry is entry
    assert calls == ["weather.home"]
    assert result["work_forecast"] == []

