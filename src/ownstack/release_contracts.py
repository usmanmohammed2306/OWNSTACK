"""Reviewed expectations for one bounded customer data-visibility adapter.

These models describe test inputs and assertions, never authorization to grant
access, execute code or change an expectation. Approval authority belongs to the
authenticated control plane. The adapter receives only VisibilityInput; expected
results stay outside the candidate process and are compared independently.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


Identifier = Annotated[str, Field(min_length=1, max_length=96, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]*$')]
Label = Annotated[str, Field(min_length=1, max_length=240)]
Role = Literal['anonymous', 'contractor', 'member', 'engineer', 'manager', 'admin']


def _instant(value: object) -> datetime:
    """Require an explicit timezone; equivalent instants canonicalize to UTC."""
    if isinstance(value, str):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', value):
            raise ValueError('An explicit RFC3339 instant is required')
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('A timezone-aware instant is required')
    try:
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise ValueError('Instant cannot be represented in UTC') from None


def _single_line(value: str) -> str:
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError:
        raise ValueError('A valid UTF-8 label/reference is required') from None
    if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('A nonempty single-line label/reference is required')
    return value


def _sequence(value):
    # JSON arrays and Python tuples have the same bounded wire semantics.
    if not isinstance(value, (list, tuple)):
        raise ValueError('An explicit array is required')
    return tuple(value)


class _ContractModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid', revalidate_instances='always')


class VisibilityInput(_ContractModel):
    """Synthetic request context for the fixed document-read adapter operation.

    A production integration derives actor/resource facts from trusted server
    state. This reviewed fixture context is not a replacement identity system.
    Optional grant intervals can be expired at ``at``, but must be well formed.
    """
    actor_id: Identifier
    actor_tenant_id: Identifier
    actor_role: Role
    resource_id: Identifier
    resource_tenant_id: Identifier
    assigned: bool
    at: datetime
    grant_starts_at: datetime | None = None
    grant_expires_at: datetime | None = None
    grant_revoked: bool = False

    @field_validator('at', mode='before')
    @classmethod
    def request_instant(cls, value):
        return _instant(value)

    @field_validator('grant_starts_at', 'grant_expires_at', mode='before')
    @classmethod
    def grant_instant(cls, value):
        return None if value is None else _instant(value)

    @model_validator(mode='after')
    def well_formed_grant(self):
        if (self.grant_starts_at is None) != (self.grant_expires_at is None):
            raise ValueError('Grant start and expiry must both be present or absent')
        if self.grant_starts_at is not None and self.grant_expires_at <= self.grant_starts_at:
            raise ValueError('Grant expiry must follow its start')
        if self.grant_revoked and self.grant_starts_at is None:
            raise ValueError('A revoked fixture must identify its grant interval')
        return self


class _FieldsModel(_ContractModel):
    visible_fields: Annotated[tuple[str, ...], Field(max_length=64)]

    @field_validator('visible_fields', mode='before')
    @classmethod
    def explicit_field_array(cls, value):
        return _sequence(value)

    @field_validator('visible_fields')
    @classmethod
    def public_field_names(cls, value):
        if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', field) or field.startswith('__') for field in value):
            raise ValueError('Only explicit flat public field names are supported')
        if len(value) != len(set(value)):
            raise ValueError('Duplicate field names are not allowed')
        # Field order has no semantic meaning in the JSON object being observed.
        return tuple(sorted(value))


class VisibilityExpectation(_FieldsModel):
    status_code: Literal[200, 401, 403, 404]

    @field_validator('status_code', mode='before')
    @classmethod
    def strict_status(cls, value):
        if type(value) is not int:
            raise ValueError('An integer HTTP status is required')
        return value

    @model_validator(mode='after')
    def denied_has_no_visible_fields(self):
        if self.status_code != 200 and self.visible_fields:
            raise ValueError('Denied expectations cannot expose resource fields')
        return self


class VisibilityObservation(_FieldsModel):
    """Only actual status/field names, never values, enter the comparison.

    An unexpected server response, including 500 or fields on a denial, must be
    retained as a failing observation rather than silently discarded by schema.
    """
    status_code: Annotated[StrictInt, Field(ge=100, le=599)]


class VisibilityCase(_ContractModel):
    case_id: Identifier
    title: Label
    kind: Literal['target', 'control']
    input: VisibilityInput
    expected: VisibilityExpectation

    @field_validator('title')
    @classmethod
    def no_control_characters(cls, value):
        return _single_line(value)


class RequirementSpec(_ContractModel):
    """One immutable proposed revision; changing it requires fresh approval.

    Target cases address the customer tenant's resources. At least one control
    case addresses another tenant. This is a coverage floor, not a proof that all
    relevant states or a customer's actual intent have been captured.
    """
    schema_version: Literal[1] = 1
    key: Annotated[Identifier, Field(max_length=80)]
    version: Annotated[StrictInt, Field(ge=1, le=1_000_000)]
    customer_tenant_id: Identifier
    title: Label
    source_ref: Annotated[str, Field(min_length=1, max_length=512)]
    owner_id: Identifier
    expires_at: datetime | None = None
    cases: Annotated[tuple[VisibilityCase, ...], Field(min_length=2, max_length=64)]

    @field_validator('schema_version', mode='before')
    @classmethod
    def strict_schema_version(cls, value):
        if type(value) is not int:
            raise ValueError('An integer schema version is required')
        return value

    @field_validator('expires_at', mode='before')
    @classmethod
    def optional_expiry(cls, value):
        return None if value is None else _instant(value)

    @field_validator('cases', mode='before')
    @classmethod
    def explicit_cases(cls, value):
        return _sequence(value)

    @field_validator('title', 'source_ref')
    @classmethod
    def single_line_reference(cls, value):
        return _single_line(value)

    @model_validator(mode='after')
    def scoped_coverage(self):
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError('Each case ID must be unique within a requirement')
        contexts = [json.dumps(case.input.model_dump(mode='json'), sort_keys=True, separators=(',', ':')) for case in self.cases]
        if len(set(contexts)) != len(contexts):
            raise ValueError('Identical request contexts cannot inflate or contradict requirement coverage')
        if not any(case.kind == 'target' for case in self.cases):
            raise ValueError('At least one target case is required')
        if not any(case.kind == 'control' for case in self.cases):
            raise ValueError('At least one other-tenant control is required')
        for case in self.cases:
            matches = case.input.resource_tenant_id == self.customer_tenant_id
            if matches != (case.kind == 'target'):
                raise ValueError('Target/control classification must match customer resource scope')
        return self


class CaseEvaluation(_ContractModel):
    case_id: Identifier
    passed: bool
    expected_status_code: StrictInt
    observed_status_code: StrictInt
    missing_fields: tuple[str, ...]
    unexpected_fields: tuple[str, ...]


class VisibilityAdapter(Protocol):
    """The fixed operation an integration must expose, without expected outputs."""
    def observe(self, request: VisibilityInput) -> VisibilityObservation: ...


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def case_digest(case: VisibilityCase | dict) -> str:
    checked = VisibilityCase.model_validate(case)
    return _digest(checked.model_dump(mode='json'))


def requirement_digest(spec: RequirementSpec | dict) -> str:
    """Bind every approved field and expectation; case ordering is irrelevant."""
    checked = RequirementSpec.model_validate(spec)
    value = checked.model_dump(mode='json')
    value['cases'] = sorted(value['cases'], key=lambda case: case['case_id'])
    return _digest(value)


def requirement_active(spec: RequirementSpec | dict, at: datetime | str) -> bool:
    checked = RequirementSpec.model_validate(spec)
    instant = _instant(at)
    return checked.expires_at is None or instant < checked.expires_at


def evaluate_observation(case: VisibilityCase | dict, observation: VisibilityObservation | dict) -> CaseEvaluation:
    """Compare independently; no candidate-authored expected result is accepted."""
    checked = VisibilityCase.model_validate(case)
    actual = VisibilityObservation.model_validate(observation)
    wanted, seen = set(checked.expected.visible_fields), set(actual.visible_fields)
    missing, unexpected = tuple(sorted(wanted - seen)), tuple(sorted(seen - wanted))
    return CaseEvaluation(case_id=checked.case_id,
        passed=actual.status_code == checked.expected.status_code and not missing and not unexpected,
        expected_status_code=checked.expected.status_code, observed_status_code=actual.status_code,
        missing_fields=missing, unexpected_fields=unexpected)
