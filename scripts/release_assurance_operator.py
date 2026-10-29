"""Local CI/operator bridge for the fixed release visibility adapter.

Hashes source snapshots, executes queued checks outside the API, and writes a
review artifact. No GitHub write, arbitrary command, inference or deployment.
"""
import argparse
import json
import os
from pathlib import Path
import time


def database(value):
    from sqlalchemy.engine import make_url
    url=make_url(value)
    if url.get_backend_name()!='sqlite' or not url.database:
        raise ValueError('Explicit disposable local SQLite lab database required')
    original=Path(url.database).absolute()
    if any(p.is_symlink() for p in (original,*original.parents)):
        raise ValueError('Symlink database paths are forbidden')
    path=original.resolve(strict=True)
    root=Path(__file__).resolve().parents[1]
    private=root/'.private/release-assurance-20261027'
    reusable=root/'.private/release-labs'
    marked=False
    if path.is_relative_to(reusable) and path.parent.parent==reusable and path.name=='ownstack.sqlite':
        marker=path.parent/'lab.json'
        marked=(marker.is_file() and not marker.is_symlink() and json.loads(marker.read_text())=={
            'schema_version':1,'purpose':'ownstack-offline-release-lab','database':'ownstack.sqlite'})
        if marked:
            import sqlite3
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
                marked=db.execute("SELECT reserved_calls FROM inference_budget WHERE id='global'").fetchone()==(0,)
    if (not path.is_relative_to(private) and not marked) or path.name.endswith(('-wal','-shm')) or path.is_symlink():
        raise ValueError('Only this task release-assurance lab DB is permitted')
    return str(url.set(database=str(path)))


def run_once(factory,repositories,output,image):
    from ownstack.release_assurance import claim_next,finish_check,review_markdown,expire_checks
    from ownstack.release_executor import run_release,PROFILE,POLICY,RUNNER,HTTP_CLIENT,READY_CLIENT,execution_fingerprint
    from ownstack.models import ReleaseCheck
    import hashlib
    expire_checks(factory)
    item=claim_next(factory)
    if item is None:return False
    target=output/item['id']
    try:
        baseline=repositories[item['baseline_sha256']];candidate=repositories[item['candidate_sha256']]
        result=run_release(baseline,candidate,item['requirements'],target,image=image,
            expected_baseline_sha256=item['baseline_sha256'],expected_candidate_sha256=item['candidate_sha256'])
    except Exception as error:
        # No guessed success or fake observed result. A blocked report retains
        # identity and may be inspected; independent acceptance cannot use it.
        result={'runner':RUNNER,'profile':PROFILE,'policy':POLICY,'image_id':image,
            'execution_policy_sha256':execution_fingerprint(),
            'oracle_sha256':hashlib.sha256((HTTP_CLIENT+READY_CLIENT).encode()).hexdigest(),
            'baseline_sha256':item['baseline_sha256'],'candidate_sha256':item['candidate_sha256'],
            'requirements_sha256':item['requirements_sha256'],'provider_calls':0,'released':False,
            'baseline':{'state':'blocked','failure':type(error).__name__,'observations':[],'cleanup_verified':False},
            'candidate':{'state':'blocked','failure':'Not executed','observations':[],'cleanup_verified':False},
            'passed':False,'status':'blocked','baseline_valid':False,'candidate_valid':False,'assessments':[],
            'reason':'Incomplete, duplicate, failed or mismatched HTTP observation set'}
    saved=finish_check(factory,item['id'],item['claim_token'],result)
    output.mkdir(mode=0o700,parents=True,exist_ok=True)
    from ownstack.repository_executor import private_json
    private_json(output/(item['id']+'-operator.json'),{'id':item['id'],'result_saved':saved,'report':result})
    if saved:
        with factory() as db:
            review=review_markdown(db.get(ReleaseCheck,item['id']))
        path=output/(item['id']+'-review.md')
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(review);stream.flush();os.fsync(stream.fileno())
    print(json.dumps({'check_id':item['id'],'result_saved':saved,'provider_calls':0}),flush=True)
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    snapshot=sub.add_parser('snapshot');snapshot.add_argument('source',type=Path)
    worker=sub.add_parser('work');worker.add_argument('--database-url',required=True)
    worker.add_argument('--source',type=Path,action='append',required=True)
    worker.add_argument('--image',required=True);worker.add_argument('--output',type=Path,required=True)
    worker.add_argument('--watch-seconds',type=int,default=0)
    args=parser.parse_args()
    from ownstack.release_executor import snapshot_repository
    if args.command=='snapshot':
        print(json.dumps(snapshot_repository(args.source)));return
    if (os.environ.get('OWNSTACK_AI_MODE')!='off' or os.environ.get('OWNSTACK_MAX_LIVE_CALLS')!='0'
            or any(os.environ.get(k) for k in ('NEBIUS_API_KEY','NEBIUS_MODEL_ID','NEBIUS_PATCH_MODEL_ID'))):
        raise ValueError('Explicit AI-off/cap-zero/empty provider settings required')
    if not 0<=args.watch_seconds<=600:raise ValueError('Watch duration must be bounded to ten minutes')
    url=database(args.database_url)
    output=args.output.resolve()
    root=Path(__file__).resolve().parents[1]
    anchor=root/'.private/release-assurance-20261027'
    reusable=root/'.private/release-labs'
    if not output.is_relative_to(anchor) and not output.is_relative_to(reusable):raise ValueError('Private offline lab output required')
    os.environ['OWNSTACK_DATABASE_URL']=url
    from sqlalchemy.orm import sessionmaker
    from ownstack.db import make_engine
    engine=make_engine(url);factory=sessionmaker(bind=engine,expire_on_commit=False)
    repositories={snapshot_repository(path)['sha256']:path for path in args.source}
    end=time.monotonic()+args.watch_seconds
    try:
        while True:
            worked=run_once(factory,repositories,output,args.image)
            if not args.watch_seconds or time.monotonic()>=end:break
            if not worked:time.sleep(.3)
    finally:engine.dispose()


if __name__=='__main__':main()
