"""CI entry point for reviewed requirements and bounded adapter snapshots.

Exit0 means evaluated cases passed,1 means a candidate regression and2 means
blocked/invalid baseline. Does not merge, deploy or publish a GitHub comment.
Pin requirements from a separately reviewed protected revision, never let the
candidate rewrite its own expected results. Existing Docker image is required.
"""
import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from ownstack.model_contracts import strict_json
from ownstack.release_contracts import RequirementSpec
from ownstack.release_executor import run_release
from ownstack.release_assurance import review_markdown,assess_report


def result_state(report,specs):
    item=SimpleNamespace(baseline_sha256=report['baseline_sha256'],candidate_sha256=report['candidate_sha256'],
        requirements_sha256=report['requirements_sha256'],requirements=[s.model_dump(mode='json') for s in specs])
    return assess_report(item,report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--requirements',type=Path,required=True)
    parser.add_argument('--requirements-sha256',required=True)
    parser.add_argument('--image',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    raw=args.requirements.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.requirements_sha256:
        raise ValueError('Requirements do not match the independently pinned receipt')
    parsed=strict_json(raw.decode(),limit=512_000)
    if not isinstance(parsed,list) or not 1<=len(parsed)<=30:
        raise ValueError('Explicit reviewed requirement list required')
    specs=[RequirementSpec.model_validate(s) for s in parsed]
    report=run_release(args.baseline,args.candidate,specs,args.output,image=args.image)
    state=result_state(report,specs)
    from ownstack.policy import digest
    item=SimpleNamespace(state=state,baseline_sha256=report['baseline_sha256'],candidate_sha256=report['candidate_sha256'],
        requirements_sha256=report['requirements_sha256'],report=report,evidence_hash=digest(report),decision=None)
    target=args.output/'review.md'
    with target.open('x') as stream:stream.write(review_markdown(item))
    target.chmod(0o600)
    print(json.dumps({'state':state,'evidence_hash':item.evidence_hash,'report':str(args.output/'report.json'),
                      'review':str(target),'deployed':False,'provider_calls':0}))
    return 0 if state=='passed' else 1 if state=='regression' else 2


if __name__=='__main__':
    try:code=main()
    except Exception as error:
        # Validation details can contain private requirements. Keep CLI output
        # bounded and omit input values, provider credentials and source bytes.
        print(json.dumps({'state':'blocked','error_type':type(error).__name__,'provider_calls':0}));code=2
    raise SystemExit(code)
