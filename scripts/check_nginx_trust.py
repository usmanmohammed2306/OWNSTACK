"""Test the real generated proxy with two loopback peers, no DB/AI/public ports.

Only trusted test code runs. The installed Nginx and API images share an isolated
network-none namespace. The upstream echoes headers, not application/private data.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CLIENT = r'''
import http.client,json,threading,time
from http.server import BaseHTTPRequestHandler,HTTPServer
class Echo(BaseHTTPRequestHandler):
    def do_GET(self):
        body=json.dumps(dict(self.headers)).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)
    def log_message(self,*_):pass
server=HTTPServer(('127.0.0.1',18800),Echo)
threading.Thread(target=server.serve_forever,daemon=True).start()
records=[]
for peer,expected in [('127.0.0.1','http'),('127.0.0.2','https')]:
    for path in ['/v1/session','/v1/probe','/health/live']:
        for attempt in range(30):
            try:
                connection=http.client.HTTPConnection('127.0.0.1',8080,timeout=2,source_address=(peer,0))
                connection.request('GET',path,headers={'Host':'ownstack-proxy.invalid',
                    'X-Forwarded-Proto':'https','X-Forwarded-For':'198.51.100.9'})
                response=connection.getresponse();data=response.read();connection.close()
                if response.status==200:break
            except OSError:pass
            time.sleep(.1)
        else:raise RuntimeError('Local proxy unavailable')
        headers={k.lower():v for k,v in json.loads(data).items()}
        wanted_ip=peer if expected=='http' else '198.51.100.9'
        passed=(headers.get('x-forwarded-proto')==expected
            and headers.get('x-forwarded-for')==wanted_ip
            and headers.get('host')=='ownstack-proxy.invalid')
        records.append({'peer':peer,'path':path,'expected_scheme':expected,
            'observed_scheme':headers.get('x-forwarded-proto'),'passed':passed})
server.shutdown()
print(json.dumps({'passed':all(r['passed'] for r in records),'checks':records}))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    name='ownstack-proxy-control-'+uuid4().hex
    template=(ROOT/'web/nginx.conf').read_text()
    config=template.replace('${OWNSTACK_EDGE_INTERNAL_IP}','127.0.0.2').replace(
        'http://api:8800','http://127.0.0.1:18800')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as output, tempfile.TemporaryDirectory(prefix='ownstack-proxy-control-') as directory:
        try:
            path=Path(directory)/'default.conf'
            path.write_text(config);path.chmod(0o444)
            subprocess.run(['docker','run','-d','--pull','never','--name',name,
                '--network','none','--read-only','--tmpfs','/var/cache/nginx:rw,size=16m',
                '--tmpfs','/var/run:rw,size=1m','--memory','128m','--pids-limit','32',
                '--security-opt','no-new-privileges','-v',str(path)+':/etc/nginx/conf.d/default.conf:ro',
                '--entrypoint','nginx','ownstack-offline-20261018-web','-g','daemon off;'],
                check=True,capture_output=True,timeout=15)
            result=subprocess.run(['docker','run','--rm','--pull','never',
                '--network','container:'+name,'--read-only','--cap-drop','ALL',
                '--security-opt','no-new-privileges','--memory','128m','--pids-limit','16',
                'ownstack-offline-20261018-api','python','-I','-B','-c',CLIENT],
                capture_output=True,text=True,timeout=30)
            if result.returncode:raise RuntimeError('Proxy controls unavailable')
            report=json.loads(result.stdout)
        except Exception as error:
            report={'passed':False,'error_type':type(error).__name__}
        finally:
            subprocess.run(['docker','rm','--force',name],capture_output=True,timeout=15)
        report.update(date=datetime.now(timezone.utc).isoformat(),new_inference_calls=0,
            database_used=False,public_ports=False,
            template_sha256=hashlib.sha256(template.encode()).hexdigest(),
            limits='Actual Nginx HTTP forwarding only; no TLS certificate, Caddy or public network test.')
        json.dump(report,output,indent=2);output.write('\n')
    print(json.dumps(report,indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
