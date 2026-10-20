import importlib.util
import json
from pathlib import Path


def load_script():
    path = Path(__file__).resolve().parents[1] / "scripts/submission_preflight.py"
    spec = importlib.util.spec_from_file_location("submission", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_inventory_never_pretends_public_readiness():
    module = load_script()
    manifest = json.loads((module.ROOT / "docs/submission_manifest.json").read_text())
    result = module.inspect(module.ROOT, manifest)
    assert result["local_materials_pass"]
    assert result["external_gates"]
    assert result["submission_readiness_independently_verified"] is False
    assert result["network_calls"] == result["inference_calls"] == 0


def test_missing_artifacts_and_fake_public_video_fail(tmp_path):
    module = load_script()
    manifest = {"repository_url": "http://localhost", "test_build_url": "https://example.com",
                "youtube_url": "https://other.invalid/video", "video_duration_seconds": 180}
    result = module.inspect(tmp_path, manifest)
    assert not result["local_materials_pass"]
    assert any("YouTube" in gate for gate in result["external_gates"])
    assert any("180" in gate for gate in result["external_gates"])


def test_owner_assertions_still_not_independent_verification():
    module = load_script()
    manifest = {"repository_url": "https://github.com/owner/project", "test_build_url": "https://demo.owner.invalid",
                "youtube_url": "https://www.youtube.com/watch?v=placeholder", "video_duration_seconds": 150,
                "owner_confirmations": dict.fromkeys(module.CONFIRMATIONS, True)}
    result = module.inspect(module.ROOT, manifest)
    assert not result["external_gates"]
    assert result["owner_asserted_external_gates_complete"] is True
    assert result["submission_readiness_independently_verified"] is False
