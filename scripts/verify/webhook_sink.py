#!/usr/bin/env python3
"""Local HTTPS webhook-sink receiver for the verify steps.

    webhook_sink.py <port> <cert.pem> <key.pem> <log.jsonl>

Answers every POST with 200 and appends one JSON line per request ({"t", "path", "headers", "body"}) to the log.
"""

from __future__ import annotations

import json
import ssl
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Sink(BaseHTTPRequestHandler):
    log_path = ""

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw
        line = {"t": time.time(), "path": self.path, "headers": dict(self.headers), "body": body}
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *_: object) -> None:
        pass


def main() -> None:
    port, cert, key, log = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    Sink.log_path = log
    server = ThreadingHTTPServer(("0.0.0.0", port), Sink)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
