"""A real HTTPS webhook receiver on localhost, for the integrations acceptance tests and demo.

It verifies the HMAC signature the way a customer would (``pareeksha.integrations.signing``),
records every request, and de-duplicates on ``X-Pareeksha-Event-Id`` (what a well-behaved receiver
does for an at-least-once sender). Behaviour per request can be steered: respond with a given
status, or hold the response until released (to kill the sender mid-request).

    python -m tests.integration.webhook_receiver <port> <cert_dir> <signing_secret>
"""

from __future__ import annotations

import datetime
import ipaddress
import json
import ssl
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from pareeksha.integrations.signing import SignatureError, verify_signature


def make_certificate(directory: Path) -> tuple[Path, Path]:
    """A self-signed certificate for ``localhost`` / 127.0.0.1; returns ``(cert, key)`` paths."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "receiver.crt", directory / "receiver.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@dataclass
class Received:
    path: str
    headers: dict[str, str]
    body: bytes
    signature_ok: bool

    @property
    def event_id(self) -> str:
        return str(json.loads(self.body).get("event_id", ""))


@dataclass
class Receiver:
    """State shared with the request handler thread."""

    signing_secret: str
    requests: list[Received] = field(default_factory=list)
    statuses: list[int] = field(default_factory=list)  # consumed one per request, then 200
    hold: threading.Event | None = None  # when set (cleared), responses wait for it to be set
    arrived: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def unique_event_ids(self) -> set[str]:
        return {r.event_id for r in self.requests} - {""}


def _handler(state: Receiver) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            headers = {k: v for k, v in self.headers.items()}
            try:
                verify_signature(headers, body, state.signing_secret)
                signature_ok = True
            except SignatureError:
                signature_ok = False
            with state._lock:
                state.requests.append(Received(self.path, headers, body, signature_ok))
                status = state.statuses.pop(0) if state.statuses else 200
            state.arrived.set()
            if state.hold is not None:
                state.hold.wait(60)
            if not signature_ok:
                status = 401
            payload = json.dumps({"received": signature_ok}).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the sender was killed while we held the response

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


class ReceiverServer:
    def __init__(self, cert_dir: Path, signing_secret: str, port: int = 0) -> None:
        self.state = Receiver(signing_secret)
        self.cert, key = make_certificate(cert_dir)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, key)
        self._server = ThreadingHTTPServer(("127.0.0.1", port), _handler(self.state))
        self._server.socket = context.wrap_socket(self._server.socket, server_side=True)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        return f"https://localhost:{self.port}/hook"

    def start(self) -> ReceiverServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        if self.state.hold is not None:
            self.state.hold.set()
        self._server.shutdown()
        self._server.server_close()


if __name__ == "__main__":
    server = ReceiverServer(Path(sys.argv[2]), sys.argv[3], int(sys.argv[1])).start()
    print(f"receiver on {server.url} cert {server.cert}", flush=True)
    threading.Event().wait()
