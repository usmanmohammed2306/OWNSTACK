"""Populate only a named, AI-off local synthetic release lab."""
import argparse,json,os
from pathlib import Path
from customer_release import lab_path,offline,private_json

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--name',required=True);args=parser.parse_args()
    path=lab_path(args.name);state=json.loads((path/'operator.json').read_text())
    if state.get('OWNSTACK_ENV')!='local' or state.get('OWNSTACK_DATABASE_URL')!='sqlite:///'+str(path/'ownstack.sqlite'):
        raise ValueError('Named local fixture required')
    os.environ.update(state);offline()
    from ownstack.db import SessionLocal
    from ownstack.org_simulation import seed_organization
    from ownstack.models import InferenceBudget
    with SessionLocal() as db:
        if db.get(InferenceBudget,'global').reserved_calls!=0:raise ValueError('Fixture must have zero provider reservations')
        result=seed_organization(db);db.commit()
    private_json(path/'organization-simulation.json',result)
    print(json.dumps({k:result[k] for k in ('simulation','employees','departments','new_credentials_created')}))

if __name__=='__main__':main()
