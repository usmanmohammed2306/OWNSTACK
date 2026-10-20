import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("graph_lab", Path(__file__).resolve().parents[1] / "scripts/run_graph_lab.py")
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


@pytest.mark.parametrize("case", list(lab.CASES))
def test_declared_graph_lab_cases_match_sequential_reference(tmp_path, case):
    engine, factory = lab.setup_database(tmp_path / "lab.db")
    try:
        results = [lab.scenario(factory, scheduler, case, scheduler + "-" + case) for scheduler in ("plain", "langgraph")]
        assert all(row["passed"] for row in results)
        assert results[0]["saved"] == results[1]["saved"]
    finally:
        engine.dispose()


def test_native_interrupt_replay_control_is_detected():
    result = lab.interrupt_replay_experiment()
    assert result["passed"]
    assert result["side_effect_before_interrupt"]["calls_after_resume"] == 2
    assert result["separate_generation_node"]["calls_after_resume"] == 1
