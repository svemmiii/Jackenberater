from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "jackenberater"


def _key_paths(value, prefix=()):
    result = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = (*prefix, key)
            result.add(path)
            result |= _key_paths(child, path)
    return result


def test_custom_integration_translation_structure_matches_between_en_and_de():
    en = json.loads((INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8"))
    de = json.loads((INTEGRATION / "translations" / "de.json").read_text(encoding="utf-8"))
    assert _key_paths(en) == _key_paths(de)
    assert not (INTEGRATION / "strings.json").exists()


def test_local_brand_icon_is_present_and_hacs_does_not_ignore_brands():
    icon = INTEGRATION / "brand" / "icon.png"
    data = icon.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    # PNG IHDR width/height are the first two big-endian integers after the
    # signature + IHDR length/type. HACS/HA brand icons are 256x256.
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    assert (width, height) == (256, 256)
    workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
    assert "ignore: brands" not in workflow


def test_only_compact_profile_diagnostics_are_exposed_as_ha_entities():
    for module in ("button.py", "switch.py", "entity.py"):
        source = (INTEGRATION / module).read_text(encoding="utf-8")
        assert "Compatibility placeholder" in source
        assert "ProfileManager" not in source
        assert "Entity" not in source.replace("entities", "")
    sensor_source = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    assert "class ProfileDiagnosticsSensor" in sensor_source
    assert "profile_diagnostics" in sensor_source
    assert "_unrecorded_attributes = frozenset({MATCH_ALL})" in sensor_source
    assert "_attr_entity_registry_enabled_default = False" in sensor_source
    assert "_ignore_next_state_event" not in sensor_source
    assert "async_reset" not in sensor_source
    assert "async_undo" not in sensor_source
    assert "learning_enabled =" not in sensor_source
    init_source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    assert 'PLATFORMS = ["sensor"]' in (INTEGRATION / "const.py").read_text(encoding="utf-8")
    assert "async_forward_entry_setups(entry, PLATFORMS)" in init_source
    assert "_async_remove_legacy_profile_entities(hass, entry)" in init_source
    for suffix in (
        "_learning_enabled",
        "_reset_learning",
        "_undo_feedback",
        "_learning_status",
    ):
        assert suffix in init_source


def test_profile_backup_is_disabled_in_backend_and_frontend():
    const_source = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    api_source = (INTEGRATION / "api.py").read_text(encoding="utf-8")
    frontend_source = (INTEGRATION / "frontend" / "jackenberater-card.js").read_text(
        encoding="utf-8"
    )
    assert "PROFILE_BACKUP_ENABLED = False" in const_source
    assert "if PROFILE_BACKUP_ENABLED:" in api_source
    assert "const JB_PROFILE_BACKUP_ENABLED = false;" in frontend_source


def test_ha_runtime_job_imports_repository_package_reliably():
    pytest_config = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(
        encoding="utf-8"
    )
    assert "pythonpath = ." in pytest_config
    assert "python -m pytest -q tests/ha_runtime" in workflow


def test_forecast_coordinator_has_keepalive_listener_for_periodic_refresh():
    init_source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    assert "coordinator.async_add_listener" in init_source
    assert "entry.async_on_unload" in init_source


def test_manifest_declares_single_config_entry_without_duplicate_flow_guard():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    config_flow = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    assert manifest["single_config_entry"] is True
    assert "_abort_if_unique_id_configured" not in config_flow
    assert 'async_set_unique_id("main")' not in config_flow


def test_frontend_registration_does_not_hide_unexpected_runtime_errors():
    init_source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    assert 'domain_data["frontend_path_registered"] = True' in init_source
    assert "except RuntimeError" not in init_source


def test_release_version_is_consistent_across_current_release_files():
    version = "0.2.0"
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    const_source = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    init_source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    context = (ROOT / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    bug = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text(encoding="utf-8")

    assert manifest["version"] == version
    assert f'INTEGRATION_VERSION = "{version}"' in const_source
    assert f"# JackenBerater v{version}" in readme
    assert f"?v={version}&ui=1" in readme
    assert f"JackenBerater v{version}" in context
    assert changelog.startswith(f"# Changelog\n\n## v{version}\n")
    assert f'value: "{version}"' in bug
    assert 'FRONTEND_CACHE_REVISION = "1"' in init_source
    assert 'wanted = f"{base}?v={INTEGRATION_VERSION}&ui={FRONTEND_CACHE_REVISION}"' in init_source


def test_frontend_narrow_layout_uses_card_width_not_only_viewport():
    frontend = (INTEGRATION / "frontend/jackenberater-card.js").read_text(encoding="utf-8")
    assert "container-type:inline-size" in frontend
    assert "@container (max-width:520px)" in frontend
    assert ".jb-badge{display:none}" in frontend

def test_release_hardening_uses_runtime_data_and_removes_owned_frontend_resource():
    init_source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    api_source = (INTEGRATION / "api.py").read_text(encoding="utf-8")
    weather_source = (INTEGRATION / "weather.py").read_text(encoding="utf-8")
    assert "entry.runtime_data =" in init_source
    assert 'getattr(entry, "runtime_data", None)' in api_source
    assert "config_entry=entry" in weather_source
    assert "async def async_remove_entry" in init_source
    assert "await manager.async_flush()" in init_source
    assert "await manager.async_remove_storage()" in init_source
    assert "async_delete_item" in init_source


def test_profile_deletion_has_runtime_and_registry_cleanup_contract():
    const_source = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    profiles_source = (INTEGRATION / "profiles.py").read_text(encoding="utf-8")
    sensor_source = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
    assert "SIGNAL_PROFILE_DELETED" in const_source
    assert "SIGNAL_PROFILE_DELETED.format" in profiles_source
    assert 'runtime.setdefault("simulations", {}).pop(profile_id, None)' in sensor_source
    assert "registry.async_remove(entity_id)" in sensor_source
    init_source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
    assert "_async_remove_orphan_profile_diagnostics" in init_source
    assert "manager.sync_user_directory" in init_source


def test_user_card_does_not_expose_internal_effective_temperature():
    frontend = (INTEGRATION / "frontend" / "jackenberater-card.js").read_text(encoding="utf-8")
    assert "thermisch etwa" not in frontend
    assert "effective_now_c" not in frontend





def test_bug_report_template_targets_current_release():
    bug = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text(encoding="utf-8")
    assert 'value: "0.2.0"' in bug
