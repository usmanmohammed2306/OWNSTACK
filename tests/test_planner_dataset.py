import importlib.util
import json
from pathlib import Path
from ownstack.action_plans import validate_plan

def source():
    spec=importlib.util.spec_from_file_location('authored_dataset',Path(__file__).resolve().parents[1]/'training/action_planner.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def test_dataset_is_deterministic_disjoint_and_schema_valid():
    module=source();rows=module.dataset();assert rows==module.dataset()
    assert len(rows)==288
    train={r['text'] for r in rows if r['split']=='train'};test={r['text'] for r in rows if r['split']=='test'}
    assert len(train)==222 and len(test)==66 and train.isdisjoint(test)
    assert {r['family'] for r in rows if r['split']=='train'}.isdisjoint({r['family'] for r in rows if r['split']=='test'})
    assert len(train|test)==len(rows)
    for row in rows:assert validate_plan(json.dumps(row['plan']),'admin')

def test_heldout_includes_ambiguous_unsupported_and_refusal_cases():
    rows=[r for r in source().dataset() if r['split']=='test']
    actions={r['plan']['actions'][0]['action'] for r in rows}
    assert actions=={'navigate','theme','move','draft','reset','clarify','refuse'}
    assert sum(r['plan']['actions'][0]['action']=='refuse' for r in rows)==2
