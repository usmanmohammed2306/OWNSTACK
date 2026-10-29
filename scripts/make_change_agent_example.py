"""Create fresh owned source fixtures without modifying the example or a repository."""
import argparse,json
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    target=args.output.absolute()
    if any(p.is_symlink() for p in (target,*target.parents)):raise ValueError('No symlink output')
    target.mkdir(mode=0o700,parents=True,exist_ok=False)
    source=Path(__file__).resolve().parents[1]/'examples/counterexample_workspace'
    from ownstack.release_repository import load,MANIFEST
    from ownstack.counterexample_loop import apply_patch
    snapshot,files=load(source);base=target/'baseline';base.mkdir(mode=0o700)
    for name,data in files.items():(base/name).write_bytes(data)
    (base/MANIFEST).write_text(json.dumps(snapshot['config'],indent=2)+'\n')
    apply_patch(base,target/'candidate',json.loads((source/'regression.json').read_text()),{'customer_policy.py'})
    print(json.dumps({'created':True,'baseline':str(base),'candidate':str(target/'candidate'),
        'repair_responses':str(source/'repair-responses.json'),'provider_calls':0,'synthetic':True}))

if __name__=='__main__':main()
