"""Two deliberately different native schemas with one narrow normalized policy.

The adapters are trusted, agent-authored fixtures. Their semantic manifests are
declarations checked against these finite outputs, not machine-proven semantics.
"""
from dataclasses import dataclass, replace
from ownstack.compatibility import CONTRACTS, HostManifest, Resource


SEMANTICS = (("tenant", "owner-tenant"), ("scope", "single-workspace"),
             ("title", "public-title"), ("content", "public-content"),
             ("internal_notes", "private-internal-notes"),
             ("customer_email", "private-contact-email"))
SUPPORTED = tuple((c.id, c.version, c.hash) for c in CONTRACTS.values())


@dataclass(frozen=True)
class ProjectDocument:
    uuid: str
    organization: str
    project_slug: str
    title: str
    body: str
    finance_notes: str
    contact: str


@dataclass(frozen=True)
class DocumentEnvelope:
    uuid: str
    workspace: tuple[str, str]
    content: tuple[tuple[str, str], ...]


DOCUMENTS = (
    ProjectDocument("atlas-plan", "atlas", "atlas-project", "Atlas plan", "Install canopy",
                    "Synthetic margin: 18%", "buyer@atlas.invalid"),
    ProjectDocument("atlas-other", "atlas", "other-project", "Other plan", "Restricted other scope",
                    "Synthetic margin: 12%", "other@atlas.invalid"),
    ProjectDocument("nova-plan", "nova", "nova-project", "Nova plan", "Inspect roof",
                    "Synthetic margin: 22%", "buyer@nova.invalid"),
)


class ProjectDocuments:
    def __init__(self, version: int = 1, *, unsafe_semantics: bool = False):
        if version not in (1, 2):
            raise ValueError("Only two owned schema versions exist")
        self.manifest = HostManifest("projects", version, "project-document", SEMANTICS,
                                     SUPPORTED, f"project-adapter-v{version}")
        if unsafe_semantics:
            self.manifest = replace(self.manifest, semantics=tuple(
                (k, "public-content" if k == "internal_notes" else v) for k, v in SEMANTICS),
                adapter_revision=f"project-adapter-v{version}-unsafe")
        self.rows = DOCUMENTS if version == 1 else tuple(
            DocumentEnvelope(d.uuid, (d.organization, d.project_slug),
                             (("caption", d.title), ("markdown", d.body),
                              ("private_notes", d.finance_notes), ("contact_email", d.contact)))
            for d in DOCUMENTS)

    def resource(self, key: str) -> Resource | None:
        for row in self.rows:
            if row.uuid != key:
                continue
            if isinstance(row, ProjectDocument):
                return Resource(row.uuid, row.organization, row.project_slug,
                                (("title", row.title), ("content", row.body),
                                 ("internal_notes", row.finance_notes), ("customer_email", row.contact)))
            payload = dict(row.content)
            return Resource(row.uuid, row.workspace[0], row.workspace[1],
                            (("title", payload["caption"]), ("content", payload["markdown"]),
                             ("internal_notes", payload["private_notes"]),
                             ("customer_email", payload["contact_email"])))
        return None

    def snapshot(self) -> tuple[Resource, ...]:
        return tuple(self.resource(row.uuid) for row in self.rows)


# This app has integer work-order keys, company-owned boards and nested payloads.
# It does not reuse the document schema or project IDs.
BOARDS = {"A-17": "atlas", "N-24": "nova"}
WORK_ORDERS = {
    701: {"board": "A-17", "blocks": {"summary": "Canopy visit", "instructions": "Measure site",
                                        "technician": {"private": "Synthetic supplier rebate"}},
          "requester": {"email": "scheduler@atlas.invalid"}},
    802: {"board": "N-24", "blocks": {"summary": "Roof visit", "instructions": "Check supports",
                                        "technician": {"private": "Synthetic quote limit"}},
          "requester": {"email": "scheduler@nova.invalid"}},
}


class WorkOrders:
    def __init__(self, version: int = 1):
        if version not in (1, 2):
            raise ValueError("Only two owned schema versions exist")
        self.manifest = HostManifest("workorders", version, "service-ticket", SEMANTICS,
                                     SUPPORTED, f"workorder-adapter-v{version}")
        self.rows = WORK_ORDERS if version == 1 else {
            key: {"queue": row["board"], "public": (row["blocks"]["summary"], row["blocks"]["instructions"]),
                  "restricted": (row["blocks"]["technician"]["private"], row["requester"]["email"])}
            for key, row in WORK_ORDERS.items()}

    def resource(self, key: str) -> Resource | None:
        if not key.startswith("WO-") or not key[3:].isdigit():
            return None
        number = int(key[3:])
        if key != f"WO-{number}":
            return None
        row = self.rows.get(number)
        if not row:
            return None
        if self.manifest.version == 1:
            board = row["board"]
            fields = (("title", row["blocks"]["summary"]), ("content", row["blocks"]["instructions"]),
                      ("internal_notes", row["blocks"]["technician"]["private"]),
                      ("customer_email", row["requester"]["email"]))
        else:
            board = row["queue"]
            fields = tuple(zip(("title", "content", "internal_notes", "customer_email"),
                               row["public"] + row["restricted"]))
        return Resource(key, BOARDS[board], board, fields)

    def snapshot(self) -> tuple[Resource, ...]:
        return tuple(self.resource(f"WO-{number}") for number in sorted(self.rows))
