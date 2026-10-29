"""CI classifications must agree with independent control-plane assessment."""
import importlib.util
from pathlib import Path

from test_release_journeys import approved_requirement,queue_check,release_enabled,explicit_result_double  # noqa:F401
from ownstack.release_assurance import claim_next
from ownstack.release_executor import assess_observations
from ownstack.release_contracts import RequirementSpec

spec=importlib.util.spec_from_file_location('customer_ci',Path(__file__).resolve().parents[1]/'scripts/check_customer_release.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_candidate_environment_failure_is_blocked_not_a_baseline_regression(client,fixture_db,release_enabled):
    req,engineer,_=approved_requirement(client);queue_check(client,req,engineer)
    claim=claim_next(fixture_db);report=explicit_result_double(claim)
    report['candidate'].update(state='blocked',failure='Controlled unavailable adapter',observations=[])
    report.update(assess_observations(claim['requirements'],report['baseline'],report['candidate']))
    assert module.result_state(report,[RequirementSpec.model_validate(s) for s in claim['requirements']])=='blocked'


def test_completed_invalid_baseline_has_distinct_ci_state(client,fixture_db,release_enabled):
    req,engineer,_=approved_requirement(client);queue_check(client,req,engineer)
    claim=claim_next(fixture_db);report=explicit_result_double(claim,candidate_ok=False)
    report['baseline']=report['candidate'];report.update(assess_observations(claim['requirements'],report['baseline'],report['candidate']))
    assert module.result_state(report,[RequirementSpec.model_validate(s) for s in claim['requirements']])=='baseline_failed'
