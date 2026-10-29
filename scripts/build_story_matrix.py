"""Freeze 1,000 authored composites: 25 contexts crossed with 40 control stories.

These are not 1,000 customer observations or independently written requirements.
The executable scope is the owned project app, not industry-specific integration.
"""
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DOMAINS=[
 ('construction','A storm-delayed building handover brings a visiting surveyor into a confidential bid workspace. Separate subcontractors share some staff but competing bids must stay separate.'),
 ('biopharma','A batch-quality review spans a manufacturer, an external laboratory and a contracted quality specialist. Lot evidence must remain traceable while unrelated study files stay private.'),
 ('aerospace','A leased-aircraft maintenance review needs a parts specialist during a narrow inspection window. Several carriers use the same supplier, but one carrier cannot inherit another carrier’s files.'),
 ('shipping','A customs broker needs a manifest review while a ship changes ports. Connectivity is unreliable, documents are revised and other shippers’ commercial terms must remain inaccessible.'),
 ('semiconductors','A yield investigation involves a foundry, a design house and a visiting process specialist. Process evidence is time-sensitive and unrelated intellectual property must stay private.'),
 ('retail','A consignment supplier needs to reconcile one campaign’s stock. Multiple franchises share a platform but have distinct purchasing agreements, and the review window ends during a shift change.'),
 ('energy','An outage-planning contractor reviews one maintenance project while an incident team works in parallel. The request concerns documents, never operational grid control.'),
 ('finance-audit','A contracted auditor reconciles one close-period project. Several subsidiaries use the platform, and permission to inspect evidence must not become authority to move funds.'),
 ('insurance','A specialist reviews one claims-operations project with restricted attachments. The platform must preserve scope and history without making eligibility or claims decisions.'),
 ('university','A sponsored-research project needs a visiting reviewer before a grant milestone. A shared institution account cannot imply access to unrelated sponsors or research groups.'),
 ('media','An external licensing specialist reviews an embargoed production package. Several studios share a distributor and an early release of the wrong material would be costly.'),
 ('procurement','A procurement team requests a supplier review across a tender deadline. Competing vendors use the same service and overlapping committee memberships cannot merge their workspaces.'),
 ('renewables','A lender’s technical adviser reviews one wind-site project during financial diligence. Weather shifts the visit, while other projects retain separate contracts and evidence.'),
 ('mining','An environmental consultant reviews a mine-site evidence pack. Permit milestones, shift changes and separate operators make timing and scope consequential.'),
 ('agriculture','A cooperative investigates a produce recall with a contracted traceability specialist. Different farms share logistics but cannot inherit one another’s commercial records.'),
 ('telecom','A fiber deployment needs a visiting interconnection reviewer. Multiple network operators share a contractor and project names resemble one another, making identifiers essential.'),
 ('automotive-supply','A parts-recall coordinator reviews a supplier project across several assembly partners. This concerns evidence access, never vehicle firmware or physical control.'),
 ('hr-operations','A contracted payroll-operations reviewer inspects one integration project. Personnel-related records require strict workspace separation; the app makes no employment decisions.'),
 ('hospitality','A franchise support specialist reviews a property-opening project during a busy weekend. Different owners use the same brand and must retain separate financial evidence.'),
 ('legal-operations','An external discovery coordinator reviews a matter-operations project. Privileged material belongs to distinct clients; the app cannot decide legal obligations.'),
 ('security-review','A scoped security reviewer needs one application-assessment project. Evidence access is distinct from permission to run arbitrary commands or reach another customer’s systems.'),
 ('developer-platform','An enterprise integration team requests a customer-specific change before an onboarding deadline. Similar requests recur, but shared code and exact release decisions remain separate.'),
 ('nonprofit','A program-accountability reviewer needs one grant-reporting project. Several funding partners share staff, while beneficiary-related records must remain within the right workspace.'),
 ('commerce-software','A customer-success engineer reviews one invoicing-integration project. Currency and renewal differences create pressure for customization, but this access contract cannot change money rules.'),
 ('healthcare-operations','A visiting operations specialist reviews a referral-logistics project across shift changes. No clinical decision, patient-treatment automation or compliance certification is implied.'),
]
PATTERNS=[
 ('standard','A legitimate short-lived review needs exact scope, approval, a successful protected read and a confirmed revoke.'),
 ('duplicate_request','A lost response causes the requester to deliver the same creation operation twice. Saved identity must be recovered without duplicate work.'),
 ('changed_idempotency','A second tab reuses a creation key after changing its text. The system must reject the changed intent and preserve the first request.'),
 ('duplicate_preparation','The requester presses prepare again after generation completes. The saved proposal must return without another model dispatch.'),
 ('saved_refresh','The page is refreshed while reviewing an already prepared proposal. Reading saved status must not generate again.'),
 ('foreign_project','A forwarded link refers to a different workspace’s project. The direct API must reject the resource even if the caller is privileged in their own workspace.'),
 ('foreign_viewer','A copied account identifier belongs to another customer. A local project cannot be used to grant that foreign identity access.'),
 ('project_drift','The project revision changes while the proposal is under review. Approval must fail until a fresh exact preview is explicitly reviewed.'),
 ('document_drift','A protected document changes after interpretation. The earlier preview must not authorize a newly different document set or content.'),
 ('wrong_hash','A client submits a different proposal hash than the one displayed. Exact approval must fail before any access effect.'),
 ('wrong_approver','An engineer who prepared the proposal tries to approve it. Preparation must not silently expand that role’s approval authority.'),
 ('disabled_viewer','The proposed reviewer is disabled before preparation. The system must not claim that this disabled identity can currently read the project.'),
 ('disable_after_grant','The reviewer is disabled after a valid grant. Existing session/token state must no longer permit reads.'),
 ('expiry','A valid permission reaches its expiry while cleanup workers are absent. The protected read, not a later cleanup job, must enforce the end.'),
 ('exact_expiry','A read occurs at the exact end boundary. Half-open time semantics must deny it without a grace period.'),
 ('future_start','A scheduled variation exists before its start boundary. It must not grant early access and must become effective only at the agreed start.'),
 ('selective_revoke','The same reviewer has two legitimate project engagements. Revoking one must preserve the other and must not be described as complete offboarding.'),
 ('role_survives_revoke','The reviewer now has independent member authority. Revoking a variation must not pretend to remove access granted by that role.'),
 ('two_reviews','The workspace requires two independent current reviewers. The first exact approval must remain evidence only until the second arrives.'),
 ('duplicate_reviewer','One reviewer submits twice under different operation keys. Repeated consent from one person must not count as two independent reviewers.'),
 ('signer_role_loss','A reviewer loses the required role after activation. Both actual access and diagnostic previews must reflect the missing authority.'),
 ('signer_rotation','A reviewer’s session identity version changes after activation. Old approval evidence must not satisfy the captured current-authority condition.'),
 ('review_age','The first review is older than the permitted collection window when the second arrives. A fresh explicit review is required.'),
 ('policy_drift','The approval policy changes after the preview. The old proposal cannot silently inherit a different governance requirement.'),
 ('approval_audit_failure','The effect transaction encounters an evidence-write failure. It must roll back instead of granting access without its required history.'),
 ('observation_failure','A read-time observation cannot be persisted. The response must fail closed without returning protected document content.'),
 ('disguised_feature','A missing export feature is submitted using an access-request category. It must become engineering work or refusal, never an access configuration trick.'),
 ('feature_handoff','The customer needs a real PDF export. The workflow must create a scoped engineering item and keep release authority with a human.'),
 ('patch_role','A workspace administrator tries to submit engineering code. Access-review authority must not imply code-authoring or release authority.'),
 ('patch_escape','A proposed patch targets a path outside the declared owned file. The edit protocol must reject it before execution.'),
 ('oversized_patch','A proposed source replacement exceeds the declared input bound. The server must reject the work rather than process an unbounded payload.'),
 ('release_without_checks','A candidate exists without current independent checks. A human decision request must not turn that unverified patch into a release.'),
 ('stale_patch_hash','A release decision refers to a different candidate hash. The response must not imply that evidence for one patch validates another.'),
 ('forged_agent_fields','The browser submits extra authority fields with an agent request. The service must reject them before model interpretation.'),
 ('actor_changes','The preparing identity loses authority between model completion and host compilation. The late result must not create an effect proposal.'),
 ('request_revision_changes','The request revision changes while the model works. The old answer must not attach to the new revision.'),
 ('intent_changes','The saved request scope/text changes without a revision increment. The intent hash must still fence the stale model answer.'),
 ('approval_replay','An approval response is lost after commit. Replaying the same exact operation must return the saved variation without creating another.'),
 ('revoke_drift','The grant changes between rollback preview and confirmation. A stale rollback digest must not mutate a different effect.'),
 ('proof_tampering','A proof export is copied and altered. Its envelope check must detect the alteration, and a foreign customer must still be denied the original export.'),
]

def cases():
    rows=[]
    for domain_index,(domain,context) in enumerate(DOMAINS):
        for pattern_index,(pattern,conflict) in enumerate(PATTERNS):
            i=domain_index*40+pattern_index+1
            feature=pattern in {'disguised_feature','feature_handoff','patch_role','patch_escape','oversized_patch','release_without_checks','stale_patch_hash'}
            project=f'Project C{i:04d}X'
            text=f'Add PDF export for {project}' if feature else f'Give our contractor read-only access to {project} for one hour'
            rows.append({'id':f'ST{i:04d}','domain':domain,'pattern':pattern,'project':project,
                'story':context+' '+conflict+' The operator must preserve the other customer, retain failed evidence, expose honest progress and leave release decisions explicit.',
                'request':text,'kind':'access' if pattern=='disguised_feature' else 'feature' if feature else 'access',
                'expected_scope':'Owned project-app workflow; no industry-specific implementation or customer observation',
                'invariants':['tenant isolation','no unreviewed effect','no provider credit use','saved evidence','no release implied'],
                'model_input_scope':'Request text only; the industry story is challenge context, not a claim of full narrative understanding'})
    return rows

if __name__=='__main__':
    target=ROOT/'evals/story_matrix_v1';target.mkdir(parents=True,exist_ok=True)
    raw=''.join(json.dumps(c,ensure_ascii=False,separators=(',',':'))+'\n' for c in cases())
    path=target/'cases.jsonl'
    if path.exists() and path.read_text()!=raw:raise SystemExit('Do not overwrite a different frozen dataset')
    path.write_text(raw)
    manifest={'version':1,'cases':1000,'domains':25,'technical_patterns':40,'origin':'Authored combinatorial fictional composites, not real customer observations or 1000 independent business systems',
        'cases_sha256':hashlib.sha256(raw.encode()).hexdigest(),'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope':'Executable owned-host journeys; controls are repeated across domain contexts. Model quality and human fallback must be reported separately.'}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))
