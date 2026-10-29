"""Independent safety regressions with explicit results doubles, no Docker.

These are control-plane authorization/evidence tests, not customer interviews or
actual repository execution results. Actual HTTP adapter runs are saved separately.
"""
import importlib.util
from pathlib import Path

import pytest

from test_release_journeys import (approved_requirement,explicit_result_double,queue_check,
                                  release_enabled)  # noqa: F401


def checked(client,factory):
    from ownstack.release_assurance import claim_next,finish_check
    requirement,engineer,admin=approved_requirement(client)
    queued,_=queue_check(client,requirement,engineer)
    claim=claim_next(factory)
    assert finish_check(factory,queued['id'],claim['claim_token'],explicit_result_double(claim))
    saved=client.get('/v1/release/checks/'+queued['id'],headers=engineer).json()
    assert saved['state']=='passed'
    return saved,engineer


def test_policy_change_after_pass_requires_fresh_checks_before_human_acceptance(client,fixture_db,release_enabled,monkeypatch):
    saved,engineer=checked(client,fixture_db)
    def changed(*args,**kwargs):
        raise ValueError('Execution policy changed after this saved check')
    monkeypatch.setattr('ownstack.release_executor.validate_report',changed)
    response=client.post('/v1/release/checks/'+saved['id']+'/decide',headers=engineer,
        json={'expected_revision':saved['revision'],'evidence_hash':saved['evidence_hash'],
              'decision':'accept_for_manual_release'})
    assert response.status_code==409,response.text
    current=client.get('/v1/release/checks/'+saved['id'],headers=engineer).json()
    assert current['decision'] is None


@pytest.mark.parametrize('field,value',[('expected','malformed'),('observed_baseline',[]),('observed_candidate',None)])
def test_blocked_malformed_nested_report_is_still_inspectable(client,fixture_db,release_enabled,field,value):
    from ownstack.release_assurance import claim_next,finish_check
    requirement,engineer,_=approved_requirement(client)
    queued,_=queue_check(client,requirement,engineer)
    claim=claim_next(fixture_db);report=explicit_result_double(claim)
    report['assessments'][0][field]=value
    assert finish_check(fixture_db,queued['id'],claim['claim_token'],report)
    saved=client.get('/v1/release/checks/'+queued['id'],headers=engineer).json()
    assert saved['state']=='blocked'
    review=client.get('/v1/release/checks/'+queued['id']+'/review',headers=engineer)
    assert review.status_code==200
    assert 'blocked' in review.text and 'Nothing was deployed' in review.text


def test_operator_rejects_symlink_database_before_engine_creation(tmp_path):
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('release_operator_security',root/'scripts/release_assurance_operator.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    # Rebind script location so the test never creates files in the real lab.
    module.__file__=str(tmp_path/'scripts/release_assurance_operator.py')
    anchor=tmp_path/'.private/release-assurance-20261027';anchor.mkdir(parents=True)
    target=anchor/'fixture.sqlite';target.touch()
    link=anchor/'alias.sqlite';link.symlink_to(target)
    with pytest.raises(ValueError):module.database('sqlite:///'+str(link))
