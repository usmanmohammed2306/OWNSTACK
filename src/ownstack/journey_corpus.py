"""Private, resumable admission audit for sourced journey candidates.

An imported PR is not a completed OwnStack journey. Exact-text fingerprints only
detect some duplicates; neither they nor upstream model annotations prove semantic
diversity, persona relevance, test validity or a right to train. Gold patches stay
in private source files and are never returned as training pairs by this module.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from ownstack.experiment_store import canonical, digest

POLICY = "sourced-candidate-admission-v1"
SPDX = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "MPL-2.0",
        "GPL-2.0", "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0", "GPL-3.0-only",
        "GPL-3.0-or-later", "LGPL-2.1", "LGPL-2.1-only", "LGPL-2.1-or-later",
        "LGPL-3.0-only", "LGPL-3.0-or-later", "Unlicense", "CC0-1.0"}
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
SHA = re.compile(r"[a-f0-9]{40}")


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def private_dir(path: Path) -> Path:
    """Require an existing private directory, without symlink ancestors."""
    absolute = path.absolute()
    if any(p.is_symlink() for p in (absolute, *absolute.parents)):
        raise ValueError("No symlink corpus path or ancestors")
    if not path.is_dir() or path.stat().st_mode & 0o077:
        raise ValueError("Use an existing directory with mode 0700")
    return absolute


def normalized_sha(value: str) -> str:
    return digest(" ".join(value.casefold().split()))


def audit_row(row: dict, heldout_repos: set[str]) -> dict:
    """Describe blockers without executing source code or trusting source commands."""
    issues = []
    case_id, repo = row.get("instance_id"), row.get("repo")
    if not isinstance(case_id, str) or not case_id or len(case_id) > 250:
        issues.append("invalid_case_identity")
    if not isinstance(repo, str) or not REPO.fullmatch(repo) or any(
            p in {".", ".."} for p in str(repo).split("/")):
        issues.append("invalid_repository")
    commit = row.get("base_commit")
    if not isinstance(commit, str) or not SHA.fullmatch(commit):
        issues.append("unpinned_source")
    problem = row.get("problem_statement") or ""
    description = row.get("pr_description") or ""
    patch = row.get("patch") or ""
    test_patch = row.get("test_patch") or ""
    for value in (problem, description, patch, test_patch):
        if not isinstance(value, str) or len(value) > 4_000_000:
            raise ValueError("Source text must be a bounded string")
    if len(problem.strip()) < 80:
        issues.append("insufficient_problem")
    if not description.strip():
        issues.append("no_original_pr_description")
    if not patch.strip() or not test_patch.strip():
        issues.append("missing_patch_or_oracle")
    tests = []
    for name in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        value = row.get(name)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                value = None
        if (not isinstance(value, list) or not value or
                not all(isinstance(t, str) and t and len(t) <= 4000 for t in value)):
            issues.append("missing_or_invalid_" + name.lower())
            value = []
        tests.extend(value)
    if len(tests) != len(set(tests)):
        issues.append("overlapping_or_duplicate_test_ids")
    license_id = row.get("license") or "unknown"
    if license_id not in SPDX:
        issues.append("license_review_required")
    meta = row.get("meta") or {}
    annotation = meta.get("llm_metadata") or {}
    detected = annotation.get("detected_issues") or {}
    if not isinstance(detected, dict):
        issues.append("invalid_quality_annotations")
    else:
        issues.extend("upstream_quality_" + str(k) for k, v in detected.items() if v is True)
    if not annotation:
        issues.append("missing_quality_annotations")
    if repo in heldout_repos:
        issues.append("heldout_repository")
    # Even a clean source row needs a reviewed environment and a new independent
    # candidate. Upstream install/test command strings never become executable.
    gates = ["environment_not_reviewed", "candidate_missing", "not_executed",
             "persona_fit_unreviewed", "human_review_missing"]
    return {
        "case_id": case_id if isinstance(case_id, str) else "invalid",
        "repo": repo if isinstance(repo, str) else "invalid",
        "base_commit": commit,
        "source_url": ("https://github.com/" + repo + "/pull/" + str(row["pull_number"]))
        if "invalid_repository" not in issues and type(row.get("pull_number")) is int
        and row["pull_number"] > 0 else None,
        "problem_sha256": normalized_sha(problem) if problem.strip() else None,
        "pr_description_sha256": digest(description),
        "problem_origin": "upstream_reconstruction_unverified",
        "patch_sha256": normalized_sha(patch) if patch.strip() else None,
        "oracle_sha256": normalized_sha(test_patch) if test_patch.strip() else None,
        "raw_row_sha256": digest(canonical(row)),
        "license": license_id,
        "categories": annotation.get("pr_categories") or [],
        "difficulty": annotation.get("difficulty"),
        "source_quality_blockers": sorted(set(issues)),
        "execution_gates": gates,
        "persona_id": None,
        "execution_status": "not_executed",
        "training_eligible": False,
    }


class CorpusStore:
    """Commit each bounded batch; replay of identical source coordinates is inert."""

    def __init__(self, directory: Path, heldout_repos: set[str]):
        self.directory = private_dir(directory)
        self.heldout_repos = heldout_repos
        self.policy = digest(canonical({"policy": POLICY, "heldout": sorted(heldout_repos),
                                       "source": file_sha(Path(__file__))}))
        self.path = self.directory / "corpus.sqlite"
        if self.path.is_symlink():
            raise ValueError("No database symlink")
        if not self.path.exists():
            os.close(os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        if self.path.stat().st_mode & 0o077:
            raise ValueError("Private database permissions required")
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sources (
                    dataset TEXT, revision TEXT, shard TEXT, sha256 TEXT, policy TEXT,
                    PRIMARY KEY(dataset,revision,shard));
                CREATE TABLE IF NOT EXISTS cases (
                    dataset TEXT, revision TEXT, shard TEXT, ordinal INTEGER,
                    case_id TEXT, repo TEXT, problem_hash TEXT, patch_hash TEXT,
                    oracle_hash TEXT, raw_hash TEXT, body TEXT,
                    PRIMARY KEY(dataset,revision,shard,ordinal));
                CREATE INDEX IF NOT EXISTS case_identity ON cases(case_id);
                CREATE INDEX IF NOT EXISTS problem_identity ON cases(problem_hash);
                CREATE INDEX IF NOT EXISTS patch_identity ON cases(patch_hash);
                CREATE INDEX IF NOT EXISTS oracle_identity ON cases(oracle_hash);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def register(self, dataset: str, revision: str, shard: str, checksum: str):
        if not SHA.fullmatch(revision) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise ValueError("Pinned revision and checksum required")
        value = (dataset, revision, shard, checksum, self.policy)
        with self.connection() as db:
            prior = db.execute("SELECT * FROM sources WHERE dataset=? AND revision=? AND shard=?",
                               value[:3]).fetchone()
            if prior and prior != value:
                raise ValueError("Source bytes or admission policy changed; use a new store")
            db.execute("INSERT OR IGNORE INTO sources VALUES (?,?,?,?,?)", value)

    def append_batch(self, dataset: str, revision: str, shard: str,
                     start: int, rows: list[dict]) -> int:
        if start < 0 or not rows or len(rows) > 256:
            raise ValueError("Use 1..256 rows and a nonnegative source ordinal")
        added = 0
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            source = db.execute("SELECT policy FROM sources WHERE dataset=? AND revision=? AND shard=?",
                                (dataset, revision, shard)).fetchone()
            if not source or source[0] != self.policy:
                raise ValueError("Register pinned source with the current policy first")
            for ordinal, row in enumerate(rows, start):
                item = audit_row(row, self.heldout_repos)
                identity = (dataset, revision, shard, ordinal)
                prior = db.execute("SELECT raw_hash FROM cases WHERE dataset=? AND revision=? AND shard=? AND ordinal=?",
                                   identity).fetchone()
                if prior:
                    if prior[0] != item["raw_row_sha256"]:
                        raise ValueError("Source coordinate replay has different bytes")
                    continue
                for field, column in (("case_id", "case_id"), ("problem_sha256", "problem_hash"),
                                      ("patch_sha256", "patch_hash"), ("oracle_sha256", "oracle_hash")):
                    if item[field] and db.execute("SELECT 1 FROM cases WHERE " + column + "=? LIMIT 1",
                                                 (item[field],)).fetchone():
                        item["source_quality_blockers"].append("duplicate_" + field)
                db.execute("INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                    *identity, item["case_id"], item["repo"], item["problem_sha256"],
                    item["patch_sha256"], item["oracle_sha256"], item["raw_row_sha256"], canonical(item)))
                added += 1
        return added

    def summary(self) -> dict:
        blockers, repositories, categories = Counter(), Counter(), Counter()
        total = clean = 0
        with self.connection() as db:
            for (body,) in db.execute("SELECT body FROM cases ORDER BY rowid"):
                item = json.loads(body)
                total += 1
                clean += not item["source_quality_blockers"]
                blockers.update(item["source_quality_blockers"])
                repositories.update([item["repo"]])
                categories.update(item["categories"])
            sources = [dict(zip(("dataset", "revision", "shard", "sha256", "policy"), row))
                       for row in db.execute("SELECT * FROM sources ORDER BY dataset,revision,shard")]
        return {"policy": self.policy, "source_rows_audited": total,
                "rows_without_detected_source_blockers": clean,
                "source_blockers": dict(blockers), "repository_count": len(repositories),
                "repositories": dict(repositories), "categories": dict(categories),
                "sources": sources, "imported_corpus_completed_journeys": 0,
                "persona_assignments": 0, "training_eligible": 0, "training_has_run": False,
                "provider_calls": 0, "target_completed_journeys": 100000,
                "required_per_persona": 1000, "target_met": False,
                "limitations": ["Import and quality audit are not execution",
                                "Exact normalization is not semantic diversity proof",
                                "Published PR descriptions and reconstructed problems remain distinct",
                                "Licenses and persona fit need review",
                                "Source annotations are untrusted model outputs",
                                "New candidates, environments, independent checks and human review are missing"]}
