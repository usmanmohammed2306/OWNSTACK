"""Install a locally reviewed Colab export, never arbitrary executable weights."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

def install(archive: Path, destination: Path):
    with zipfile.ZipFile(archive) as bundle:
        if sum(i.file_size for i in bundle.infolist())>80_000_000:raise ValueError('Oversized export')
        for item in bundle.infolist():
            path=Path(item.filename)
            if path.is_absolute() or '..' in path.parts or ((item.external_attr>>16)&0o170000)==0o120000:raise ValueError('Unsafe ZIP member')
            if path.parts[0] not in {'adapter','trainer','dataset.jsonl','manifest.json','baseline.json','evaluation.json'}:raise ValueError('Unexpected ZIP member')
            if path.suffix in {'.bin','.pt','.pth','.py','.sh'}:raise ValueError('Executable/pickle payload is not permitted')
        destination.mkdir(mode=0o700,parents=True,exist_ok=False)
        bundle.extractall(destination)
    info=json.loads((destination/'manifest.json').read_text())
    if hashlib.sha256((destination/'dataset.jsonl').read_bytes()).hexdigest()!=info['dataset_sha256']:raise ValueError('Dataset digest mismatch')
    files={str(p.relative_to(destination)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.rglob('*')) if p.is_file()}
    for p in destination.rglob('*'):
        if p.is_file():p.chmod(0o600)
    installation={'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':files}
    (destination/'installation.json').write_text(json.dumps(installation,indent=2));(destination/'installation.json').chmod(0o600)
    return {'path':str(destination),'manifest_sha256':files['manifest.json'],'baseline_exact':info['baseline_exact'],'trained_exact':info['trained_exact'],'test_total':info['test_total']}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('archive',type=Path);parser.add_argument('destination',type=Path);args=parser.parse_args()
    print(json.dumps(install(args.archive,args.destination),indent=2))
