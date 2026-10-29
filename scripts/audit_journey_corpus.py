"""Audit pinned private Parquet sources. No installation, inference or execution."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import pyarrow.parquet as pq
from ownstack.journey_corpus import CorpusStore, file_sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--source-directory", type=Path, required=True)
    parser.add_argument("--heldout-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / ".private"
    for path in (args.metadata, args.source_directory, args.output):
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Inputs and audit output must stay under .private")
    metadata = json.loads(args.metadata.read_text())
    heldout = {json.loads(line)["repo"] for line in args.heldout_catalog.read_text().splitlines() if line}
    store = CorpusStore(args.output, heldout)
    for entry in metadata["files"]:
        if not entry["path"].endswith(".parquet"):
            continue
        path = args.source_directory / Path(entry["path"]).name
        if path.is_symlink() or path.stat().st_size != entry["size"] or file_sha(path) != entry["lfs"]["sha256"]:
            raise ValueError("Source size or checksum differs from pinned metadata")
        store.register(metadata["dataset"], metadata["revision"], entry["path"], entry["lfs"]["sha256"])
        ordinal = 0
        for batch in pq.ParquetFile(path).iter_batches(batch_size=128):
            rows = batch.to_pylist()
            store.append_batch(metadata["dataset"], metadata["revision"], entry["path"], ordinal, rows)
            ordinal += len(rows)
            if ordinal % 4096 == 0:
                print(json.dumps({"shard": entry["path"], "audited": ordinal}), flush=True)
        print(json.dumps({"shard": entry["path"], "complete_rows": ordinal}), flush=True)
    result = store.summary()
    # Preserve prior summaries on reruns; the source-coordinate journal is resumable.
    index = len(list(args.output.glob("summary-*.json"))) + 1
    with os.fdopen(os.open(args.output / f"summary-{index:04}.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
        json.dump(result, file, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k not in {"repositories", "sources"}}, indent=2))


if __name__ == "__main__":
    main()
