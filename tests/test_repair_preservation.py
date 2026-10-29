"""Passing observations accompany failures; expectations remain independent."""
from copy import deepcopy
from itertools import product
from ownstack.counterexample_loop import preservation_witnesses


def evidence():
    cases=[];assessments=[]
    for index,(allowed,assigned,grant,same) in enumerate(product((False,True),repeat=4)):
        case={'case_id':str(index),'input':{'assigned':assigned,'grant_starts_at':'2026-10-28' if grant else None,
            'actor_tenant_id':'atlas','resource_tenant_id':'atlas' if same else 'nova'}}
        expected={'status_code':200 if allowed else 403,'visible_fields':['id','title'] if allowed else []}
        cases.append(case)
        assessments.append({'requirement_key':'r','case_id':str(index),'baseline_passed':True,'candidate_passed':True,
            'expected':expected,'observed_candidate':deepcopy(expected)})
    return {'assessments':assessments},[{'key':'r','cases':cases}]


def test_passing_context_is_bounded_distinct_and_keeps_response_fields():
    report,requirements=evidence();before=deepcopy((report,requirements))
    result=preservation_witnesses(report,requirements)
    assert len(result)==6
    assert result[0]['expected']['visible_fields']==['id','title']
    assert result[0]['observed']==result[0]['expected']
    assert len({(r['expected']['status_code'],r['input']['assigned'],r['input']['grant_starts_at'],r['input']['resource_tenant_id']) for r in result})==6
    result[0]['expected']['visible_fields'].clear()
    assert (report,requirements)==before


def test_failed_baselines_or_failed_candidates_cannot_be_passing_witnesses():
    report,requirements=evidence()
    for i,row in enumerate(report['assessments']):
        row['baseline_passed']=i%2==0;row['candidate_passed']=i%2!=0
    assert preservation_witnesses(report,requirements)==[]


def test_witness_selection_is_independent_of_observation_order_and_empty_is_honest():
    report,requirements=evidence();first=preservation_witnesses(report,requirements)
    report['assessments'].reverse()
    assert preservation_witnesses(report,requirements)==first
    assert preservation_witnesses({},requirements)==[]


def test_identical_access_paths_do_not_fill_context_with_duplicates():
    report,requirements=evidence()
    report['assessments']=report['assessments'][:1]*100
    assert len(preservation_witnesses(report,requirements))==1
