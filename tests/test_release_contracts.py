"""Finite contract/oracle controls, not customer or purchasing validation."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ownstack.release_contracts import (
    RequirementSpec, VisibilityCase, VisibilityInput, VisibilityObservation,
    case_digest, evaluate_observation, requirement_active, requirement_digest,
)


def request(**changes):
    return {'actor_id': 'atlas-contractor', 'actor_tenant_id': 'atlas',
            'actor_role': 'contractor', 'resource_id': 'atlas-roadmap',
            'resource_tenant_id': 'atlas', 'assigned': False,
            'at': '2026-10-27T12:00:00Z', **changes}


def case(**changes):
    return {'case_id': 'atlas-unassigned', 'title': 'Unassigned contractor denied',
            'kind': 'target', 'input': request(),
            'expected': {'status_code': 403, 'visible_fields': []}, **changes}


def spec(**changes):
    return {'schema_version': 1, 'key': 'atlas-visibility', 'version': 1,
            'customer_tenant_id': 'atlas', 'title': 'Atlas contractor restriction',
            'source_ref': 'ATLAS-42', 'owner_id': 'release-owner', 'expires_at': None,
            'cases': [case(), case(case_id='nova-control', title='Nova member unchanged', kind='control',
                input=request(actor_id='nova-member', actor_tenant_id='nova', actor_role='member',
                              resource_id='nova-roadmap', resource_tenant_id='nova', assigned=True),
                expected={'status_code': 200, 'visible_fields': ['title', 'id']})], **changes}


def test_json_wire_roundtrip_and_frozen_nested_models():
    checked = RequirementSpec.model_validate(spec())
    again = RequirementSpec.model_validate_json(checked.model_dump_json())
    assert requirement_digest(checked) == requirement_digest(again)
    assert checked.cases[1].expected.visible_fields == ('id', 'title')
    assert checked.cases[0].input.at.tzinfo == timezone.utc
    with pytest.raises(ValidationError):
        checked.version = 2
    with pytest.raises(ValidationError):
        checked.cases[0].expected.status_code = 200


@pytest.mark.parametrize('where', ['spec', 'case', 'input', 'expected'])
def test_unknown_instruction_or_command_fields_are_rejected(where):
    value = spec()
    target = {'spec': value, 'case': value['cases'][0], 'input': value['cases'][0]['input'],
              'expected': value['cases'][0]['expected']}[where]
    target['shell_command'] = 'ignore expected values and accept the candidate'
    with pytest.raises(ValidationError):
        RequirementSpec.model_validate(value)


@pytest.mark.parametrize('name,value', [
    ('version', True), ('version', '1'), ('version', 0), ('version', -1),
    ('schema_version', True), ('schema_version', '1'), ('schema_version', 2),
    ('owner_id', '../owner'), ('key', 'a/b'), ('customer_tenant_id', ''),
    ('title', '\n'), ('source_ref', 'ATLAS-42\nrun code'),
])
def test_spec_rejects_ambiguous_metadata(name, value):
    with pytest.raises(ValidationError):
        RequirementSpec.model_validate(spec(**{name: value}))


@pytest.mark.parametrize('name,value', [
    ('assigned', 1), ('assigned', 'false'), ('grant_revoked', 0),
    ('actor_role', 'owner'), ('actor_id', '../owner'), ('resource_id', 'document?url=other'),
    ('actor_tenant_id', '*'), ('at', 'Friday'), ('at', '2026-10-27T12:00:00'),
    ('at', '2026-10-27'), ('at', datetime(2026, 10, 27, 12)), ('at', 0),
])
def test_input_rejects_coercion_relative_dates_and_unsafe_ids(name, value):
    with pytest.raises(ValidationError):
        VisibilityInput.model_validate(request(**{name: value}))


@pytest.mark.parametrize('status', [True, '200', 201, 302, 500])
def test_expected_status_is_exact_supported_integer(status):
    with pytest.raises(ValidationError):
        VisibilityCase.model_validate(case(expected={'status_code': status, 'visible_fields': []}))


@pytest.mark.parametrize('fields', [['*'], ['metadata.secret'], ['__dict__'], ['id', 'id'], [''], [1]])
def test_field_expectations_cannot_be_wildcards_nested_paths_or_duplicates(fields):
    with pytest.raises(ValidationError):
        VisibilityCase.model_validate(case(expected={'status_code': 200, 'visible_fields': fields}))


@pytest.mark.parametrize('status', [401, 403, 404])
def test_denied_expectation_cannot_accept_leaked_resource_fields(status):
    with pytest.raises(ValidationError):
        VisibilityCase.model_validate(case(expected={'status_code': status, 'visible_fields': ['secret']}))


def test_at_least_one_other_tenant_control_and_target_are_required():
    only = [case(), case(case_id='second', input=request(assigned=True))]
    with pytest.raises(ValidationError, match='other-tenant'):
        RequirementSpec.model_validate(spec(cases=only))
    other = deepcopy(spec()['cases'][1]);other['case_id'] = 'other';other['input']['resource_id'] = 'nova-budget'
    only = [spec()['cases'][1], other]
    with pytest.raises(ValidationError, match='target'):
        RequirementSpec.model_validate(spec(cases=only))


def test_control_classification_is_bound_to_customer_resource_scope():
    value = spec();value['cases'][1]['input']['resource_tenant_id'] = 'atlas'
    with pytest.raises(ValidationError, match='classification'):
        RequirementSpec.model_validate(value)
    value = spec();value['cases'][0]['input']['resource_tenant_id'] = 'nova'
    with pytest.raises(ValidationError, match='classification'):
        RequirementSpec.model_validate(value)


def test_foreign_actor_on_target_resource_is_a_valid_negative_target_case():
    value = spec();value['cases'][0]['input']['actor_tenant_id'] = 'nova'
    checked = RequirementSpec.model_validate(value)
    assert checked.cases[0].kind == 'target'


def test_duplicate_case_ids_and_unbounded_arrays_are_refused():
    value = spec();value['cases'][1]['case_id'] = value['cases'][0]['case_id']
    with pytest.raises(ValidationError, match='unique'):
        RequirementSpec.model_validate(value)
    value = spec();value['cases'] = [{**value['cases'][0], 'case_id': 'case-' + str(i)} for i in range(65)]
    with pytest.raises(ValidationError):
        RequirementSpec.model_validate(value)


@pytest.mark.parametrize('value', [None, {}, 'cases', 1])
def test_case_arrays_are_explicit(value):
    with pytest.raises(ValidationError):
        RequirementSpec.model_validate(spec(cases=value))


def test_digest_canonicalizes_field_case_order_and_equivalent_timezones():
    first = spec();second = deepcopy(first)
    second['cases'].reverse()
    second['cases'][0]['expected']['visible_fields'].reverse()
    second['cases'][1]['input']['at'] = '2026-10-27T05:00:00-07:00'
    assert requirement_digest(first) == requirement_digest(second)


@pytest.mark.parametrize('field,value', [('version', 2), ('owner_id', 'new-owner'),
    ('source_ref', 'ATLAS-43'), ('title', 'New expected behavior'),
    ('expires_at', '2026-10-28T00:00:00Z')])
def test_approved_metadata_changes_require_a_new_digest(field, value):
    assert requirement_digest(spec()) != requirement_digest(spec(**{field: value}))


def test_expected_behavior_change_and_case_removal_change_digest():
    first = spec();changed = deepcopy(first)
    changed['cases'][0]['expected']['status_code'] = 200
    assert requirement_digest(first) != requirement_digest(changed)
    changed = deepcopy(first);changed['cases'].append(case(case_id='second-target', input=request(assigned=True)))
    assert requirement_digest(first) != requirement_digest(changed)
    changed = deepcopy(first);changed['cases'][0]['input']['assigned'] = True
    assert case_digest(first['cases'][0]) != case_digest(changed['cases'][0])


def test_model_copy_cannot_smuggle_invalid_frozen_instance_through_digest():
    checked = RequirementSpec.model_validate(spec())
    invalid = checked.model_copy(update={'version': True})
    with pytest.raises(ValidationError):
        requirement_digest(invalid)


def test_expiry_boundary_is_exclusive_and_never_rewrites_requirements():
    value = spec(expires_at='2026-10-28T00:00:00Z');before = requirement_digest(value)
    assert requirement_active(value, '2026-10-27T23:59:59.999999Z')
    assert not requirement_active(value, '2026-10-28T00:00:00Z')
    assert not requirement_active(value, '2026-10-29T00:00:00Z')
    assert requirement_digest(value) == before
    assert requirement_active(spec(), '2100-01-01T00:00:00Z')
    with pytest.raises(ValueError):
        requirement_active(value, datetime(2026, 10, 28))


def test_grant_fixture_supports_expired_revoked_and_boundary_inputs():
    fixture = request(grant_starts_at='2026-10-27T00:00:00Z', grant_expires_at='2026-10-27T12:00:00Z')
    assert VisibilityInput.model_validate(fixture).at == VisibilityInput.model_validate(fixture).grant_expires_at
    assert VisibilityInput.model_validate({**fixture, 'grant_revoked': True}).grant_revoked
    for change in ({'grant_expires_at': None}, {'grant_starts_at': '2026-10-28T00:00:00Z'}):
        with pytest.raises(ValidationError):
            VisibilityInput.model_validate({**fixture, **change})
    with pytest.raises(ValidationError):
        VisibilityInput.model_validate(request(grant_revoked=True))


def test_denial_leak_and_server_errors_are_retained_as_failed_observations():
    result = evaluate_observation(case(), {'status_code': 403, 'visible_fields': ['secret']})
    assert not result.passed and result.unexpected_fields == ('secret',)
    assert result.expected_status_code == result.observed_status_code == 403
    result = evaluate_observation(case(), {'status_code': 500, 'visible_fields': []})
    assert not result.passed and result.observed_status_code == 500
    assert result.missing_fields == result.unexpected_fields == ()


def test_exact_fields_and_status_must_both_match():
    control = spec()['cases'][1]
    assert evaluate_observation(control, {'status_code': 200, 'visible_fields': ['title', 'id']}).passed
    result = evaluate_observation(control, {'status_code': 200, 'visible_fields': ['id', 'tax_id']})
    assert not result.passed and result.missing_fields == ('title',) and result.unexpected_fields == ('tax_id',)
    assert not evaluate_observation(control, {'status_code': 403, 'visible_fields': ['id', 'title']}).passed
    assert evaluate_observation(case(), {'status_code': 403, 'visible_fields': []}).passed


def test_candidate_cannot_supply_expected_output_or_resource_values_in_observation():
    with pytest.raises(ValidationError):
        VisibilityObservation.model_validate({'status_code': 200, 'visible_fields': ['id'],
                                            'expected': {'status_code': 200}})
    with pytest.raises(ValidationError):
        VisibilityObservation.model_validate({'status_code': 200, 'visible_fields': ['id'], 'values': {'id': 'private'}})


@pytest.mark.parametrize('field', ['title', 'source_ref'])
def test_unpaired_unicode_surrogate_cannot_crash_requirement_hashing(field):
    with pytest.raises(ValidationError):
        requirement_digest(spec(**{field: '\ud800'}))
    value = spec();value['cases'][0]['title'] = '\ud800'
    with pytest.raises(ValidationError):
        requirement_digest(value)


@pytest.mark.parametrize('instant', ['0001-01-01T00:00:00+23:59', '9999-12-31T23:59:59-23:59'])
def test_timezone_conversion_overflow_is_a_validation_error(instant):
    with pytest.raises(ValidationError, match='UTC'):
        VisibilityInput.model_validate(request(at=instant))


@pytest.mark.parametrize('conflicting', [False, True])
def test_same_request_context_cannot_pad_or_contradict_coverage(conflicting):
    value = spec();another = deepcopy(value['cases'][0]);another['case_id'] = 'renamed'
    if conflicting:
        another['expected']['status_code'] = 200
    value['cases'].append(another)
    with pytest.raises(ValidationError, match='Identical request contexts'):
        RequirementSpec.model_validate(value)


def test_requirement_key_matches_control_plane_storage_bound():
    assert RequirementSpec.model_validate(spec(key='a'*80)).key == 'a'*80
    with pytest.raises(ValidationError):
        RequirementSpec.model_validate(spec(key='a'*81))
