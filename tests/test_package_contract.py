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
