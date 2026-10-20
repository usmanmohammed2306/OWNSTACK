import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile
import pytest


def module():
    script = Path(__file__).resolve().parents[1] / "scripts/package_submission.py"
    spec = importlib.util.spec_from_file_location("submission_bundle", script)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_source_digest_mismatch_and_unlisted_files_fail(tmp_path):
    checker = module()
    for index, extra in enumerate((False, True)):
        path = tmp_path / f"source-{index}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("ownstack/README.md", "tampered" if not extra else "source")
            archive.writestr("ownstack/SOURCE_MANIFEST.json", json.dumps({"README.md": hashlib.sha256(b"source").hexdigest()}))
            if extra:
                archive.writestr("ownstack/.env", "private")
        with pytest.raises(ValueError):
            checker.checked_sources(path)


def test_bundle_excludes_intermediates_and_refuses_long_video(tmp_path):
    builder = module()
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("ownstack/README.md", "source")
        archive.writestr("ownstack/SOURCE_MANIFEST.json", json.dumps({"README.md": hashlib.sha256(b"source").hexdigest()}))
    report = {"duration_seconds": 180, "video_tracks": 1, "audio_tracks": 1,
              "inference_calls": 0, "format": "unit-test fake media, not a live demo"}
    (tmp_path / "render-report.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="180"):
        builder.bundle(source, tmp_path, tmp_path / "rejected.zip")
    report["duration_seconds"] = 162
    (tmp_path / "render-report.json").write_text(json.dumps(report))
    (tmp_path / "OwnStack-demo.mp4").write_bytes(b"unit-test placeholder only")
    (tmp_path / "OwnStack-demo.vtt").write_text("WEBVTT")
    (tmp_path / ".env").write_text("private")
    (tmp_path / "narration-1.aiff").write_text("intermediate")
    output = tmp_path / "bundle.zip"
    result = builder.bundle(source, tmp_path, output)
    assert result["published"] is False and result["new_inference_calls"] == 0
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"ownstack-test-build.zip", "OwnStack-demo.mp4", "OwnStack-demo.vtt",
                                             "PUBLICATION_CHECKLIST.md", "BUNDLE_MANIFEST.json"}
    with pytest.raises(ValueError, match="new output"):
        builder.bundle(source, tmp_path, output)
