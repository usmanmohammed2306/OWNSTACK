"""Measure the actual local serving backend, with no external provider calls."""
import argparse
import json
import os
from pathlib import Path
import statistics
from urllib.parse import urlsplit
import httpx
from action_planner import dataset

def run(endpoint, output):
    parsed=urlsplit(endpoint)
    if (parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost'} or parsed.username or parsed.password
            or parsed.path not in {'','/'} or parsed.query or parsed.fragment):raise ValueError('Local evaluation only')
    if output.exists() or Path(str(output)+'.partial').exists():raise FileExistsError('Preserve existing results; use a new path')
    rows=[r for r in dataset() if r['split']=='test']
    results=[]
    key=os.getenv('OWNSTACK_PLANNER_SERVICE_TOKEN','')
    with httpx.Client(timeout=60,trust_env=False,follow_redirects=False,headers={'X-OwnStack-Planner-Key':key} if key else {}) as client:
        health=client.get(endpoint+'/health').json()
        for row in rows:
            response=client.post(endpoint+'/plan',json={'text':row['text']});response.raise_for_status();result=response.json()
            try:actual=json.loads(result['output'])
            except ValueError:actual=None
            results.append({'text':row['text'],'expected':row['plan'],'actual':actual,'exact':actual==row['plan'],'latency_ms':result['latency_ms']})
            Path(str(output)+'.partial').write_text(json.dumps({'health':health,'rows':results},indent=2))
    times=sorted(r['latency_ms'] for r in results)
    report={'health':health,'total':len(results),'exact':sum(r['exact'] for r in results),'median_ms':statistics.median(times),'p95_ms':times[min(len(times)-1,int(len(times)*.95))],'rows':results}
    output.write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--endpoint',default='http://127.0.0.1:8811');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();run(args.endpoint,args.output)
