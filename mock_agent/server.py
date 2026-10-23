# STUB(VOICE-03): placeholder for the mock EMI agent; VOICE-03 replaces it with the pareeksha-audio-v1 server.
from http.server import BaseHTTPRequestHandler, HTTPServer


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        ok = self.path == "/health"
        self.send_response(200 if ok else 404)
        self.end_headers()
        self.wfile.write(b'{"status":"ok","placeholder":true}' if ok else b"")


HTTPServer(("0.0.0.0", 8765), H).serve_forever()
