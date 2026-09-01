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
    en = json.loads((INTEGRATION / "translations" / "en.json").read_text())
    de = json.loads((INTEGRATION / "translations" / "de.json").read_text())
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
    workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text()
    assert "ignore: brands" not in workflow
