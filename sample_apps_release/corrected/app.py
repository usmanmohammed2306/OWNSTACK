"""Owned corrected revision: shared document handling preserves tenant policy."""
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from urllib.parse import unquote


def moment(value):
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def current_grant(data):
    start,end=data.get('grant_starts_at'),data.get('grant_expires_at')
    return bool(start and end and not data.get('grant_revoked')
                and moment(start)<=moment(data['at'])<moment(end))


def read(data):
    if data['actor_tenant_id']!=data['resource_tenant_id']:
        return 404,{}
    role=data['actor_role']
    if role=='contractor':
        if not (data['assigned'] or current_grant(data)):
            return 403,{}
        return 200,{'id':data['resource_id'],'title':'Synthetic project document'}
    if role in {'admin','engineer','member','manager','product_owner'}:
        return 200,{'id':data['resource_id'],'title':'Synthetic project document','internal_notes':'Synthetic private notes'}
    return 403,{}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass

    def do_GET(self):
        status,body=(200,b'ready') if self.path=='/health' else (404,b'{}')
        self.send_response(status);self.end_headers();self.wfile.write(body)

    def do_POST(self):
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=16384:raise ValueError('Bounded input required')
            data=json.loads(self.rfile.read(size))
            status,body=read(data) if unquote(self.path)=='/documents/'+data['resource_id'] else (404,{})
        except Exception:status,body=400,{}
        raw=json.dumps(body,separators=(',',':')).encode()
        self.send_response(status);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)


if __name__=='__main__':
    HTTPServer(('127.0.0.1',8765),Handler).serve_forever()
