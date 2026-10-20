"""Initialize only the named verifier job volume with shared service permissions."""
import os
from pathlib import Path


def main() -> None:
    root = Path("/srv/jobs")
    for path in (root, root / "incoming", root / "outgoing"):
        path.mkdir(parents=True, exist_ok=True)
        os.chown(path, 0, 10001)
        path.chmod(0o770)
        os.chown(path, 10001, 10001)


if __name__ == "__main__":
    main()
