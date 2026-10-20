"""Transparent synthetic baselines, not measurements of a team's manual process."""
from dataclasses import dataclass
from difflib import unified_diff
from ownstack.compatibility import HostAdapter, Principal, ReadResult


@dataclass(frozen=True)
class ManualFlag:
    tenant: str
    host: str
    scope: str
    subject: str
    expires: int
    redactions: tuple[str, ...]


def manual_flag_read(adapter: HostAdapter, actor: Principal, key: str,
                     now: int, flags: tuple[ManualFlag, ...]) -> ReadResult:
    """A competent small baseline: scoped, expiring read flag with field exclusions.

    It deliberately has no manifest migration fence or approval history. It uses
    the same trusted normalization so field mapping is not an unfair disadvantage.
    """
    resource = adapter.resource(key)
    if resource is None or resource.tenant != actor.tenant:
        return ReadResult(False, "not-found")
    selected = [flag for flag in flags if
                (flag.tenant, flag.host, flag.scope, flag.subject) ==
                (actor.tenant, adapter.manifest.host, resource.scope, actor.id) and now < flag.expires]
    if actor.role not in ("admin", "member") and not (actor.role == "contractor" and selected):
        return ReadResult(False, "no-read-permission")
    hidden = {field for flag in selected for field in flag.redactions}
    return ReadResult(True, "manual-flag", tuple((k, v) for k, v in resource.fields if k not in hidden))


# Tiny actual Python source fixtures, compiled and executed in the experiment.
# The repeated edit burden follows from this fixture's deliberate branch design;
# it is not an estimate of maintenance time or all real feature-flag systems.
BRANCH_V1 = """def public_view(row):
    return {"title": row["title"], "content": row["body"]}
"""
BRANCH_V2 = """def public_view(row):
    return {"title": row["caption"], "content": row["markdown"]}
"""


def branch_edit_comparison() -> dict:
    copies = {tenant: BRANCH_V1 for tenant in ("atlas", "nova")}
    edits = {}
    failures_before = 0
    row_v2 = {"caption": "Synthetic", "markdown": "Value"}
    for tenant, source in copies.items():
        namespace = {}
        exec(compile(source, f"owned-{tenant}-branch-v1", "exec"), namespace)
        try:
            namespace["public_view"](row_v2)
        except KeyError:
            failures_before += 1
        edits[tenant] = list(unified_diff(source.splitlines(), BRANCH_V2.splitlines(),
                                         fromfile=f"{tenant}/v1", tofile=f"{tenant}/v2", lineterm=""))
        exec(compile(BRANCH_V2, f"owned-{tenant}-branch-v2", "exec"), namespace)
        assert namespace["public_view"](row_v2) == {"title": "Synthetic", "content": "Value"}
    return {"synthetic": True, "branches": 2, "branches_broken_before_update": failures_before,
            "branch_source_units_edited": len(edits), "shared_adapter_source_units_edited": 1,
            "manual_flag_shared_adapter_source_units_edited": 1,
            "diffs": edits, "human_time_measured": False,
            "interpretation": "Shared adapter and competent shared feature-flag baseline both avoid duplicated fixture edits."}
