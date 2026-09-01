"""UI configuration for JackenBerater."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import callback
from homeassistant.data_entry_flow import SectionConfig, section
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    selector,
)

from .const import (
    CONF_CONTEXT_CALENDAR,
    CONF_FALLBACK_INDOOR_TEMP,
    CONF_INDOOR_TEMP,
    CONF_RAIN_ADVICE,
    CONF_SHIFT_ANCHOR_DATE,
    CONF_SHIFT_EARLY_END,
    CONF_SHIFT_EARLY_START,
    CONF_SHIFT_LATE_END,
    CONF_SHIFT_LATE_START,
    CONF_SHIFT_NIGHT_END,
    CONF_SHIFT_NIGHT_START,
    CONF_SHIFT_PATTERN,
    CONF_SHARED_USER_IDS,
    CONF_VACATION_CALENDAR,
    CONF_WEATHER,
    CONF_WORK_MODE,
    CONF_WORK_WEATHER,
    CONF_WORK_ZONE,
    CONF_WORKDAY_END,
    CONF_WORKDAY_START,
    DEFAULT_FALLBACK_INDOOR_TEMP,
    DEFAULT_WORKDAY_END,
    DEFAULT_WORKDAY_START,
    DOMAIN,
    SECTION_BASIC,
    SECTION_CONTEXT,
    SECTION_SHIFT,
    SECTION_SHARED,
    SECTION_WORK,
    WORK_MODE_NONE,
    WORK_MODE_SHIFT,
    WORK_MODE_WEEKDAY,
)


def _entity(domain: str, *, device_class: str | None = None) -> EntitySelector:
    config: dict[str, Any] = {"domain": domain}
    if device_class:
        config["device_class"] = device_class
    return EntitySelector(EntitySelectorConfig(**config))


def _work_mode_options(language: str | None) -> list[SelectOptionDict]:
    german = str(language or "de").lower().startswith("de")
    if german:
        return [
            {"value": WORK_MODE_NONE, "label": "Arbeit nicht berücksichtigen"},
            {"value": WORK_MODE_WEEKDAY, "label": "Normale 5-Tage-Woche"},
            {"value": WORK_MODE_SHIFT, "label": "Rotierendes Schichtsystem"},
        ]
    return [
        {"value": WORK_MODE_NONE, "label": "Do not consider work"},
        {"value": WORK_MODE_WEEKDAY, "label": "Normal 5-day work week"},
        {"value": WORK_MODE_SHIFT, "label": "Rotating shift system"},
    ]


def _schema(
    shared_options: list[SelectOptionDict] | None = None,
    language: str | None = None,
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(SECTION_BASIC): section(
                vol.Schema(
                    {
                        vol.Required(CONF_WEATHER): _entity("weather"),
                        vol.Optional(CONF_INDOOR_TEMP): _entity(
                            "sensor", device_class=SensorDeviceClass.TEMPERATURE
                        ),
                        vol.Optional(
                            CONF_FALLBACK_INDOOR_TEMP,
                            default=DEFAULT_FALLBACK_INDOOR_TEMP,
                        ): NumberSelector(
                            NumberSelectorConfig(
                                min=15.0,
                                max=28.0,
                                step=0.5,
                                mode=NumberSelectorMode.BOX,
                                unit_of_measurement="°C",
                            )
                        ),
                        vol.Optional(CONF_RAIN_ADVICE, default=True): BooleanSelector(),
                    }
                ),
                SectionConfig(collapsed=False),
            ),
            vol.Optional(SECTION_CONTEXT): section(
                vol.Schema(
                    {
                        vol.Optional(CONF_CONTEXT_CALENDAR): _entity("calendar"),
                    }
                ),
                SectionConfig(collapsed=True),
            ),
            vol.Optional(SECTION_WORK): section(
                vol.Schema(
                    {
                        vol.Optional(CONF_WORK_ZONE): _entity("zone"),
                        vol.Optional(CONF_WORK_WEATHER): _entity("weather"),
                        vol.Optional(CONF_WORK_MODE, default=WORK_MODE_WEEKDAY): SelectSelector(
                            SelectSelectorConfig(
                                options=_work_mode_options(language),
                                multiple=False,
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        vol.Optional(CONF_WORKDAY_START, default=DEFAULT_WORKDAY_START): selector({"time": {}}),
                        vol.Optional(CONF_WORKDAY_END, default=DEFAULT_WORKDAY_END): selector({"time": {}}),
                        vol.Optional(CONF_VACATION_CALENDAR): _entity("calendar"),
                    }
                ),
                SectionConfig(collapsed=True),
            ),
            vol.Optional(SECTION_SHARED): section(
                vol.Schema(
                    {
                        vol.Optional(CONF_SHARED_USER_IDS, default=[]): SelectSelector(
                            SelectSelectorConfig(
                                options=shared_options or [],
                                multiple=True,
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    }
                ),
                SectionConfig(collapsed=True),
            ),
            vol.Optional(SECTION_SHIFT): section(
                vol.Schema(
                    {
                        vol.Optional(CONF_SHIFT_PATTERN): TextSelector(
                            TextSelectorConfig(autocomplete="off")
                        ),
                        vol.Optional(CONF_SHIFT_ANCHOR_DATE): selector({"date": {}}),
                        vol.Optional(CONF_SHIFT_EARLY_START, default="06:00"): selector({"time": {}}),
                        vol.Optional(CONF_SHIFT_EARLY_END, default="14:00"): selector({"time": {}}),
                        vol.Optional(CONF_SHIFT_LATE_START, default="14:00"): selector({"time": {}}),
                        vol.Optional(CONF_SHIFT_LATE_END, default="22:00"): selector({"time": {}}),
                        vol.Optional(CONF_SHIFT_NIGHT_START, default="22:00"): selector({"time": {}}),
                        vol.Optional(CONF_SHIFT_NIGHT_END, default="06:00"): selector({"time": {}}),
                    }
                ),
                SectionConfig(collapsed=True),
            ),
        }
    )


def _flatten(user_input: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for section_name in (SECTION_BASIC, SECTION_CONTEXT, SECTION_WORK, SECTION_SHARED, SECTION_SHIFT):
        values = user_input.get(section_name)
        if isinstance(values, dict):
            for key, value in values.items():
                if value not in (None, ""):
                    result[key] = value
    return result


def _section_defaults(data: dict[str, Any]) -> dict[str, Any]:
    basic = {
        CONF_WEATHER: data.get(CONF_WEATHER),
        CONF_FALLBACK_INDOOR_TEMP: data.get(
            CONF_FALLBACK_INDOOR_TEMP, DEFAULT_FALLBACK_INDOOR_TEMP
        ),
        CONF_RAIN_ADVICE: data.get(CONF_RAIN_ADVICE, True),
    }
    if data.get(CONF_INDOOR_TEMP):
        basic[CONF_INDOOR_TEMP] = data[CONF_INDOOR_TEMP]

    context = {}
    if data.get(CONF_CONTEXT_CALENDAR):
        context[CONF_CONTEXT_CALENDAR] = data[CONF_CONTEXT_CALENDAR]

    work = {
        CONF_WORK_MODE: data.get(CONF_WORK_MODE, WORK_MODE_WEEKDAY),
        CONF_WORKDAY_START: data.get(CONF_WORKDAY_START, DEFAULT_WORKDAY_START),
        CONF_WORKDAY_END: data.get(CONF_WORKDAY_END, DEFAULT_WORKDAY_END),
    }
    for key in (CONF_WORK_ZONE, CONF_WORK_WEATHER, CONF_VACATION_CALENDAR):
        if data.get(key):
            work[key] = data[key]
    shared = {}
    if data.get(CONF_SHARED_USER_IDS):
        shared[CONF_SHARED_USER_IDS] = list(data[CONF_SHARED_USER_IDS])

    shift = {
        key: data[key]
        for key in (
            CONF_SHIFT_PATTERN,
            CONF_SHIFT_ANCHOR_DATE,
            CONF_SHIFT_EARLY_START,
            CONF_SHIFT_EARLY_END,
            CONF_SHIFT_LATE_START,
            CONF_SHIFT_LATE_END,
            CONF_SHIFT_NIGHT_START,
            CONF_SHIFT_NIGHT_END,
        )
        if data.get(key)
    }
    result: dict[str, Any] = {SECTION_BASIC: basic}
    if context:
        result[SECTION_CONTEXT] = context
    if work:
        result[SECTION_WORK] = work
    if shared:
        result[SECTION_SHARED] = shared
    if shift:
        result[SECTION_SHIFT] = shift
    return result


def _time_key(value: Any) -> tuple[int, int] | None:
    """Normalize Home Assistant time-selector values for validation."""
    if value in (None, ""):
        return None
    try:
        parts = str(value).split(":")
        return int(parts[0]), int(parts[1])
    except (TypeError, ValueError, IndexError):
        return None


def _same_time(start: Any, end: Any) -> bool:
    a = _time_key(start)
    b = _time_key(end)
    return a is not None and b is not None and a == b


def _validate(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    mode = str(data.get(CONF_WORK_MODE, WORK_MODE_WEEKDAY))
    pattern = data.get(CONF_SHIFT_PATTERN)
    anchor = data.get(CONF_SHIFT_ANCHOR_DATE)

    if mode == WORK_MODE_SHIFT:
        tokens = [x.strip().upper() for x in str(pattern or "").split(",") if x.strip()]
        if not tokens or any(x not in {"F", "S", "N", "X"} for x in tokens):
            errors["base"] = "invalid_shift_pattern"
        elif not anchor:
            errors["base"] = "shift_anchor_required"
        elif any(
            _same_time(data.get(start_key), data.get(end_key))
            for start_key, end_key in (
                (CONF_SHIFT_EARLY_START, CONF_SHIFT_EARLY_END),
                (CONF_SHIFT_LATE_START, CONF_SHIFT_LATE_END),
                (CONF_SHIFT_NIGHT_START, CONF_SHIFT_NIGHT_END),
            )
        ):
            errors["base"] = "invalid_shift_time"
    elif mode == WORK_MODE_WEEKDAY and _same_time(
        data.get(CONF_WORKDAY_START, DEFAULT_WORKDAY_START),
        data.get(CONF_WORKDAY_END, DEFAULT_WORKDAY_END),
    ):
        errors["base"] = "invalid_work_time"

    work_weather = data.get(CONF_WORK_WEATHER)
    work_context_present = any(
        data.get(key)
        for key in (CONF_WORK_ZONE, CONF_VACATION_CALENDAR, CONF_SHIFT_PATTERN)
    )
    if work_context_present and mode != WORK_MODE_NONE and not work_weather:
        errors.setdefault("base", "work_weather_required")
    return errors


async def _shared_user_options(hass) -> list[SelectOptionDict]:
    users = await hass.auth.async_get_users()
    return [
        {"value": str(user.id), "label": str(user.name or user.id)}
        for user in users
        if user.is_active and not user.system_generated
    ]


class JackenBeraterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the single local JackenBerater instance."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        await self.async_set_unique_id("main")
        shared_options = await _shared_user_options(self.hass)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            data = _flatten(user_input)
            errors = _validate(data)
            if not errors:
                return self.async_create_entry(title="JackenBerater", data=data)
            return self.async_show_form(
                step_id="user",
                data_schema=self.add_suggested_values_to_schema(_schema(shared_options, self.hass.config.language), user_input),
                errors=errors,
            )
        return self.async_show_form(step_id="user", data_schema=_schema(shared_options, self.hass.config.language))

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        entry = self._get_reconfigure_entry()
        shared_options = await _shared_user_options(self.hass)
        if user_input is not None:
            data = _flatten(user_input)
            errors = _validate(data)
            if not errors:
                # The update listener registered by the integration performs the
                # reload. Home Assistant 2026.6+ explicitly recommends the
                # non-reloading helper in this setup to avoid double reloads.
                return self.async_update_and_abort(entry, data=data)
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=self.add_suggested_values_to_schema(_schema(shared_options, self.hass.config.language), user_input),
                errors=errors,
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _schema(shared_options, self.hass.config.language), _section_defaults(dict(entry.data))
            ),
        )
