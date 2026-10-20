"""Check an exported evidence digest offline. Does not establish authenticity."""
import argparse
import json
from pathlib import Path
from ownstack.proof import verify_envelope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        envelope = json.loads(args.path.read_text())
        valid = verify_envelope(envelope)
    except (OSError, ValueError, TypeError):
        valid = False
    if not valid:
        raise SystemExit("FAIL: invalid proof envelope or digest mismatch")
    print("PASS: content digest matches. Not proof of authenticity, security or release.")


if __name__ == "__main__":
    main()
