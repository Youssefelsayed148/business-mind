"""Mock of graph.facebook.com / graph.instagram.com (HTTPS, throwaway CA).
Records every request so the driver can assert the Meta boundary was reached.
Inspection endpoints: GET /__requests, POST /__reset. No real Meta traffic."""
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

LOG: list[dict] = []
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: object) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/__requests":
            with LOCK:
                return self._send(200, LOG)
        self._send(200, {"id": "mock", "data": []})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        if self.path == "/__reset":
            with LOCK:
                LOG.clear()
            return self._send(200, {"reset": True})
        parts = urlsplit(self.path)
        query = {k: ("<redacted>" if "token" in k else v) for k, v in parse_qsl(parts.query)}
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {"_unparsed": True}
        with LOCK:
            n = len(LOG) + 1
            LOG.append({"n": n, "host": self.headers.get("Host"), "path": parts.path, "query": query, "body": body})
        self._send(200, {
            "messaging_product": "whatsapp", "contacts": [{"input": "x", "wa_id": "x"}],
            "messages": [{"id": f"wamid.MOCK{n}"}], "recipient_id": "x", "message_id": f"mid.MOCK{n}",
        })

    def log_message(self, fmt: str, *args: object) -> None:
        print("mock-meta", self.command, self.headers.get("Host"), self.path.split("?")[0], flush=True)


server = ThreadingHTTPServer(("0.0.0.0", 443), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain("/pki/server.pem", "/pki/server.key")
server.socket = context.wrap_socket(server.socket, server_side=True)
print("mock-meta listening on 443", flush=True)
server.serve_forever()
