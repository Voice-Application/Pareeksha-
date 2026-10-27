"""Local https webhook sink for V6: logs one JSON line per POST (event id, signature header, time), answers 200."""

import json
import ssl
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = sys.argv[1]


class Sink(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {}
        row = {
            "t": time.strftime("%FT%TZ", time.gmtime()),
            "path": self.path,
            "headers": {k: v for k, v in self.headers.items() if k.lower().startswith("x-pareeksha")},
            "event_id": payload.get("event_id") or payload.get("id"),
            "type": payload.get("type"),
            "call_id": (payload.get("payload") or payload.get("data") or {}).get("call_id"),
        }
        with open(LOG, "a") as f:
            f.write(json.dumps(row) + "\n")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a: object) -> None:
        pass


ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(sys.argv[2], sys.argv[3])
srv = HTTPServer(("0.0.0.0", 18443), Sink)
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
srv.serve_forever()
