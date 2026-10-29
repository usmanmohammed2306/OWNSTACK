"""Reproduce the private Jinja evaluator from pinned public train-source bytes.

Requires the optional research extra. Does not run source, generate a candidate,
admit training data, modify the original evaluator or contact any AI provider.
"""
import argparse
import json
import os
from pathlib import Path

from ownstack.experiment_store import canonical, digest
from ownstack.journey_corpus import file_sha
from ownstack.repository_executor import ROOT, private_directory
from ownstack.repository_profiles import SUPPLEMENT, supplemental_cases

SHARD_BYTES = 946882400
SHARD_SHA = '2d754c0b1edb075e791d1299eb2e7a88e10c9c655282e26c24c56410dc6dfd49'


def prepare(source: Path, original: Path, output: Path):
    for path in [source, original, output]:
        if path.is_symlink() or not path.resolve().is_relative_to((ROOT / '.private').resolve()):
            raise ValueError('Keep evaluator inputs and outputs under .private without symlinks')
    if output.exists():
        raise FileExistsError('Preserve previous evaluators')
    if source.stat().st_size != SHARD_BYTES or file_sha(source) != SHARD_SHA:
        raise ValueError('Source differs from the pinned public shard')
    supplemental_cases()  # Check the public projection before reading gold bytes.
    manifest = json.loads((ROOT / SUPPLEMENT / 'manifest.json').read_text())
    import pyarrow.parquet as pq
    parquet = pq.ParquetFile(source)
    offset, index, selected = 0, manifest['source_ordinal'], None
    for group in range(parquet.num_row_groups):
        count = parquet.metadata.row_group(group).num_rows
        if offset <= index < offset + count:
            position = offset
            for batch in parquet.iter_batches(batch_size=128, row_groups=[group]):
                if position <= index < position + batch.num_rows:
                    selected = batch.slice(index - position, 1).to_pylist()[0]
                    break
                position += batch.num_rows
            break
        offset += count
    if not selected or digest(canonical(selected)) != manifest['raw_row_sha256']:
        raise ValueError('Selected source row differs from its pinned original')
    if selected['instance_id'] != 'pallets__jinja-1537' or selected['license'] != 'BSD-3-Clause':
        raise ValueError('Unexpected source identity or rights metadata')
    row = {**selected, 'version': '3.0', 'FAIL_TO_PASS': json.dumps(selected['FAIL_TO_PASS']),
           'PASS_TO_PASS': json.dumps(selected['PASS_TO_PASS'])}
    private_directory(output.parent)
    # Keep the source's original malformed test ID. The separately versioned
    # public oracle expansion is checked and applied by RepositoryCase.load.
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as file:
        with original.open('rb') as base:
            for block in iter(lambda: base.read(1024 * 1024), b''):
                file.write(block)
        file.write((canonical(row) + '\n').encode())
    return {'case_id': selected['instance_id'], 'source_split': 'train',
            'evaluator_sha256': file_sha(output), 'reference_patch_printed': False,
            'provider_calls': 0, 'training_eligible': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--base-evaluator', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.base_evaluator, args.output), indent=2))
