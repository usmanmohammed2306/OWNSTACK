"""A competent cheap baseline for the deliberately narrow English command set.

Written against the published action vocabulary after authoring the dataset, so
this is a transparent engineering comparison, not a blinded independent study.
It has exactly the same absence of execution/approval authority as the model.
"""
import json
import re
from action_planner import dataset

def baseline(text):
    text=text.lower()
    def has(words):return bool(re.search(r'\b('+words+r')\b',text))
    action={'action':'clarify'}
    targets={'workspace':'demo','requests':'journey','access':'access','code':'engineering','patterns':'convergence'}
    target=next((value for key,value in targets.items() if has(key)),None)
    color=next((key for key in ['ice','violet','mint'] if has(key)),None)
    directions={'left':(-3,0),'right':(3,0),'front':(0,3),'back':(0,-3)}
    direction=next((value for key,value in directions.items() if has(key)),None)
    if has('approve|deploy|shell|bash|secret|secrets|password|admin|administrator|superuser|bypass|disable|steal|cookie|merge|execute|escalate'):action={'action':'refuse'}
    elif has('reset|defaults|default|factory|original|restore'):action={'action':'reset'}
    elif color:action={'action':'theme','target':color}
    elif target and direction and has('move|put|place|shift|reposition|slide|arrange'):action={'action':'move','target':target,'x':direction[0],'z':direction[1]}
    elif target and has('open|show|go|navigate|take|see|switch|display|bring|inspect'):action={'action':'navigate','target':target}
    elif has('pdf|csv|export|feature|integration|reporting|dashboard|software|printable'):action={'action':'draft','target':'feature'}
    elif has('access|permission|view|read|view-only'):action={'action':'draft','target':'access'}
    return {'actions':[action]}

if __name__=='__main__':
    rows=[dict(text=r['text'],expected=r['plan'],actual=baseline(r['text']),exact=baseline(r['text'])==r['plan']) for r in dataset() if r['split']=='test']
    print(json.dumps({'exact':sum(r['exact'] for r in rows),'total':len(rows),'scope':'authored English vocabulary; baseline not blinded','rows':rows},indent=2))
