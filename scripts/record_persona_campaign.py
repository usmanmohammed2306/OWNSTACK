"""Record actual evidence and explicit blocks. Never manufacture a 100k pass count."""
import argparse,json
from pathlib import Path
from ownstack.experiment_store import ExperimentStore,Result,export_sft,digest

def record(catalog,auth_report,output,failure_log=None):
    store=ExperimentStore(output)
    source=[json.loads(line) for line in catalog.read_text().splitlines()]
    auth=json.loads(auth_report.read_text())
    for name,path in [('catalog-source.jsonl',catalog),('auth-source.json',auth_report)]:
        import os
        fd=os.open(output/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as file:file.write(path.read_bytes())
    for row in auth['rows']:
        store.append(Result(case_id=row['persona_id'],persona_id=row['persona_id'],scope='authentication',
            status='passed' if row['passed'] else 'failed',source_group='ownstack-persona-auth',source_split='test',
            checks=row['checks'],reason=row.get('error','Existing saved-account checks; not a completed business need.'),
            evidence_file='auth-source.json',evidence_sha256=digest(auth_report.read_bytes())),
            'recorded-auth-'+row['persona_id'])
    for case in source:
        store.append(Result(case_id=case['id'],scope='upstream_issue',status='blocked',source_group=case['repo'],
            source_split='test',source_url=case['source_url'],case_sha256=case['problem_sha256'],oracle_sha256=case['required_tests_sha256'],
            reason='Preflight: OwnStack currently permits the owned sample file only. No external repository checkout, candidate or upstream required tests were run. This is not a failed upstream execution or a completed user journey.'),
            'source-block-'+case['id'])
    if failure_log:
        raw=failure_log.read_bytes()
        # Preserve the actual earlier failure as a harness failure, never as a
        # failed customer scenario or a fabricated negative training example.
        import os
        fd=os.open(output/'retained-harness-failure.log',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as file:file.write(raw)
        store.append(Result(case_id='persona-verification-harness-r1',scope='control',status='failed',
            source_group='ownstack-persona-auth',source_split='test',
            reason='The first harness queried a nonexistent WebSession.revoked field during its summary. See retained failure; corrected run is recorded separately.',
            evidence_file='retained-harness-failure.log',evidence_sha256=digest(raw)),event_id='retained-harness-r1')
    summary=store.summary()
    summary.update(requested_personas=100,requested_scenarios_per_persona=1000,requested_total=100000,
        sourced_distinct_cases=len(source),source_cases_assigned_to_personas=0,
        fabricated_or_multiplied_cases=0,full_business_journeys_completed=0,
        scope='Actual authentication evidence plus source-readiness blocks, not 100000 executions or resolutions.')
    (output/'campaign.json').write_text(json.dumps(summary,indent=2)+'\n')
    training=export_sft(store,output/'sft-readiness',heldout_ids={r['id'] for r in source},heldout_groups={r['repo'] for r in source})
    return {'campaign':summary,'training':training}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--catalog',type=Path,required=True)
    p.add_argument('--auth-report',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--failure-log',type=Path)
    a=p.parse_args();print(json.dumps(record(a.catalog,a.auth_report,a.output,a.failure_log),indent=2))
