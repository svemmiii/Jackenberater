from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).parents[1] / "custom_components" / "jackenberater"
PKG = "jackenberater_config_flow_testpkg"

package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PKG, package)

# The production integration runs inside Home Assistant where voluptuous is
# available. These tests target pure config-flow helpers only.
vol = types.ModuleType("voluptuous")
vol.Schema = lambda value: value
vol.Required = lambda key, **kwargs: key
vol.Optional = lambda key, **kwargs: key
sys.modules.setdefault("voluptuous", vol)

ha = types.ModuleType("homeassistant")
ha.__path__ = []
sys.modules.setdefault("homeassistant", ha)

config_entries = types.ModuleType("homeassistant.config_entries")
class DummyConfigFlow:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()
config_entries.ConfigFlow = DummyConfigFlow
sys.modules[config_entries.__name__] = config_entries
ha.config_entries = config_entries

components = types.ModuleType("homeassistant.components")
components.__path__ = []
sys.modules[components.__name__] = components
sensor = types.ModuleType("homeassistant.components.sensor")
sensor.SensorDeviceClass = type("SensorDeviceClass", (), {"TEMPERATURE": "temperature"})
sys.modules[sensor.__name__] = sensor

core = types.ModuleType("homeassistant.core")
core.callback = lambda func: func
sys.modules[core.__name__] = core

data_entry_flow = types.ModuleType("homeassistant.data_entry_flow")
class SectionConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
def section(schema, config):
    return (schema, config)
data_entry_flow.SectionConfig = SectionConfig
data_entry_flow.section = section
sys.modules[data_entry_flow.__name__] = data_entry_flow

helpers = types.ModuleType("homeassistant.helpers")
helpers.__path__ = []
sys.modules[helpers.__name__] = helpers
selectors = types.ModuleType("homeassistant.helpers.selector")
class DummySelector:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
class DummyConfig(DummySelector):
    pass
for name in (
    "BooleanSelector", "EntitySelector", "NumberSelector", "TextSelector",
    "SelectSelector",
):
    setattr(selectors, name, type(name, (DummySelector,), {}))
for name in (
    "EntitySelectorConfig", "NumberSelectorConfig", "TextSelectorConfig",
    "SelectSelectorConfig",
):
    setattr(selectors, name, type(name, (DummyConfig,), {}))
selectors.NumberSelectorMode = type("NumberSelectorMode", (), {"BOX": "box"})
selectors.SelectSelectorMode = type("SelectSelectorMode", (), {"DROPDOWN": "dropdown"})
selectors.SelectOptionDict = dict
selectors.selector = lambda value: value
sys.modules[selectors.__name__] = selectors


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


const = load("const")
config_flow = load("config_flow")


def test_default_work_settings_are_five_day_week():
    defaults = config_flow._section_defaults({const.CONF_WEATHER: "weather.home"})
    work = defaults[const.SECTION_WORK]
    assert work[const.CONF_WORK_MODE] == const.WORK_MODE_WEEKDAY
    assert work[const.CONF_WORKDAY_START] == "08:00"
    assert work[const.CONF_WORKDAY_END] == "17:00"


def test_shift_mode_requires_valid_pattern_and_anchor():
    errors = config_flow._validate({
        const.CONF_WORK_MODE: const.WORK_MODE_SHIFT,
        const.CONF_SHIFT_PATTERN: "F,S,Q",
        const.CONF_SHIFT_ANCHOR_DATE: "2026-09-01",
        const.CONF_WORK_WEATHER: "weather.work",
    })
    assert errors["base"] == "invalid_shift_pattern"

    errors = config_flow._validate({
        const.CONF_WORK_MODE: const.WORK_MODE_SHIFT,
        const.CONF_SHIFT_PATTERN: "F,F,S,S,N,N,N,X,X",
        const.CONF_WORK_WEATHER: "weather.work",
    })
    assert errors["base"] == "shift_anchor_required"


def test_work_context_requires_work_weather_when_enabled():
    errors = config_flow._validate({
        const.CONF_WORK_MODE: const.WORK_MODE_WEEKDAY,
        const.CONF_WORK_ZONE: "zone.work",
    })
    assert errors["base"] == "work_weather_required"

    assert config_flow._validate({
        const.CONF_WORK_MODE: const.WORK_MODE_NONE,
        const.CONF_WORK_ZONE: "zone.work",
    }) == {}


def test_flatten_keeps_selected_sections_and_omits_empty_values():
    result = config_flow._flatten({
        const.SECTION_BASIC: {
            const.CONF_WEATHER: "weather.home",
            const.CONF_INDOOR_TEMP: "",
        },
        const.SECTION_WORK: {
            const.CONF_WORK_MODE: const.WORK_MODE_WEEKDAY,
            const.CONF_WORK_WEATHER: "weather.work",
        },
    })
    assert result[const.CONF_WEATHER] == "weather.home"
    assert result[const.CONF_WORK_MODE] == const.WORK_MODE_WEEKDAY
    assert result[const.CONF_WORK_WEATHER] == "weather.work"
    assert const.CONF_INDOOR_TEMP not in result


def test_work_mode_labels_are_localized():
    de = config_flow._work_mode_options("de-DE")
    en = config_flow._work_mode_options("en-GB")
    assert de[1]["label"] == "Normale 5-Tage-Woche"
    assert en[1]["label"] == "Normal 5-day work week"


def test_equal_weekday_start_and_end_is_rejected():
    errors = config_flow._validate({
        const.CONF_WORK_MODE: const.WORK_MODE_WEEKDAY,
        const.CONF_WORKDAY_START: "08:00",
        const.CONF_WORKDAY_END: "08:00:00",
        const.CONF_WORK_WEATHER: "weather.work",
    })
    assert errors["base"] == "invalid_work_time"


def test_equal_shift_start_and_end_is_rejected():
    errors = config_flow._validate({
        const.CONF_WORK_MODE: const.WORK_MODE_SHIFT,
        const.CONF_SHIFT_PATTERN: "F,S,N,X",
        const.CONF_SHIFT_ANCHOR_DATE: "2026-09-01",
        const.CONF_SHIFT_EARLY_START: "06:00",
        const.CONF_SHIFT_EARLY_END: "06:00",
        const.CONF_SHIFT_LATE_START: "14:00",
        const.CONF_SHIFT_LATE_END: "22:00",
        const.CONF_SHIFT_NIGHT_START: "22:00",
        const.CONF_SHIFT_NIGHT_END: "06:00",
        const.CONF_WORK_WEATHER: "weather.work",
    })
    assert errors["base"] == "invalid_shift_time"


def test_reconfigure_uses_non_reloading_update_helper():
    import asyncio

    class Auth:
        async def async_get_users(self):
            return []

    flow = config_flow.JackenBeraterConfigFlow()
    flow.hass = types.SimpleNamespace(
        auth=Auth(),
        config=types.SimpleNamespace(language="de"),
    )
    entry = types.SimpleNamespace(entry_id="entry", data={})
    flow._get_reconfigure_entry = lambda: entry
    calls = []

    def update_and_abort(target, **kwargs):
        calls.append((target, kwargs))
        return {"type": "abort", "reason": "reconfigure_successful"}

    flow.async_update_and_abort = update_and_abort
    result = asyncio.run(flow.async_step_reconfigure({
        const.SECTION_BASIC: {const.CONF_WEATHER: "weather.home"},
        const.SECTION_WORK: {const.CONF_WORK_MODE: const.WORK_MODE_NONE},
    }))
    assert result["type"] == "abort"
    assert len(calls) == 1
    assert calls[0][0] is entry
    assert calls[0][1]["data"][const.CONF_WEATHER] == "weather.home"
    assert "data_updates" not in calls[0][1]


def test_reconfigure_full_replacement_removes_cleared_optional_fields():
    import asyncio

    class Auth:
        async def async_get_users(self):
            return []

    flow = config_flow.JackenBeraterConfigFlow()
    flow.hass = types.SimpleNamespace(
        auth=Auth(),
        config=types.SimpleNamespace(language="de"),
    )
    entry = types.SimpleNamespace(entry_id="entry", data={
        const.CONF_WEATHER: "weather.home",
        const.CONF_INDOOR_TEMP: "sensor.living",
        const.CONF_CONTEXT_CALENDAR: "calendar.context",
        const.CONF_WORK_MODE: const.WORK_MODE_WEEKDAY,
        const.CONF_WORK_WEATHER: "weather.work",
        const.CONF_WORK_ZONE: "zone.work",
        const.CONF_VACATION_CALENDAR: "calendar.vacation",
    })
    flow._get_reconfigure_entry = lambda: entry
    calls = []

    def update_and_abort(target, **kwargs):
        calls.append((target, kwargs))
        return {"type": "abort", "reason": "reconfigure_successful"}

    flow.async_update_and_abort = update_and_abort
    result = asyncio.run(flow.async_step_reconfigure({
        const.SECTION_BASIC: {
            const.CONF_WEATHER: "weather.home",
            const.CONF_INDOOR_TEMP: "",
        },
        const.SECTION_CONTEXT: {const.CONF_CONTEXT_CALENDAR: ""},
        const.SECTION_WORK: {
            const.CONF_WORK_MODE: const.WORK_MODE_NONE,
            const.CONF_WORK_WEATHER: "",
            const.CONF_WORK_ZONE: "",
            const.CONF_VACATION_CALENDAR: "",
        },
    }))
    assert result["type"] == "abort"
    replacement = calls[0][1]["data"]
    assert replacement[const.CONF_WEATHER] == "weather.home"
    assert const.CONF_INDOOR_TEMP not in replacement
    assert const.CONF_CONTEXT_CALENDAR not in replacement
    assert const.CONF_WORK_WEATHER not in replacement
    assert const.CONF_WORK_ZONE not in replacement
    assert const.CONF_VACATION_CALENDAR not in replacement
