"""Bundle an inventoried source build, final local video and captions. No upload.

Explicit input files only; no narration intermediates, credentials or databases.
Refuses overwrite, invalid source inventory and video reports at/over 3 minutes.
Reported media metadata is from the local renderer, not independent attestation.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def checked_sources(path: Path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate source archive paths")
        manifest = json.loads(archive.read("ownstack/SOURCE_MANIFEST.json"))
        expected = {"ownstack/" + name for name in manifest} | {"ownstack/SOURCE_MANIFEST.json"}
        if set(names) != expected:
            raise ValueError("Source inventory does not cover every entry")
        for name, expected_hash in manifest.items():
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or (
                relative.name.startswith(".env") and relative.name not in {".env.example", ".env.production.example"}
            ) or relative.suffix in {".db", ".pyc"}:
                raise ValueError("Unsafe source archive path")
            if hashlib.sha256(archive.read("ownstack/" + name)).hexdigest() != expected_hash:
                raise ValueError("Source digest mismatch")
    return len(manifest)


def bundle(source: Path, video_dir: Path, output: Path):
    if output.exists():
        raise ValueError("Choose a new output path; existing artifacts are never overwritten")
    file_count = checked_sources(source)
    report = json.loads((video_dir / "render-report.json").read_text())
    duration = report["duration_seconds"]
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 < duration < 180:
        raise ValueError("Demo must be strictly under 180 seconds")
    if report["video_tracks"] != 1 or report["audio_tracks"] != 1 or report["inference_calls"] != 0:
        raise ValueError("Unexpected local render metadata")
    files = {"ownstack-test-build.zip": source,
             "OwnStack-demo.mp4": video_dir / "OwnStack-demo.mp4",
             "OwnStack-demo.vtt": video_dir / "OwnStack-demo.vtt",
             "PUBLICATION_CHECKLIST.md": ROOT / "docs/PUBLICATION_CHECKLIST.md"}
    if any(path.is_symlink() for path in files.values()):
        raise ValueError("Do not bundle symlink inputs")
    inventory = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}
    metadata = {"files_sha256": inventory, "source_files": file_count, "video_duration_seconds": duration,
                "format": report["format"], "published": False, "submitted": False,
                "new_inference_calls": 0, "digest_is_signed_attestation": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in files.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
        archive.writestr("BUNDLE_MANIFEST.json", json.dumps(metadata, indent=2) + "\n")
    return {"artifact": str(output.resolve()), "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), **metadata}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-build", required=True, type=Path)
    parser.add_argument("--video-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = bundle(args.source_build, args.video_dir, args.output)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        parser.error("Invalid bundle inputs or existing output; verify source/video artifacts")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
