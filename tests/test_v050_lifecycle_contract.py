from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "jackenberater"


def test_preview_exposes_recoverable_profile_shell_and_profile_watch_list():
    source = (INTEGRATION / "api.py").read_text(encoding="utf-8")
    preview = source[source.index("async def ws_preview"):source.index("async def ws_open_session")]
    assert '"recommendation": None' in preview
    assert '"advice_error": None' in preview
    assert '"weather_unavailable", "work_weather_unavailable"' in preview
    assert '"watched_entities": _profile_watched_entities(entry, manager, profile_id)' in preview


def test_websocket_open_session_has_no_recent_session_shortcut():
    source = (INTEGRATION / "api.py").read_text(encoding="utf-8")
    block = source[source.index("async def ws_open_session"):source.index("async def ws_profile_setup")]
    assert "recent_active_session" not in block
    assert "await manager.async_open_session(" in block


def test_frontend_adopts_preview_watch_list_and_initializes_real_weather_value():
    frontend = (INTEGRATION / "frontend" / "jackenberater-card.js").read_text(encoding="utf-8")
    assert "preview.watched_entities" in frontend
    assert "this._watchedEntities = preview.watched_entities" in frontend
    assert "_ensureSetupWeatherDefault()" in frontend
    assert "this._setup.weather_entity =" in frontend


def test_v050_keeps_new_person_context_in_existing_info_setup_surfaces():
    frontend = (INTEGRATION / "frontend" / "jackenberater-card.js").read_text(encoding="utf-8")
    assert "jackenberater/profile_context" in frontend
    assert "_profileContextPanel(profile)" in frontend
    assert "_startSetupEdit()" in frontend
    assert "edit-setup" in frontend


def test_forecasts_are_entity_keyed_on_demand_not_global_home_work_polling():
    weather = (INTEGRATION / "weather.py").read_text(encoding="utf-8")
    block = weather[weather.index("class JackenWeatherCoordinator"):]
    update = block[block.index("async def _async_update_data"):]
    assert "await _fetch_hourly" not in update
    assert "async_forecast_for" in block
    assert "self._profile_forecasts.get(entity_id)" in block
