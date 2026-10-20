from datetime import date
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("daily_slice", ROOT / "scripts/daily_slice.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_plan_has_exact_ninety_real_reference_slices():
    entries = module.plan()
    assert len(entries) == 90
    assert entries[0]["date"] == "2026-10-19"
    assert entries[-1]["date"] == "2027-01-16"
    assert all(e["suggested_commit"].startswith("feat:") for e in entries)


def test_calendar_boundaries_and_next_unfinished_are_not_completion():
    entries = module.plan()
    assert module.select_day(entries, date(2026, 10, 18), set()) is None
    assert module.select_day(entries, date(2026, 10, 19), set())["day"] == 1
    assert module.select_day(entries, date(2027, 1, 16), set())["day"] == 90
    assert module.select_day(entries, date(2027, 1, 17), set()) is None
    assert module.select_day(entries, date(2026, 10, 30), set())["day"] == 12
    assert module.select_day(entries, date(2026, 10, 30), {1, 3}, next_incomplete=True)["day"] == 2
    assert module.select_day(entries, date(2026, 10, 30), set(range(1, 91)), next_incomplete=True) is None


@pytest.mark.parametrize("days", [[0], [91], [True], [1, 1], ["1"]])
def test_progress_rejects_invalid_days(tmp_path, days):
    path = tmp_path / "progress.json"
    path.write_text(json.dumps({"completed_days": days}))
    with pytest.raises(ValueError):
        module.progress(path)


def test_inspection_does_not_write_progress(tmp_path, capsys):
    path = tmp_path / "progress.json"
    before = '{"completed_days": [1]}'
    path.write_text(before)
    assert module.main(["--date", "2026-10-19", "--next", "--progress", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["day"] == 2
    assert path.read_text() == before
