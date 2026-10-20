"""Print one planned learning slice. Read-only, offline, never invokes Git or AI."""
import argparse
from datetime import date, datetime
import json
from pathlib import Path
import shlex
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
START = date(2026, 10, 19)
END = date(2027, 1, 16)


def plan(root=ROOT):
    entries = []
    for line in (root / "docs/NINETY_DAY_PLAN.md").read_text().splitlines():
        columns = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(columns) == 7 and columns[0].isdigit():
            day, dated, feature, reference, proof, check, commit = columns
            entries.append({"day": int(day), "date": dated, "feature": feature, "reference": reference,
                            "proof": proof, "reference_check": check, "suggested_commit": commit})
    if len(entries) != 90 or [e["day"] for e in entries] != list(range(1, 91)):
        raise ValueError("Plan must contain ninety sequential days")
    for entry in entries:
        if (date.fromisoformat(entry["date"]) - START).days != entry["day"] - 1:
            raise ValueError("Plan dates must be continuous")
        reference = (root / entry["reference"]).resolve()
        if not reference.is_relative_to(root.resolve()) or not reference.is_file():
            raise ValueError("Reference file missing or outside project")
        # Treat command text only as data; also catch stale example test names.
        checks = [part for part in shlex.split(entry["reference_check"]) if part.endswith((".py", ".mjs"))]
        if not checks or any(not (root / path).is_file() for path in checks):
            raise ValueError("Reference check file missing")
    return entries


def progress(path):
    if not path.exists():
        return set()
    raw = json.loads(path.read_text())
    days = raw["completed_days"]
    if (not isinstance(days, list) or any(type(day) is not int or not 1 <= day <= 90 for day in days)
            or len(days) != len(set(days))):
        raise ValueError("completed_days must contain unique integer days 1 to 90")
    return set(days)


def select_day(entries, today, completed, day=None, next_incomplete=False):
    if day is not None:
        if not 1 <= day <= 90:
            raise ValueError("Day must be 1 to 90")
        return entries[day - 1]
    if today < START or today > END:
        return None
    if next_incomplete:
        return next((entry for entry in entries if entry["day"] not in completed), None)
    return entries[(today - START).days]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--day", type=int)
    group.add_argument("--next", action="store_true", dest="next_incomplete")
    parser.add_argument("--date", type=date.fromisoformat, help="Inspect another date; does not change progress")
    parser.add_argument("--progress", type=Path, default=ROOT / ".private/learning-progress.json")
    parser.add_argument("--check-plan", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        entries = plan()
        if args.check_plan:
            print(json.dumps({"days": len(entries), "start": START.isoformat(), "end": END.isoformat(),
                              "reference_paths": "checked", "completion_claimed": False}))
            return 0
        completed = progress(args.progress)
        today = args.date or datetime.now(ZoneInfo("America/Phoenix")).date()
        entry = select_day(entries, today, completed, args.day, args.next_incomplete)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    if entry is None:
        print("No pending lesson in this ninety-day window. No work was marked complete.")
        return 0
    if args.json:
        print(json.dumps({**entry, "completion": "self_recorded" if entry["day"] in completed else "planned",
                          "inference_calls": 0}, indent=2))
        return 0
    print(f'Day {entry["day"]:02d} / {entry["date"]}: {entry["feature"]}')
    print(f'Predict and prove: {entry["proof"]}')
    print(f'Read: {entry["reference"]}')
    print(f'Reference check: {entry["reference_check"]}')
    print("Implement one behavior in your learner repo and run its matching negative test.")
    print(f'Commit after your check passes: {entry["suggested_commit"]}')
    print("Review specific changed files, commit and push yourself. This command changed nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
