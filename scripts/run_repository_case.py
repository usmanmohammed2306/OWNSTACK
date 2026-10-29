"""Run an explicit local upstream case and bounded candidate, with no inference."""
import argparse
import json
from pathlib import Path
from ownstack.repository_executor import ROOT, RepositoryCase, execute

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--origin', choices=['human', 'model', 'reference'], required=True)
    parser.add_argument('--evaluator', type=Path, default=ROOT / '.private/real-issues-20261025/evaluator/evaluator-only.jsonl')
    parser.add_argument('--cache', type=Path, default=ROOT / '.private/repository-executor-20261025/source-cache')
    args = parser.parse_args()
    case = RepositoryCase.load(ROOT / 'evals/real_issues_v1/cases.jsonl', args.evaluator, args.case)
    result = execute(case, json.loads(args.candidate.read_text()), args.output, args.cache, origin=args.origin)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
