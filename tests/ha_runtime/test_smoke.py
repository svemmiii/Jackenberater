"""Real Home Assistant runtime smoke test for the integration lifecycle."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.jackenberater.const import (
    CONF_FALLBACK_INDOOR_TEMP,
    CONF_RAIN_ADVICE,
    CONF_SHARED_USER_IDS,
    CONF_WEATHER,
    DOMAIN,
)


async def _coordinator_first_refresh(coordinator) -> None:
    coordinator.data = {
        "home_forecast": [],
        "work_forecast": [],
    }


async def test_setup_preview_session_feedback_reload_and_unload(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: MockUser,
    hass_read_only_user: MockUser,
    hass_read_only_access_token: str,
    enable_custom_integrations: None,
) -> None:
    """Exercise real HA setup, sensor forwarding and authenticated WebSockets."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="JackenBerater",
        data={
            CONF_WEATHER: "weather.home",
            CONF_FALLBACK_INDOOR_TEMP: 21.5,
            CONF_RAIN_ADVICE: True,
            CONF_SHARED_USER_IDS: [hass_read_only_user.id],
        },
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    hass.states.async_set(
        "weather.home",
        "cloudy",
        {
            "temperature": 15.0,
            "temperature_unit": "°C",
            "wind_speed": 5.0,
            "wind_speed_unit": "km/h",
        },
    )

    with (
        patch(
            "custom_components.jackenberater._async_register_frontend",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.jackenberater.JackenWeatherCoordinator.async_config_entry_first_refresh",
            new=_coordinator_first_refresh,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED

        manager = hass.data[DOMAIN][entry.entry_id]["profiles"]
        await manager.async_ensure_profile(hass_admin_user.id, "Admin")
        await manager.async_setup_profile(
            hass_admin_user.id, cold=3, warm=3, wind=3, evening=3
        )
        await hass.async_block_till_done()

        admin_client = await hass_ws_client(hass)
        await admin_client.send_json_auto_id(
            {
                "type": "jackenberater/preview",
                "entry_id": entry.entry_id,
                "profile_id": hass_admin_user.id,
            }
        )
        preview = await admin_client.receive_json()
        assert preview["success"]
        assert preview["result"]["recommendation"]["simulation_active"] is False
        assert "diagnostics" in preview["result"]

        await admin_client.send_json_auto_id(
            {
                "type": "jackenberater/open_session",
                "entry_id": entry.entry_id,
                "profile_id": hass_admin_user.id,
            }
        )
        opened = await admin_client.receive_json()
        assert opened["success"]
        session_id = opened["result"]["session"]["id"]

        await admin_client.send_json_auto_id(
            {
                "type": "jackenberater/feedback",
                "entry_id": entry.entry_id,
                "profile_id": hass_admin_user.id,
                "session_id": session_id,
                "rating": "perfect",
                "voluntary": True,
            }
        )
        feedback = await admin_client.receive_json()
        assert feedback["success"]

        shared_client = await hass_ws_client(hass, hass_read_only_access_token)
        await shared_client.send_json_auto_id(
            {
                "type": "jackenberater/preview",
                "entry_id": entry.entry_id,
                "profile_id": hass_admin_user.id,
            }
        )
        shared_preview = await shared_client.receive_json()
        assert shared_preview["success"]
        assert "diagnostics" not in shared_preview["result"]

        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED
