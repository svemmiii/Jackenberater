from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1] / "custom_components" / "jackenberater"

spec = importlib.util.spec_from_file_location("jackenberater_time_utils_test", ROOT / "time_utils.py")
time_utils = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(time_utils)


def test_real_add_uses_elapsed_hours_across_both_dst_changes():
    berlin = ZoneInfo("Europe/Berlin")
    for start in (
        datetime(2026, 3, 28, 20, tzinfo=berlin),
        datetime(2026, 10, 24, 20, tzinfo=berlin),
    ):
        end = time_utils.real_add(start, timedelta(hours=16))
        assert time_utils.elapsed(start, end) == timedelta(hours=16)


def test_ambiguous_fold_is_ordered_by_real_utc_instant():
    berlin = ZoneInfo("Europe/Berlin")
    first = datetime(2026, 10, 25, 2, 30, tzinfo=berlin, fold=0)
    second = datetime(2026, 10, 25, 2, 15, tzinfo=berlin, fold=1)
    assert time_utils.is_after(second, first)
    assert time_utils.elapsed(first, second) == timedelta(minutes=45)
    assert time_utils.instant_key(first) != time_utils.instant_key(second)
    assert time_utils.as_utc(first).tzinfo == timezone.utc
