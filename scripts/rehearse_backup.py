"""Rehearse an explicit SQLite backup in a new private directory without inference."""
import argparse
import json
from pathlib import Path
from ownstack.config import Settings
from ownstack.recovery import rehearse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--private-output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = rehearse(args.source, args.private_output, Settings())
    except Exception as error:
        print(json.dumps({"error_type": type(error).__name__, "passed": False}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
