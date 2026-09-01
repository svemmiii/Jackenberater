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
    CONF_WORK_CALENDAR,
    CONF_WORK_WEATHER,
    CONF_WORK_ZONE,
    DEFAULT_FALLBACK_INDOOR_TEMP,
    DOMAIN,
    SECTION_BASIC,
    SECTION_CONTEXT,
    SECTION_SHIFT,
    SECTION_SHARED,
    SECTION_WORK,
)


def _entity(domain: str, *, device_class: str | None = None) -> EntitySelector:
    config: dict[str, Any] = {"domain": domain}
    if device_class:
        config["device_class"] = device_class
    return EntitySelector(EntitySelectorConfig(**config))


def _schema(shared_options: list[SelectOptionDict] | None = None) -> vol.Schema:
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
                        vol.Optional(CONF_WORK_CALENDAR): _entity("calendar"),
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
        key: data[key]
        for key in (
            CONF_WORK_ZONE,
            CONF_WORK_WEATHER,
            CONF_WORK_CALENDAR,
            CONF_VACATION_CALENDAR,
        )
        if data.get(key)
    }
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


def _validate(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    pattern = data.get(CONF_SHIFT_PATTERN)
    anchor = data.get(CONF_SHIFT_ANCHOR_DATE)
    if pattern:
        tokens = [x.strip().upper() for x in str(pattern).split(",") if x.strip()]
        if not tokens or any(x not in {"F", "S", "N", "X"} for x in tokens):
            errors["base"] = "invalid_shift_pattern"
        elif not anchor:
            errors["base"] = "shift_anchor_required"

    work_weather = data.get(CONF_WORK_WEATHER)
    work_context_present = any(
        data.get(key)
        for key in (
            CONF_WORK_ZONE,
            CONF_WORK_CALENDAR,
            CONF_VACATION_CALENDAR,
            CONF_SHIFT_PATTERN,
        )
    )
    if work_context_present and not work_weather:
        errors.setdefault("base", "work_weather_required")
    elif work_weather and not (data.get(CONF_WORK_CALENDAR) or data.get(CONF_SHIFT_PATTERN)):
        # Without any time source the additional weather entity can never become
        # contextually relevant in v0.1.0. Reject silent no-op configuration.
        errors.setdefault("base", "work_time_required")
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
    MINOR_VERSION = 0

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
                data_schema=self.add_suggested_values_to_schema(_schema(shared_options), user_input),
                errors=errors,
            )
        return self.async_show_form(step_id="user", data_schema=_schema(shared_options))

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        entry = self._get_reconfigure_entry()
        shared_options = await _shared_user_options(self.hass)
        if user_input is not None:
            data = _flatten(user_input)
            errors = _validate(data)
            if not errors:
                self.hass.config_entries.async_update_entry(entry, data=data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=self.add_suggested_values_to_schema(_schema(shared_options), user_input),
                errors=errors,
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _schema(shared_options), _section_defaults(dict(entry.data))
            ),
        )
