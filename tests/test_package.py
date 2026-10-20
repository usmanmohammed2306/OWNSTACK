import importlib.util
from pathlib import Path
import sys
import zipfile


def test_source_package_excludes_secrets_caches_and_symlinks(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / "scripts/package_test_build.py"
    spec = importlib.util.spec_from_file_location("ownstack_package", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/visible.md").write_text("public documentation")
    (tmp_path / "docs/.env.private").write_text("PRIVATE")
    (tmp_path / "docs/link.md").symlink_to(tmp_path / "docs/.env.private")
    (tmp_path / ".env").write_text("PRIVATE")
    (tmp_path / ".env.example").write_text("placeholder")
    (tmp_path / "docs/__pycache__").mkdir()
    (tmp_path / "docs/__pycache__/cached.pyc").write_text("private cache")
    names = {name for _, name in module.public_paths()}
    assert names == {".env.example", "docs/visible.md"}
    archive = tmp_path / "test-build.zip"
    monkeypatch.setattr(sys, "argv", ["package_test_build", "--output", str(archive)])
    module.main()
    with zipfile.ZipFile(archive) as packaged:
        assert all((info.external_attr >> 16) & 0o777 == 0o644 for info in packaged.infolist())
        assert set(packaged.namelist()) == {"ownstack/.env.example", "ownstack/docs/visible.md", "ownstack/SOURCE_MANIFEST.json"}


def test_source_package_includes_frontend_review_tests():
    script = Path(__file__).resolve().parents[1] / "scripts/package_test_build.py"
    spec = importlib.util.spec_from_file_location("ownstack_package_ui", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    names = {name for _, name in module.public_paths()}
    assert "web/tests/review.test.mjs" in names
    assert "web/src/review.ts" in names
    assert "web/src/ApprovalReview.tsx" in names
