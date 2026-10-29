"""No network or inference: old local dispatch must stop after an explicit move."""
import importlib.util
from pathlib import Path

import pytest


def test_local_ledger_mutation_is_blocked_before_docker_after_handoff(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/serve_investigation_live.py"
    spec = importlib.util.spec_from_file_location("live_handoff_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SOURCE_ROOT", tmp_path)
    (tmp_path / ".private").mkdir()
    (tmp_path / ".private/inference-authority-moved.json").write_text('{"source_count":32}')
    def forbidden(*args, **kwargs):
        raise AssertionError("No local dispatch or ledger write after authority moves")
    monkeypatch.setattr(module.subprocess, "run", forbidden)
    with pytest.raises(RuntimeError, match="authority moved"):
        module.central("UPDATE inference_budget SET reserved_calls=reserved_calls+1")
