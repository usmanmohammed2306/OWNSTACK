"""Reviewed local environments, never commands supplied by a dataset or model.

Historical dependencies are disposable test fixtures, not production packages.
Adding a repository requires an explicit environment, paths and actual execution.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class Profile:
    id: str
    repo: str
    versions: tuple[str, ...]
    image: str
    source_prefixes: tuple[str, ...]
    test_prefix: str
    pythonpath: str
    marker: str
    dockerfile: str
    forbidden_prefixes: tuple[str, ...] = ()
    generated_files: tuple[tuple[str, str], ...] = ()
    pytest_args: tuple[str, ...] = ()


PROFILES = {
    "flask-2.0-python3.10-v1": Profile(
        "flask-2.0-python3.10-v1", "pallets/flask", ("2.0",),
        "ownstack-repository-flask20:local", ("src/flask/",), "tests/", "/repo/src",
        "src/flask/__init__.py", "ops/repository-executor/Dockerfile"),
    "pytest-7.2-python3.10-v1": Profile(
        "pytest-7.2-python3.10-v1", "pytest-dev/pytest", ("7.2",),
        "ownstack-repository-pytest72:local", ("src/_pytest/", "src/pytest/"), "testing/", "/repo/src",
        "src/_pytest/__init__.py", "ops/repository-executor/pytest72.Dockerfile",
        generated_files=(("src/_pytest/_version.py", "version = '7.2.2'\nversion_tuple = (7, 2, 2)\n"),),
        pytest_args=("-p", "pytester")),
    "sphinx-3.1-python3.8-v1": Profile(
        "sphinx-3.1-python3.8-v1", "sphinx-doc/sphinx", ("3.1",),
        "ownstack-repository-sphinx31:local", ("sphinx/",), "tests/", "/repo",
        "sphinx/__init__.py", "ops/repository-executor/sphinx31.Dockerfile", ("sphinx/testing/",)),
    "jinja-3.0-python3.10-v1": Profile(
        "jinja-3.0-python3.10-v1", "pallets/jinja", ("3.0",),
        "ownstack-repository-jinja30:local", ("src/jinja2/",), "tests/", "/repo/src",
        "src/jinja2/__init__.py", "ops/repository-executor/jinja30.Dockerfile",
        pytest_args=("-p", "pytest_asyncio.plugin", "-o", "asyncio_mode=strict")),
}

CASE_PROFILES = {
    "pallets__flask-4045": "flask-2.0-python3.10-v1",
    "pallets__flask-4160": "flask-2.0-python3.10-v1",
    "pallets__flask-4169": "flask-2.0-python3.10-v1",
    "pytest-dev__pytest-10624": "pytest-7.2-python3.10-v1",
    "sphinx-doc__sphinx-7738": "sphinx-3.1-python3.8-v1",
    "sphinx-doc__sphinx-7757": "sphinx-3.1-python3.8-v1",
    "pallets__jinja-1537": "jinja-3.0-python3.10-v1",
}

EXAMPLES = dict(zip(CASE_PROFILES, (
    "flask-blueprints.json", "flask-decimal.json", "flask-exception.json",
    "pytest-approx.json", "sphinx-napoleon.json", "sphinx-signature.json", "jinja-native.json")))

TRAIN_CASES = frozenset({"pallets__jinja-1537"})
SUPPLEMENT = 'evals/repository_additions_v2'


def supplemental_cases() -> dict:
    """Do not relabel old test cases. Verify the separate train-source projection."""
    root = Path(os.getenv('OWNSTACK_SOURCE_ROOT', Path(__file__).resolve().parents[2]))
    raw = (root / SUPPLEMENT / 'cases.jsonl').read_bytes()
    manifest = json.loads((root / SUPPLEMENT / 'manifest.json').read_text())
    if (hashlib.sha256(raw).hexdigest() != manifest['catalog_sha256']
            or manifest['dataset'] != 'nebius/SWE-rebench-V2-PRs'
            or manifest['revision'] != 'fbf0ecf50f268d5344149e2f0097db6bede83737'
            or manifest['source_split'] != 'train'):
        raise ValueError('Supplemental source provenance changed')
    rows = [json.loads(line) for line in raw.decode().splitlines()]
    if len(rows) != len(TRAIN_CASES) or {r['id'] for r in rows} != TRAIN_CASES:
        raise ValueError('Unexpected supplemental source identities')
    if any(r['source_split'] != 'train' or r['raw_row_sha256'] != manifest['raw_row_sha256'] for r in rows):
        raise ValueError('Supplemental split or raw source changed')
    return {r['id']: r for r in rows}


def for_source(repo: str, version: str) -> Profile:
    for profile in PROFILES.values():
        if profile.repo == repo and version in profile.versions:
            return profile
    raise ValueError("No reviewed execution environment for this repository/version")


def by_id(ident: str) -> Profile:
    try:
        return PROFILES[ident]
    except KeyError:
        raise ValueError("Unknown reviewed execution profile") from None
