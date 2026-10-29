"""Configure a local credential without printing it or accepting it in argv."""
import argparse
import getpass
import os
from pathlib import Path
import secrets
import sys
import tempfile
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    if not args.model.startswith("nvidia/") or "nemotron" not in args.model.lower():
        parser.error("Use a verified NVIDIA Nemotron model ID")
    if not sys.stdin.isatty():
        parser.error("Run in an interactive terminal so the key is not echoed")
    key = getpass.getpass("Nebius API key (hidden): ").strip()
    if not key or any(character.isspace() for character in key):
        parser.error("Expected a nonempty API key without whitespace")
    destination = Path(__file__).resolve().parents[1] / ".env"
    values = dict(dotenv_values(destination, interpolate=False)) if destination.exists() else {}
    values.update(NEBIUS_API_KEY=key, NEBIUS_MODEL_ID=args.model, OWNSTACK_AI_MODE="nebius",
                  OWNSTACK_MAX_LIVE_CALLS="10", OWNSTACK_AI_TIMEOUT_SECONDS="60")
    values.setdefault("OWNSTACK_SIGNING_SECRET", secrets.token_urlsafe(48))
    descriptor, temporary = tempfile.mkstemp(prefix=".env-secret-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            for name, value in values.items():
                if value is not None:
                    escaped = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
                    file.write(f"{name}='{escaped}'\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print("Configured ignored .env with owner-only permissions. No inference was called.")


if __name__ == "__main__":
    main()
