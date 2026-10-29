"""Verify runtime archive integrity and required files. Does not run or deploy it."""
import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

REQUIRED = {"README.md", "LICENSE", "pyproject.toml", "constraints.txt", "Dockerfile",
    "compose.full.yaml", "compose.production.yaml", "alembic.ini", "migrations/env.py",
    "migrations/versions/b73e2c91d406_investigations.py", "src/ownstack/api.py",
    "src/ownstack/investigation.py", "src/ownstack/identity_admin.py", "src/ownstack/worker.py",
    "src/ownstack/deployment.py",
    "src/ownstack/verifier_service.py", "web/src/main.tsx", "web/package.json",
    "web/pnpm-lock.yaml", "web/Dockerfile", "web/nginx.conf", "sample_app/report.py",
    "checks/test_report.py", "ops/Caddyfile"}
REQUIRED.update({
    'evals/real_issues_v1/cases.jsonl', 'evals/real_issues_v1/manifest.json',
    'evals/repository_additions_v2/cases.jsonl', 'evals/repository_additions_v2/manifest.json',
    *['evals/repository_candidates/' + name + '.json' for name in
      ['flask-blueprints','flask-decimal','flask-exception','pytest-approx','sphinx-napoleon','sphinx-signature','jinja-native']],
    *['ops/repository-executor/' + name for name in
      ['Dockerfile','pytest72.Dockerfile','sphinx31.Dockerfile','jinja30.Dockerfile']],
})


def verify(path):
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or len(names) > 2000 or sum(i.file_size for i in infos) > 64 * 1024 * 1024:
            raise ValueError("Duplicate members or oversized archive")
        data = {}
        for info in infos:
            parts = PurePosixPath(info.filename).parts
            if (not parts or parts[0] != "ownstack" or ".." in parts or "\\" in info.filename
                    or info.filename != PurePosixPath(info.filename).as_posix()
                    or info.is_dir() or stat.S_ISLNK(info.external_attr >> 16)
                    or any(part in {".git", ".private", ".venv", "node_modules", "__pycache__", ".pytest_cache"} for part in parts)
                    or any(part.startswith(".env") and part not in {".env.example", ".env.production.example"} for part in parts)
                    or Path(info.filename).suffix in {".db", ".db-wal", ".db-shm", ".db-journal", ".sqlite", ".sqlite3", ".dump", ".pyc"}):
                raise ValueError("Unsafe or private archive member")
            data["/".join(parts[1:])] = archive.read(info)
        try:
            manifest = json.loads(data.pop("SOURCE_MANIFEST.json"))
        except (KeyError, ValueError):
            raise ValueError("Missing or invalid source manifest") from None
        if not isinstance(manifest, dict) or set(manifest) != set(data):
            raise ValueError("Manifest inventory mismatch")
        for name, expected in manifest.items():
            if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected) or hashlib.sha256(data[name]).hexdigest() != expected:
                raise ValueError("Source digest mismatch")
        if not REQUIRED <= set(data):
            raise ValueError("Required runtime files missing")
        for name, raw in data.items():
            if not name.startswith("src/ownstack/") or not name.endswith(".py"):
                continue
            try:
                tree = ast.parse(raw.decode("utf-8"))
            except (UnicodeError, SyntaxError):
                raise ValueError("Invalid Python source") from None
            modules = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module == "ownstack":
                        modules.extend("ownstack." + alias.name for alias in node.names)
                    elif node.module.startswith("ownstack."):
                        modules.append(node.module)
                elif isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names if alias.name.startswith("ownstack."))
            for module in modules:
                target = "src/" + module.replace(".", "/")
                if target + ".py" not in data and target + "/__init__.py" not in data:
                    raise ValueError("Local Python dependency missing")
    return {"files": len(data), "archive_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "integrity": "verified", "authenticity": "not established by a digest",
        "runtime_executed": False, "deployed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.archive)))
    except (OSError, ValueError, zipfile.BadZipFile):
        parser.exit(1, "Release verification failed. Do not run this archive.\n")


if __name__ == "__main__":
    main()
