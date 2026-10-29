"""Deliberately wrong synthetic release: missing contractor assignment check."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass

    def do_GET(self):
        self.send_response(200);self.end_headers();self.wfile.write(b'ready')

    def do_POST(self):
        try:
            data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            if data['actor_tenant_id']!=data['resource_tenant_id']:status,body=404,{}
            elif data['actor_role']=='contractor':
                status,body=200,{'id':data['resource_id'],'title':'Synthetic project document'}
            elif data['actor_role'] in {'admin','engineer','member','manager','product_owner'}:
                status,body=200,{'id':data['resource_id'],'title':'Synthetic project document','internal_notes':'Synthetic private notes'}
            else:status,body=403,{}
        except Exception:status,body=400,{}
        raw=json.dumps(body).encode();self.send_response(status);self.end_headers();self.wfile.write(raw)


if __name__=='__main__':HTTPServer(('127.0.0.1',8765),Handler).serve_forever()
