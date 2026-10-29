"""Real-source provenance and noninflation, not upstream issue resolutions."""
import importlib.util
import json
from pathlib import Path
import re
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('curator',ROOT/'scripts/curate_real_issues.py')
curator=importlib.util.module_from_spec(spec);spec.loader.exec_module(curator)

def item(i=1,**changes):
    row={'instance_id':f'owner__repository-{i}','repo':'owner/repository','base_commit':'a'*40,
        'problem_statement':('Distinct regression '+str(i)+' ')*20,'patch':'source patch '+str(i),
        'test_patch':'oracle patch '+str(i),'FAIL_TO_PASS':'["regression"]','PASS_TO_PASS':'["compatibility"]','created_at':'2020-01-01T00:00:00Z'}
    return {**row,**changes}

def test_frozen_catalog_has_thousand_distinct_public_source_links_and_no_false_resolution():
    path=ROOT/'evals/real_issues_v1';manifest=json.loads((path/'manifest.json').read_text())
    raw=(path/'cases.jsonl').read_text();rows=[json.loads(line) for line in raw.splitlines()]
    assert curator.sha(raw)==manifest['catalog_sha256'] and len(rows)==1000
    for field in ['id','source_url','problem_sha256','reference_patch_sha256','test_patch_sha256']:
        assert len({r[field] for r in rows})==1000
    assert len({r['repo'] for r in rows})==12
    assert all('/pull/' in r['source_url'] and r['fail_to_pass_count']>0 and re.fullmatch('[a-f0-9]{40}',r['base_commit']) for r in rows)
    assert all(r['full_issue_resolution']=='not_executed' and r['persona_fit']=='not_reviewed' for r in rows)
    assert manifest['completed_business_journeys']==manifest['generated_or_multiplied_cases']==0
    assert manifest['target_total']==100000

def test_number_suffix_is_correctly_a_pull_reference_not_an_invented_issue_link():
    r=curator.catalog_record(item(123))
    assert r['source_url']=='https://github.com/owner/repository/pull/123'
    assert r['full_issue_resolution']=='not_executed'

def test_cosmetic_text_and_duplicate_oracle_records_do_not_pad_selection():
    rows=[item(1),item(2,problem_statement=item(1)['problem_statement'].upper()),item(3,test_patch=item(1)['test_patch']),item(4)]
    selected,excluded,eligible=curator.select_cases(rows,2)
    assert [r['instance_id'] for r in selected]==['owner__repository-1','owner__repository-4']
    assert excluded['duplicate_problem_patch_or_test']==2 and eligible==2
    with pytest.raises(ValueError,match='do not pad'):curator.select_cases(rows,3)

def test_missing_failure_oracle_and_short_story_are_not_treated_as_complex_testable_cases():
    rows=[item(1,FAIL_TO_PASS='[]'),item(2,problem_statement='short'),item(3)]
    chosen,excluded,_=curator.select_cases(rows,1)
    assert chosen[0]['instance_id']=='owner__repository-3' and excluded['insufficient_problem_or_oracle']==2

def test_unpinned_source_is_rejected_before_a_parser_or_network_is_used(tmp_path):
    source=tmp_path/'wrong.parquet';source.write_bytes(b'wrong source')
    with pytest.raises(ValueError,match='pinned'):curator.curate(source,tmp_path/'public',tmp_path/'private')
