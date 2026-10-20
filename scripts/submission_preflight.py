"""Offline, read-only submission gate. Never calls a provider or publishes.

Local success is NOT submission readiness. --strict exits 2 until the owner has
supplied and independently checked every external gate. URLs/checkboxes are owner
assertions, not automated proof of availability, eligibility or acceptance.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("LICENSE", "README.md", "compose.full.yaml", "docs/JUDGE_QUICKSTART.md",
            "docs/DEVPOST_COPY.md", "docs/DEVPOST_FIELDS.md", "docs/TOOL_FEEDBACK.md", "docs/VIDEO_SCRIPT.md",
            "docs/PUBLICATION_CHECKLIST.md", "docs/demo_scenes.json", "scripts/render_demo.swift",
            "docs/LEARNING_GUIDE.md", "docs/UNPROVEN.md",
            "docs/evidence/live-workflow.json", "docs/evidence/live-patch-super.json",
            "docs/evidence/manual-recovery.json", "docs/evidence/live-model-comparison.json")
CONFIRMATIONS = ("public_repository_and_license_checked", "judge_build_access_checked",
                 "public_youtube_playback_checked", "current_devpost_form_checked",
                 "eligibility_and_terms_checked", "work_period_and_ai_assistance_disclosed",
                 "tool_feedback_included")


def inspect(root: Path, manifest: dict):
    local_errors = ["missing file: " + name for name in REQUIRED if not (root / name).is_file()]
    try:
        live = json.loads((root / "docs/evidence/live-workflow.json").read_text())
        assert live["live"] is True and live["access"] == "observed_enforced_then_revoked"
        assert live["nova"] == "observed_denied"
        assert live["access_attempts"][0]["state"] == "accepted"
        patch = json.loads((root / "docs/evidence/live-patch-super.json").read_text())
        recovery = json.loads((root / "docs/evidence/manual-recovery.json").read_text())
        assert patch["checks"]["passed"] is False and patch["release_state"] == "not_deployed"
        assert recovery["not_live_model_success"] is True and recovery["checks"]["passed"] is True
    except (OSError, ValueError, AssertionError, KeyError, IndexError, TypeError):
        local_errors.append("historical evidence missing, malformed or inconsistent with submission narrative")
    external = []
    for key in ("repository_url", "test_build_url", "youtube_url"):
        value = manifest.get(key)
        parsed = urlparse(value if isinstance(value, str) else "")
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname in {"localhost", "127.0.0.1", "example.com"}:
            external.append(key + ": supply a real public HTTPS URL")
        elif key == "youtube_url" and parsed.hostname not in {"youtube.com", "www.youtube.com", "youtu.be"}:
            external.append("youtube_url: must be a public YouTube video")
    duration = manifest.get("video_duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 < duration < 180:
        external.append("video_duration_seconds: verified duration must be strictly below 180")
    for key in CONFIRMATIONS:
        if manifest.get("owner_confirmations", {}).get(key) is not True:
            external.append("owner confirmation required: " + key)
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "local_materials_pass": not local_errors, "local_errors": local_errors,
            "external_gates": external, "owner_asserted_external_gates_complete": not external,
            "submission_readiness_independently_verified": False,
            "network_calls": 0, "inference_calls": 0,
            "note": "Offline inventory only. Does not run tests, verify public access, submit, or validate legal eligibility."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "docs/submission_manifest.json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    try:
        result = inspect(ROOT, json.loads(args.manifest.read_text()))
    except (OSError, ValueError):
        parser.error("Cannot read submission manifest")
    print(json.dumps(result, indent=2))
    return 1 if result["local_errors"] else 2 if args.strict and result["external_gates"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
