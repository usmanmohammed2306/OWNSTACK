"""Stable identifiers for the explicitly migrated legacy General team."""
import hashlib


def general_team_id(tenant_id: str) -> str:
    return hashlib.sha256(('ownstack:general:'+tenant_id).encode()).hexdigest()[:32]


def general_team_default(context) -> str:
    # Internal/legacy constructors keep a deterministic scope. Public creation
    # always supplies the authorized project's team explicitly.
    return general_team_id(context.get_current_parameters()['tenant_id'])
