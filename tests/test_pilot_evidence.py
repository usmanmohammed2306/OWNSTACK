import pytest
from ownstack.pilot_evidence import summarize

def row(**changes):return {'case_id':'trial-1','source_kind':'observed','consent':True,'same_scope':True,
    'baseline_minutes':20.0,'ownstack_minutes':25.0,'baseline_succeeded':True,'ownstack_succeeded':True,
    'included_setup_and_review':True,'method':'Synthetic unit control, not actual users',**changes}

def test_empty_data_and_synthetic_records_do_not_establish_savings_or_demand():
    assert summarize([])['median_minutes_saved'] is None
    result=summarize([row(source_kind='synthetic')]);assert result['eligible_matched_tasks']==0
    assert result['median_minutes_saved'] is None and not result['buyer_validation_established']

def test_negative_comparison_is_retained_and_scope_controls_are_excluded():
    result=summarize([row(),row(case_id='other',same_scope=False)])
    assert result['median_minutes_saved']==-5 and result['excluded']==1 and not result['willingness_to_pay_established']

@pytest.mark.parametrize('change',[{'consent':False},{'baseline_minutes':float('nan')}])
def test_unusable_measurements_rejected(change):
    with pytest.raises(ValueError):summarize([row(**change)])

def test_duplicate_tasks_do_not_inflate_evidence():
    with pytest.raises(ValueError):summarize([row(),row()])
