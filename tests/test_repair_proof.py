"""Repair histories belong in the same tenant-private proof snapshot."""
from copy import deepcopy
import pytest
from ownstack.policy import digest
from ownstack.proof import export_proof, saved_state_fingerprint, verify_envelope
from ownstack.repair import run_repair_one
from ownstack.repair_models import RepairRun
from test_repair import start, proposal, oracle
from conftest import login


def test_export_retains_failed_and_passed_candidates_with_workflow_fences(client, fixture_db):
    run_id = start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    run_repair_one(fixture_db, verify=lambda patch: oracle(patch, False))
    run_repair_one(fixture_db, propose=proposal)
    run_repair_one(fixture_db, verify=oracle)
    with fixture_db() as db:
        run = db.get(RepairRun, run_id)
        run.configuration = {**run.configuration, "api_key": "private-never-export", "prompt": "hidden-configuration"}
        db.commit()
    response = client.get('/v1/requests/repair-request/proof', headers=login(client, 'atlas-engineer'))
    assert response.status_code == 200
    envelope = response.json()
    assert verify_envelope(envelope)
    run = envelope['payload']['repair_runs'][0]
    assert run['id'] == run_id and run['state'] == 'awaiting_review'
    assert [attempt['state'] for attempt in run['attempts']] == ['failed', 'passed']
    assert all(attempt['candidate'] and attempt['checks'] for attempt in run['attempts'])
    assert run['original_patch_hash'] == digest(run['original_patch'])
    assert run['configuration']['workflow_hash'] and run['configuration']['langgraph_version']
    assert run['release_state'] == 'not_deployed'
    assert len([event for event in envelope['payload']['events'] if event['event_type']=='repair.workflow_phase']) == 4
    assert 'private-never-export' not in response.text and 'hidden-configuration' not in response.text
    assert client.get('/v1/requests/repair-request/proof', headers=login(client, 'nova-admin')).status_code == 404
    assert client.get('/v1/requests/repair-request/proof', headers=login(client, 'atlas-contractor')).status_code == 403


def test_restart_fingerprint_includes_repair_history_but_not_export_clock(fixture_db):
    start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    envelope = export_proof(fixture_db.kw['bind'], 'repair-request', 'atlas')
    original = saved_state_fingerprint(envelope)
    changed = deepcopy(envelope)
    changed['payload']['exported_at'] = 'later'
    changed['payload']['source_hashes_at_export'] = {'new-build': 'new-source'}
    changed['sha256'] = digest(changed['payload'])
    assert saved_state_fingerprint(changed) == original
    changed['payload']['repair_runs'][0]['attempts'][0]['candidate_hash'] = 'changed'
    with pytest.raises(ValueError):
        saved_state_fingerprint(changed)
    changed['sha256'] = digest(changed['payload'])
    assert saved_state_fingerprint(changed) != original


def test_older_v1_proof_without_repair_field_remains_verifiable(fixture_db):
    start(fixture_db)
    envelope = export_proof(fixture_db.kw['bind'], 'repair-request', 'atlas')
    envelope['payload'].pop('repair_runs')
    envelope['sha256'] = digest(envelope['payload'])
    assert verify_envelope(envelope) and saved_state_fingerprint(envelope)
