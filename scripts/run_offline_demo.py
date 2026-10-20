"""Repeatable loopback HTTP journey: AI off, exhausted ledger, actual verifier.

Run only on a private restored fixture, not the main app. Saves private proofs
and a sanitized report in a new directory. --resume compares histories after an
operator-controlled service restart. No provider adapter or deployment command.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import uuid4
import httpx
from ownstack.patch_agent import fixture_patch
from ownstack.pdf_oracle import is_external_pass
from ownstack.proof import saved_state_fingerprint, source_inventory, verify_envelope

ROOT = Path(__file__).resolve().parents[1]


def local_base(base):
    parts = urlsplit(base)
    if (parts.scheme != 'http' or parts.hostname != '127.0.0.1' or not parts.port
            or parts.username or parts.password or parts.query or parts.fragment
            or parts.path not in ('', '/')):
        raise ValueError('Explicit loopback HTTP URL and port required')
    return base.rstrip('/')


class OfflineDemo:
    def __init__(self, base, directory, *, transport=None):
        self.base, self.directory = local_base(base), directory.resolve()
        if not self.directory.is_relative_to(ROOT / '.private'):
            raise ValueError('Choose a new directory inside .private')
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        self.directory.chmod(0o700)
        self.transport, self.clients = transport, {}
        self.last_request_started = None
        self.report = {'started_at': datetime.now(timezone.utc).isoformat(), 'passed': False,
            'checks': [], 'http': [], 'request_ids': {}, 'saved_fingerprints': {}, 'new_inference_calls': 0,
            'limits': ['Synthetic local restored fixture, not independent user feedback or production readiness.',
                       'Handwritten manual patch, not a live Nemotron result. Checks are not sandbox certification.',
                       'Human acceptance and Convergence decisions are record-only, never deployment.']}

    def save(self, name, value):
        path = self.directory / name
        path.touch(mode=0o600, exist_ok=False)
        path.write_text(json.dumps(value, indent=2) + '\n')

    def check(self, name, condition):
        self.report['checks'].append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)

    def call(self, who, method, path, body=None, *, expected=200, key=None):
        # This is a functional journey, not a load test. Respect the real proxy's
        # 20 r/s budget instead of weakening it or silently retrying mutations.
        if self.last_request_started is not None:
            time.sleep(max(0, .07-(time.monotonic()-self.last_request_started)))
        self.last_request_started = time.monotonic()
        if who not in self.clients:
            self.clients[who] = httpx.Client(base_url=self.base, timeout=75,
                trust_env=False, follow_redirects=False, transport=self.transport)
        client = self.clients[who]
        headers = {'Origin': self.base}
        if method == 'POST':
            headers['Idempotency-Key'] = key or uuid4().hex
            headers['X-CSRF-Token'] = client.cookies.get('ownstack_csrf') or ''
        started = time.perf_counter()
        response = client.request(method, path, json=body, headers=headers)
        self.report['http'].append({'actor': who, 'method': method, 'path': path,
            'status': response.status_code, 'elapsed_ms': round((time.perf_counter()-started)*1000, 3)})
        if response.status_code != expected:
            raise AssertionError(f'{method} {path}: expected {expected}, got {response.status_code}')
        return response.json()

    def authenticate(self):
        ready = self.call('anonymous', 'GET', '/health/ready')
        self.check('runtime_ai_off', ready['status'] == 'ready' and ready['ai_mode'] == 'off')
        for name in ('atlas-admin', 'atlas-engineer', 'atlas-contractor', 'nova-admin', 'nova-contractor', 'platform-owner'):
            self.call(name, 'POST', '/v1/session', {'username': name, 'password': 'demo-only-pass'})
        budget = self.call('atlas-admin', 'GET', '/v1/inference-budget')
        self.check('exhausted_ledger_and_zero_cap', budget['mode']=='off'
                   and budget['max_live_calls']==0 and budget['reserved_calls']==10)
        self.report['reserved_calls_before'] = budget['reserved_calls']

    def proof(self, request_id):
        proof = self.call('atlas-engineer', 'GET', f'/v1/requests/{request_id}/proof')
        self.check('proof_digest_'+request_id[:8], verify_envelope(proof))
        self.check('served_source_matches_reference_'+request_id[:8], proof['payload']['source_hashes_at_export']==source_inventory())
        self.save('proof-'+request_id+'.json', proof)
        self.report['saved_fingerprints'][request_id] = saved_state_fingerprint(proof)
        return proof

    def access(self, *, expiry=False):
        admin, engineer, contractor = 'atlas-admin', 'atlas-engineer', 'atlas-contractor'
        document = '/v1/host/projects/atlas-project/documents/atlas-roadmap'
        self.call(contractor, 'GET', document, expected=403)
        end = datetime.now(timezone.utc)+timedelta(seconds=8 if expiry else 3600)
        body = {'text': 'Give atlas-contractor read-only access to Project Atlas temporarily',
            'kind':'access', 'project_id':'atlas-project', 'viewer_id':'atlas-contractor', 'expires_at':end.isoformat()}
        key = uuid4().hex
        created = self.call(admin, 'POST', '/v1/requests', body, expected=201, key=key)
        self.check('duplicate_request_saved_'+str(expiry), self.call(admin, 'POST', '/v1/requests', body, expected=201, key=key)==created)
        request_id = created['id']
        self.report['request_ids']['expiry' if expiry else 'access'] = request_id
        self.call(admin, 'POST', f'/v1/requests/{request_id}/interpret', expected=503)
        self.check('ai_off_created_no_attempt_'+str(expiry), self.call(admin,'GET',f'/v1/requests/{request_id}/attempts')==[])
        self.call(admin, 'POST', f'/v1/requests/{request_id}/manual-handoff', expected=403)
        proposal_key = uuid4().hex
        handoff = self.call(engineer, 'POST', f'/v1/requests/{request_id}/manual-handoff', key=proposal_key)
        self.check('handoff_idempotent_'+str(expiry), self.call(engineer,'POST',f'/v1/requests/{request_id}/manual-handoff',key=proposal_key)==handoff)
        proposal = self.call(admin, 'GET', '/v1/proposals/'+handoff['proposal_id'])
        self.check('manual_not_model_'+str(expiry), handoff['ai_call'] is False and proposal['route']=='configure')
        preview = self.call(admin, 'POST', '/v1/proposals/'+proposal['id']+'/preview')
        self.check('host_preview_parity_'+str(expiry), preview['matches_saved_proposal'])
        self.call(admin, 'POST', '/v1/proposals/'+proposal['id']+'/approve', {'proposal_hash':'0'*64}, expected=409)
        self.call(engineer, 'POST', '/v1/proposals/'+proposal['id']+'/approve', {'proposal_hash':proposal['proposal_hash']}, expected=403)
        approved = self.call(admin, 'POST', '/v1/proposals/'+proposal['id']+'/approve', {'proposal_hash':proposal['proposal_hash']})
        self.call(contractor,'GET',document)
        self.call('nova-admin','GET',document,expected=404)
        self.call(contractor,'GET','/v1/host/projects/nova-project/documents/nova-roadmap',expected=404)
        self.call('nova-contractor','GET','/v1/host/projects/nova-project/documents/nova-roadmap',expected=403)
        self.call('nova-admin','GET','/v1/host/projects/nova-project/documents/nova-roadmap')
        usage = self.call(admin, 'GET', '/v1/host-observations?variation_id='+approved['variation_id'])
        self.check('actual_grant_observed_'+str(expiry), len(usage)==1 and usage[0]['basis']=='variation')
        if expiry:
            time.sleep(max(0,(end-datetime.now(timezone.utc)).total_seconds())+.15)
            self.call(contractor,'GET',document,expected=403)
            self.check('expiry_denied_without_cleanup',True)
        self.call(admin,'POST','/v1/variations/'+approved['variation_id']+'/revoke')
        self.call(contractor,'GET',document,expected=403)
        self.check('revocation_enforced_'+str(expiry),True)
        self.proof(request_id)

    def engineering(self):
        engineer = 'atlas-engineer'
        created = self.call(engineer,'POST','/v1/requests',{'text':'Add PDF export for Project Atlas',
            'kind':'feature','project_id':'atlas-project'},expected=201)
        request_id = created['id']
        self.report['request_ids']['engineering'] = request_id
        handoff = self.call(engineer,'POST',f'/v1/requests/{request_id}/manual-handoff')
        proposal = self.call(engineer,'GET','/v1/proposals/'+handoff['proposal_id'])
        self.check('pdf_routes_to_engineering',proposal['route']=='engineering' and handoff['ai_call'] is False)
        items = self.call(engineer,'GET','/v1/engineering')
        item = next(row for row in items if row['request_id']==request_id)
        item_url = '/v1/engineering/'+item['id']
        self.report['engineering_item_id'] = item['id']
        broken = fixture_patch()
        broken['edits'][0]['new'] = "def export_pdf(project_name, rows):\n    return b'not a PDF'\n"
        failed = self.call(engineer,'POST',item_url+'/manual-patch',{'patch':broken})
        failure = self.call(engineer,'POST',item_url+'/verify')
        self.check('actual_bad_patch_rejected',failure['passed'] is False and failure['patch_hash']==failed['patch_hash']
                   and failure['runner'] not in ('unavailable','no-network-queue-timeout'))
        self.call(engineer,'POST',item_url+'/decide',{'decision':'accept_for_manual_release','patch_hash':failed['patch_hash']},expected=409)
        self.call(engineer,'POST',item_url+'/repairs',{'patch_hash':failed['patch_hash']},expected=409)
        corrected = self.call(engineer,'POST',item_url+'/manual-patch',{'patch':fixture_patch()})
        passed = self.call(engineer,'POST',item_url+'/verify')
        self.check('seven_actual_external_oracle_checks',is_external_pass(passed) and passed['patch_hash']==corrected['patch_hash'])
        self.call('atlas-admin','POST',item_url+'/decide',{'decision':'accept_for_manual_release','patch_hash':corrected['patch_hash']},expected=403)
        decision = self.call(engineer,'POST',item_url+'/decide',{'decision':'accept_for_manual_release','patch_hash':corrected['patch_hash']})
        artifact = self.call(engineer,'GET',item_url+'/artifact')
        self.check('exact_artifact_not_deployed',artifact['patch_hash']==corrected['patch_hash']
                   and '+++ b/sample_app/report.py' in artifact['diff'] and decision['release_state']==artifact['release_state']=='not_deployed')
        proof = self.proof(request_id)
        evidence = proof['payload']['evidence']
        self.check('failed_evidence_preserved',any(r['kind']=='patch_checks' and r['subject_hash']==failed['patch_hash']
                   and r['result']['passed'] is False for r in evidence))
        self.check('failed_source_preserved',any(r['kind']=='superseded_patch' and r['subject_hash']==failed['patch_hash'] for r in evidence))
        self.report['runner'], self.report['oracle_cases'] = passed['runner'],passed['checks_completed']

    def convergence(self):
        feature = self.call('nova-admin','POST','/v1/requests',{'text':'Add PDF export for Project Nova',
            'kind':'feature','project_id':'nova-project'},expected=201)
        self.report['request_ids']['nova_feature'] = feature['id']
        self.call('nova-admin','GET','/v1/requests/'+self.report['request_ids']['engineering']+'/proof',expected=404)
        self.call('atlas-admin','POST','/v1/convergence/pdf-export/decide',
            {'decision':'keep_separate','rationale':'Synthetic offline comparison, not customer demand.'},expected=403)
        rows = self.call('platform-owner','GET','/v1/convergence')
        signal = next(row for row in rows if row['need_key']=='pdf-export')
        self.check('repeated_need_two_tenants',signal['affected_tenant_count']>=2 and 'text' not in signal)
        result = self.call('platform-owner','POST','/v1/convergence/pdf-export/decide',
            {'decision':'keep_separate','rationale':'Synthetic rehearsal: retain separate needs pending real-team evidence.'})
        self.check('convergence_record_only',result['effect']=='record_only')
        local = next(row for row in self.call('atlas-admin','GET','/v1/convergence') if row['need_key']=='pdf-export')
        self.check('tenant_cannot_see_cross_tenant_count',local['affected_tenant_count'] is None)

    def execute(self, resume=None):
        try:
            self.authenticate()
            if resume:
                previous = json.loads(resume.read_text())
                if not previous.get('passed') or not previous.get('saved_fingerprints'):
                    raise ValueError('A passing prior report with saved fingerprints is required')
                for request_id, expected in previous['saved_fingerprints'].items():
                    proof = self.proof(request_id)
                    self.check('restart_preserved_'+request_id[:8],saved_state_fingerprint(proof)==expected)
                self.report['resume_only'] = True
            else:
                self.access()
                self.access(expiry=True)
                self.engineering()
                self.convergence()
            after = self.call('atlas-admin','GET','/v1/inference-budget')
            self.check('budget_unchanged',after['mode']=='off' and after['max_live_calls']==0
                       and after['reserved_calls']==self.report['reserved_calls_before']==10)
            self.report['reserved_calls_after'] = after['reserved_calls']
            self.report['passed'] = True
        except Exception as error:
            self.report['error_type'] = type(error).__name__
            # Only authored assertion names/statuses, never arbitrary HTTP error bodies.
            if isinstance(error, AssertionError):
                self.report['failed_check'] = str(error)
        finally:
            for name, client in self.clients.items():
                if name!='anonymous':
                    try:
                        self.call(name,'POST','/v1/session/logout')
                    except Exception:
                        self.report.setdefault('cleanup_errors',[]).append(name)
                client.close()
            self.report['finished_at'] = datetime.now(timezone.utc).isoformat()
            self.save('report.json',self.report)
        return self.report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--resume',type=Path,help='Prior private report, after explicit service restart')
    args = parser.parse_args()
    try:
        result = OfflineDemo(args.url,args.output).execute(args.resume)
    except Exception as error:
        result = {'passed':False,'error_type':type(error).__name__,'new_inference_calls':0}
    print(json.dumps(result,indent=2))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
