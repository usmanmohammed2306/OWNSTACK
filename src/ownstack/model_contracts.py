"""Untrusted model boundaries. Schemas constrain proposals, never authorize effects."""
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class RouteProposal(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    route: Literal["configure", "engineering", "refuse"]
    reason: str = Field(min_length=1, max_length=500)


class ReplacementProposal(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    replacement: str = Field(min_length=1, max_length=12_000)


def strict_json(raw: str, limit: int = 16_384):
    """Reject duplicate keys, non-JSON numbers, excess size and deep nesting.

    Do not include input or validation details in exceptions/logs: they may contain
    private prompts or proposed source. Full schema validation happens afterwards.
    """
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("INVALID_MODEL_OUTPUT")
            result[key] = value
        return result

    try:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > limit:
            raise ValueError()
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        def depth(node, level=0):
            if level > 16:
                raise ValueError()
            if isinstance(node, dict):
                for child in node.values():
                    depth(child, level + 1)
            elif isinstance(node, list):
                for child in node:
                    depth(child, level + 1)
            elif isinstance(node, str):
                node.encode("utf-8", errors="strict")
        depth(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("INVALID_MODEL_OUTPUT") from None


def validate_proposal(raw: str, expected_tool: str):
    """Only these two proposal functions exist. No shell, read, approve or deploy."""
    schema = {"propose_route": RouteProposal, "propose_replacement": ReplacementProposal}.get(expected_tool)
    if schema is None:
        raise ValueError("UNKNOWN_MODEL_TOOL")
    try:
        return schema.model_validate(strict_json(raw))
    except ValidationError:
        raise ValueError("INVALID_MODEL_OUTPUT") from None
