"""Create a source-only reproducible test build and exact SHA-256 inventory.

Uses an explicit public-file allowlist. Never includes .env, git, runtime databases,
installed dependencies, private files, or live credentials.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = ["README.md", "LICENSE", "pyproject.toml", "constraints.txt", "Dockerfile",
                ".dockerignore", ".gitignore", ".env.example", ".env.production.example",
                "alembic.ini", "compose.yaml", "compose.full.yaml", "compose.production.yaml", "compose.rehearsal.yaml"]
PUBLIC_DIRS = ["src", "checks", "sample_app", "sample_apps_compat", "tests", "migrations", "scripts", "docs", "evals", "ops", ".github"]
WEB_FILES = ["package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "Dockerfile", ".dockerignore",
             "nginx.conf", "tsconfig.json", "vite.config.ts", "index.html"]


def public_paths():
    paths = [ROOT / name for name in PUBLIC_FILES] + [ROOT / "web" / name for name in WEB_FILES]
    for directory in [*PUBLIC_DIRS, "web/src", "web/tests"]:
        paths.extend((ROOT / directory).rglob("*"))
    for path in sorted(set(paths)):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(ROOT)
        if any(part in {"__pycache__", ".pytest_cache", "node_modules", ".private"} for part in relative.parts):
            continue
        if path.suffix in {".pyc", ".db", ".db-wal", ".db-shm", ".db-journal", ".sqlite", ".sqlite3", ".dump"} or (path.name.startswith(".env") and path.name not in {".env.example", ".env.production.example"}):
            continue
        yield path, relative.as_posix()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("Choose a new output path; existing artifacts are not overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        def add_public(name, data):
            info = zipfile.ZipInfo("ownstack/" + name)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
        for path, relative in public_paths():
            if path.resolve() == output:
                continue
            data = path.read_bytes()
            manifest[relative] = hashlib.sha256(data).hexdigest()
            add_public(relative, data)
        add_public("SOURCE_MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"artifact": str(output), "files": len(manifest),
                      "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                      "runtime_proof_checked_by_packager": False, "public_url_created": False}))


if __name__ == "__main__":
    main()
