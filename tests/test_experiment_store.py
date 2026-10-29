"""Evidence lifecycle, interruption survival and train/test separation."""
import json
import sqlite3
import pytest
from ownstack.experiment_store import ExperimentStore,Result,canonical,digest,export_sft,training_rejection

def control(**changes):
    return Result(case_id='one',scope='control',status='passed',source_group='owned-app',
        checks=[{'name':'a real finite check','passed':True}],**changes)

def verified(store,**changes):
    proof={'case_id':'issue-one','case_sha256':'a'*64,'candidate_sha256':'b'*64,'oracle_sha256':'c'*64,
        'required_tests':['regression','compatibility'],'observed_tests':{'regression':True,'compatibility':True},
        'baseline_failed':True,'candidate_passed':True}
    raw=canonical(proof).encode();(store.directory/'proof.json').write_bytes(raw)
    data={'case_id':'issue-one','scope':'upstream_issue','status':'passed','source_group':'owned-repo','source_split':'train',
        'checks':[{'name':'independent required tests','passed':True}],'candidate_origin':'model','case_sha256':'a'*64,
        'candidate_sha256':'b'*64,'oracle_sha256':'c'*64,'evidence_file':'proof.json','evidence_sha256':digest(raw),
        'human_reviewed':True,'prompt':'A bounded issue','completion':'The exact candidate'}
    return Result(**{**data,**changes})

def test_completed_failures_blocks_and_interrupted_running_work_are_preserved(tmp_path):
    s=ExperimentStore(tmp_path/'results');s.append(control(),'stable')
    s.append(Result(case_id='failure',scope='control',status='failed',source_group='owned',reason='Observed failure'))
    s.append(Result(case_id='blocked',scope='upstream_issue',status='blocked',source_group='other',reason='No adapter'))
    s.append(Result(case_id='interrupted',scope='upstream_issue',status='running',source_group='other'))
    reopened=ExperimentStore(tmp_path/'results');summary=reopened.summary()
    assert summary['states']=={'passed':1,'failed':1,'blocked':1,'running':1}
    assert summary['verified_business_outcomes']==0 and summary['running_is_not_passed']
    assert reopened.append(control(),'stable')=='stable' and len(reopened.records())==4
    with pytest.raises(ValueError,match='identity reused'):reopened.append(control(reason='Changed intent'),'stable')

def test_unproven_pass_secret_fields_and_nonboolean_checks_are_rejected():
    with pytest.raises(ValueError):Result(case_id='bad',scope='persona_business',status='passed',source_group='repo')
    with pytest.raises(ValueError):Result(case_id='bad',scope='control',status='passed',source_group='repo',checks=[{'name':'x','passed':'true'}])
    with pytest.raises(ValueError):Result(case_id='bad',scope='control',status='failed',source_group='repo',password='never-record-this')

def test_exact_required_test_and_candidate_evidence_are_necessary(tmp_path):
    s=ExperimentStore(tmp_path/'results');r=verified(s);s.append(r)
    assert s.summary()['verified_business_outcomes']==1
    with pytest.raises(ValueError,match='match candidate'):s.append(r.model_copy(update={'candidate_sha256':'d'*64}))
    proof=json.loads((s.directory/'proof.json').read_text());proof['observed_tests']['compatibility']=False
    raw=canonical(proof).encode();(s.directory/'proof.json').write_bytes(raw)
    with pytest.raises(ValueError,match='required tests'):s.append(r.model_copy(update={'evidence_sha256':digest(raw)}))

def test_reference_answers_authentication_and_test_cases_never_become_training_success(tmp_path):
    s=ExperimentStore(tmp_path/'results');r=verified(s)
    assert training_rejection(r,{'issue-one'},set())=='held_out_or_unassigned'
    assert training_rejection(r,set(),{'owned-repo'})=='held_out_or_unassigned'
    assert training_rejection(r.model_copy(update={'source_split':'test'}),set(),set())=='held_out_or_unassigned'
    assert training_rejection(r.model_copy(update={'candidate_origin':'reference'}),set(),set())=='reference_answer_or_contamination'
    assert training_rejection(control(source_split='train'),set(),set())=='not_a_business_trajectory'
    s.append(r.model_copy(update={'source_split':'test'}))
    report=export_sft(s,tmp_path/'training',{'issue-one'},{'owned-repo'})
    assert report['eligible_examples']==0 and not report['training_ready'] and not report['training_run']
    assert (tmp_path/'training/sft.jsonl').read_text()==''

def test_reviewer_gate_and_training_export_deduplicate_without_exposing_run_metadata(tmp_path):
    s=ExperimentStore(tmp_path/'results');r=verified(s);s.append(r)
    assert training_rejection(r.model_copy(update={'human_reviewed':False}),set(),set())=='human_review_missing'
    output=tmp_path/'sft';manifest=export_sft(s,output,set(),set())
    assert manifest['eligible_examples']==1 and not manifest['training_run']
    row=json.loads((output/'sft.jsonl').read_text());assert set(row)=={'prompt','completion','case_id','source_group','candidate_sha256'}
    with pytest.raises(FileExistsError):export_sft(s,output,set(),set())

def test_result_tampering_is_detected_but_hashes_are_not_attestation(tmp_path):
    s=ExperimentStore(tmp_path/'results');s.append(control())
    with sqlite3.connect(s.path) as db:db.execute("UPDATE events SET payload='{}'")
    with pytest.raises(ValueError,match='integrity'):s.records()

def test_training_rechecks_evidence_bytes_and_rejects_path_escape(tmp_path):
    s=ExperimentStore(tmp_path/'results');r=verified(s)
    with pytest.raises(ValueError,match='owned'):s.append(r.model_copy(update={'evidence_file':'../private.json'}))
    s.append(r);(s.directory/'proof.json').write_text('{}')
    with pytest.raises(ValueError,match='bytes changed'):export_sft(s,tmp_path/'unsafe-export',set(),set())
