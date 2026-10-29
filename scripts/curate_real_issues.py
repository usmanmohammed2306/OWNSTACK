"""Curate distinct published issue/PR tasks, without generating fictional cases.

Use a pinned SWE-bench parquet file. Raw issues, tests and reference solutions
remain private. The public catalog contains provenance and test expectations,
never a claim that OwnStack resolved the issue or that a persona experienced it.
Requires the optional research dependency pyarrow, not the production runtime.
"""
import argparse
from collections import Counter,defaultdict,deque
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
SOURCE_SHA='db4f70ef735b3162c74801ddcdf8d7bae8d704193788c6d844f898c20b571cbb'
REVISION='e48e2bd1e9fecd5bbd641e9414ac59da9f2e69f6'

def sha(value):return hashlib.sha256(value if isinstance(value,bytes) else value.encode()).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'))

def select_cases(rows,limit):
    """Balance repositories, deduplicate independently recorded problems/oracles.

    These filters do not certify semantic uniqueness; related bugs can remain.
    """
    buckets=defaultdict(list);excluded=Counter();seen_problem=set();seen_patch=set();seen_test=set()
    for row in sorted(rows,key=lambda r:r['instance_id']):
        problem=' '.join(re.findall(r'\w+',row['problem_statement'].casefold()))
        try:failed=json.loads(row['FAIL_TO_PASS']);retained=json.loads(row['PASS_TO_PASS'])
        except (ValueError,TypeError):excluded['invalid_test_specification']+=1;continue
        if len(row['problem_statement'])<200 or not failed or not row['patch'] or not row['test_patch']:
            excluded['insufficient_problem_or_oracle']+=1;continue
        if not isinstance(failed,list) or not isinstance(retained,list):raise ValueError('Invalid upstream tests')
        keys=(sha(problem),sha(row['patch']),sha(row['test_patch']))
        if keys[0] in seen_problem or keys[1] in seen_patch or keys[2] in seen_test:
            excluded['duplicate_problem_patch_or_test']+=1;continue
        seen_problem.add(keys[0]);seen_patch.add(keys[1]);seen_test.add(keys[2]);buckets[row['repo']].append(row)
    pools={repo:deque(items) for repo,items in sorted(buckets.items())};chosen=[]
    while len(chosen)<limit and any(pools.values()):
        for pool in pools.values():
            if pool and len(chosen)<limit:chosen.append(pool.popleft())
    if len(chosen)!=limit:raise ValueError(f'Only {len(chosen)} eligible distinct source records; do not pad the target')
    return chosen,dict(excluded),sum(len(v) for v in buckets.values())

def catalog_record(row):
    # SWE-bench instance suffixes are PR numbers, NOT original issue numbers.
    number=row['instance_id'].rsplit('-',1)[1]
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+',row['repo']) or not number.isdecimal():raise ValueError('Unexpected source identity')
    if not re.fullmatch('[a-f0-9]{40}',row['base_commit']):raise ValueError('Unpinned source revision')
    failed=json.loads(row['FAIL_TO_PASS']);retained=json.loads(row['PASS_TO_PASS'])
    title=' '.join(row['problem_statement'].strip().splitlines()[0].split())
    title=' '.join(title.split()[:20])[:180]
    tests={'fail_to_pass':failed,'pass_to_pass':retained,'test_patch_sha256':sha(row['test_patch'])}
    return {'id':row['instance_id'],'repo':row['repo'],'title':title,
        'source_url':f"https://github.com/{row['repo']}/pull/{number}",
        'source_url_kind':'published_pull_request_associated_with_issue',
        'base_commit':row['base_commit'],'created_at':row['created_at'],
        'problem_sha256':sha(row['problem_statement']),'problem_bytes':len(row['problem_statement'].encode()),
        'reference_patch_sha256':sha(row['patch']),'test_patch_sha256':sha(row['test_patch']),
        'required_tests_sha256':sha(canonical(tests)),
        'fail_to_pass_count':len(failed),'pass_to_pass_count':len(retained),
        'full_issue_resolution':'not_executed','persona_fit':'not_reviewed',
        'ownstack_support':'external_repository_adapter_not_connected'}

def curate(source,public,private,limit=1000):
    if sha(source.read_bytes())!=SOURCE_SHA:raise ValueError('Source bytes differ from the pinned dataset')
    import pyarrow.parquet as parquet
    if public.exists() or private.exists():raise FileExistsError('Preserve existing catalogs and evaluator data')
    rows=parquet.read_table(source).to_pylist();chosen,excluded,eligible=select_cases(rows,limit)
    public.mkdir(parents=True);private.mkdir(mode=0o700,parents=False)
    records=[catalog_record(row) for row in chosen]
    raw=''.join(canonical(row)+'\n' for row in records)
    (public/'cases.jsonl').write_text(raw)
    # Gold answers never enter a proposal, prompt or ordinary user response.
    import os
    fd=os.open(private/'evaluator-only.jsonl',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as file:
        for row in chosen:file.write(canonical(row)+'\n')
    manifest={'dataset':'princeton-nlp/SWE-bench','dataset_revision':REVISION,'source_parquet_sha256':SOURCE_SHA,
        'source_url':f'https://huggingface.co/datasets/princeton-nlp/SWE-bench/tree/{REVISION}',
        'catalog_sha256':sha(raw),'source_records':len(rows),'eligible_distinct_records':eligible,'curated':len(records),
        'repositories':dict(Counter(row['repo'] for row in records)),'excluded':excluded,
        'unique_source_urls':len({r['source_url'] for r in records}),
        'unique_problem_hashes':len({r['problem_sha256'] for r in records}),
        'target_total':100000,'source_shortfall_to_target':max(0,100000-len(records)),
        'completed_business_journeys':0,'generated_or_multiplied_cases':0,
        'semantic_independence_certified':False,'persona_assignments':0,
        'scope':'Published distinct issue/PR records, not OwnStack customers; no issue is counted as fixed by importing it.'}
    (public/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--public',type=Path,default=ROOT/'evals/real_issues_v1')
    p.add_argument('--private',type=Path,required=True);p.add_argument('--limit',type=int,default=1000)
    p.add_argument('--download',action='store_true',help='Download only the pinned public source into a new private file')
    a=p.parse_args()
    if a.download:
        if not a.source.absolute().resolve().is_relative_to((ROOT/'.private').resolve()):raise SystemExit('Download evaluator source only under .private')
        if a.source.exists():raise FileExistsError('Preserve the existing source file')
        import os,httpx
        url=f'https://huggingface.co/datasets/princeton-nlp/SWE-bench/resolve/{REVISION}/data/test-00000-of-00001.parquet'
        partial=a.source.with_suffix(a.source.suffix+'.partial')
        fd=os.open(partial,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);total=0;checksum=hashlib.sha256()
        with os.fdopen(fd,'wb') as file,httpx.Client(timeout=90,trust_env=False,follow_redirects=True) as client:
            with client.stream('GET',url) as response:
                response.raise_for_status()
                for block in response.iter_bytes():
                    total+=len(block)
                    if total>64*1024*1024:raise ValueError('Source exceeded bounded download size; partial retained')
                    checksum.update(block);file.write(block)
        if checksum.hexdigest()!=SOURCE_SHA:raise ValueError('Source hash mismatch; partial retained')
        partial.rename(a.source)
    print(json.dumps(curate(a.source,a.public,a.private,a.limit),indent=2))

if __name__=='__main__':main()
