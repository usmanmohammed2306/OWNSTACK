"""Owned synthetic HTTP adapter, used only for isolated release checks."""
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from urllib.parse import unquote


def moment(value):
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def read(data):
    if data['actor_tenant_id'] != data['resource_tenant_id']:
        return 404, {}
    role=data['actor_role']
    if role=='contractor':
        grant=bool(data.get('grant_starts_at') and data.get('grant_expires_at') and not data.get('grant_revoked')
                   and moment(data['grant_starts_at'])<=moment(data['at'])<moment(data['grant_expires_at']))
        if not data['assigned'] and not grant:
            return 403, {}
        return 200, {'id':data['resource_id'],'title':'Synthetic project document'}
    if role in {'admin','engineer','member','manager','product_owner'}:
        return 200, {'id':data['resource_id'],'title':'Synthetic project document','internal_notes':'Synthetic private notes'}
    return 403, {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def do_GET(self):
        if self.path=='/health':
            self.send_response(200);self.end_headers();self.wfile.write(b'ready')
        else:
            self.send_response(404);self.end_headers();self.wfile.write(b'{}')

    def do_POST(self):
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=16384:raise ValueError('Bounded input required')
            data=json.loads(self.rfile.read(size))
            if unquote(self.path)!='/documents/'+data['resource_id']:
                status,body=404,{}
            else:status,body=read(data)
        except Exception:
            status,body=400,{}
        raw=json.dumps(body,separators=(',',':')).encode()
        self.send_response(status);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)


if __name__=='__main__':
    HTTPServer(('127.0.0.1',8765),Handler).serve_forever()
