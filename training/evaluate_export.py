"""Re-score retained raw outputs with the same strict and tolerant parsers.

Removing one enclosing Markdown fence is reported separately, so a formatting
failure is not sold as complete failure of the base model's reasoning.
"""
import argparse
import json
from pathlib import Path

def parse(raw, tolerant=False):
    text=raw.strip()
    if tolerant and text.startswith('```json') and text.endswith('```'):text=text[7:-3].strip()
    try:return json.loads(text)
    except ValueError:return None

def evaluate(root):
    report={}
    for name in ['baseline','evaluation']:
        evidence=json.loads((root/(name+'.json')).read_text());rows=evidence['rows']
        report[name]={'total':len(rows),'strict_exact':sum(parse(r['raw'])==r['expected'] for r in rows),
            'fence_tolerant_exact':sum(parse(r['raw'],True)==r['expected'] for r in rows),
            'strict_json':sum(parse(r['raw']) is not None for r in rows),
            'refusal_exact':sum(parse(r['raw'],True)==r['expected'] for r in rows if r['expected']['actions'][0]['action']=='refuse'),
            'refusal_total':sum(r['expected']['actions'][0]['action']=='refuse' for r in rows)}
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);args=parser.parse_args();print(json.dumps(evaluate(args.root),indent=2))
