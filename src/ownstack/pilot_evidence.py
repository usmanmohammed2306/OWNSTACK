"""Measurement plumbing, never invented buyer validation or authenticated ROI."""
from statistics import median
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

class Trial(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    case_id:str=Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9_.:-]+$')
    source_kind:Literal['synthetic','self_reported','observed']
    consent:bool
    same_scope:bool
    baseline_minutes:float=Field(ge=0,le=100000,allow_inf_nan=False)
    ownstack_minutes:float=Field(ge=0,le=100000,allow_inf_nan=False)
    baseline_succeeded:bool
    ownstack_succeeded:bool
    included_setup_and_review:bool
    method:str=Field(min_length=1,max_length=500)

    @model_validator(mode='after')
    def private_observation(self):
        if self.source_kind!='synthetic' and not self.consent:raise ValueError('Non-synthetic observations require recorded consent')
        return self


def summarize(rows):
    trials=[Trial.model_validate(r) for r in rows]
    if len({r.case_id for r in trials})!=len(trials):raise ValueError('Duplicate tasks cannot inflate a comparison')
    eligible=[r for r in trials if r.source_kind=='observed' and r.consent and r.same_scope
        and r.baseline_succeeded and r.ownstack_succeeded and r.included_setup_and_review]
    differences=[r.baseline_minutes-r.ownstack_minutes for r in eligible]
    return {'recorded':len(trials),'eligible_matched_tasks':len(eligible),'excluded':len(trials)-len(eligible),
        'median_minutes_saved':median(differences) if differences else None,
        'buyer_validation_established':False,'willingness_to_pay_established':False,
        'limitations':'Observation labels are caller assertions. Include setup/review and failed outcomes; independent customers must validate the comparison.'}
