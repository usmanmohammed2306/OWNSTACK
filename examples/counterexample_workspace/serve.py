"""Fixed owned HTTP adapter. Run only in the reviewed disposable executor."""
from http.server import BaseHTTPRequestHandler,HTTPServer
import json
import sys
from pathlib import Path
from urllib.parse import unquote
sys.path.insert(0,str(Path(__file__).resolve().parent))
from customer_policy import read


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.send_response(200 if self.path=='/health' else 404)
        self.end_headers();self.wfile.write(b'ready' if self.path=='/health' else b'{}')
    def do_POST(self):
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16384:raise ValueError('Bounded input required')
            value=json.loads(self.rfile.read(length))
            status,body=read(value) if unquote(self.path)=='/documents/'+value['resource_id'] else (404,{})
        except Exception:status,body=400,{}
        raw=json.dumps(body).encode();self.send_response(status)
        self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)


if __name__=='__main__':HTTPServer(('127.0.0.1',8765),Handler).serve_forever()
