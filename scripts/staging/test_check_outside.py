"""Tests for check_outside.py against a local fake edge (real TLS, fake answers)."""

from __future__ import annotations

import http.server
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import check_outside as co

HOSTS = ("many.test", "saas.test", "api.test")


def _certs(tmp: Path, days: int = 60) -> tuple[Path, Path, Path]:
    sh = (
        f"cd {tmp} && openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes "
        "-keyout ca.key -out ca.pem -days 30 -subj /CN=testca -addext basicConstraints=critical,CA:TRUE -addext keyUsage=critical,keyCertSign "
        "&& openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout s.key "
        "-out s.csr -subj /CN=many.test && printf 'subjectAltName=DNS:many.test,DNS:saas.test,DNS:api.test' > s.ext "
        f"&& openssl x509 -req -in s.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days {days} -extfile s.ext -out s.pem"
    )
    subprocess.run(sh, shell=True, check=True, capture_output=True)
    return tmp / "ca.pem", tmp / "s.pem", tmp / "s.key"


def _handler(leak: bool, hsts: bool, redirect_ok: bool):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a: object) -> None:
            pass

        def _send(self, code: int, body: str = "", headers: dict[str, str] | None = None) -> None:
            self.send_response(code)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode())

        def do_GET(self) -> None:
            if not self.server.is_tls:  # type: ignore[attr-defined]
                loc = f"https://{self.headers['Host']}{self.path}"
                self._send(301 if redirect_ok else 200, "", {"Location": loc})
            elif self.path in ("/health", "/ready"):
                self._send(200, "ok", {"Strict-Transport-Security": "max-age=1"} if hsts else {})
            else:
                self._send(200, "page", {"Strict-Transport-Security": "max-age=1"} if hsts else {})

        def do_POST(self) -> None:
            if leak and self.path == "/auth/sso/exchange":
                self._send(200, "{}")
            else:
                self._send(403, "denied at the edge\n", {"X-Edge-Deny": "1"})

    return H


class Fake:
    def __init__(self, tmp: Path, days: int = 60, **kw: bool) -> None:
        self.ca, pem, key = _certs(tmp, days)
        flags = {"leak": False, "hsts": True, "redirect_ok": True, **kw}
        h = _handler(**flags)
        self.https = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
        self.https.is_tls = True  # type: ignore[attr-defined]
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(pem, key)
        self.https.socket = ctx.wrap_socket(self.https.socket, server_side=True)
        self.http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
        self.http.is_tls = False  # type: ignore[attr-defined]
        for srv in (self.https, self.http):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.ctx = ssl.create_default_context(cafile=str(self.ca))

    def targets(self) -> dict[str, co.Target]:
        hp, pp = self.https.server_address[1], self.http.server_address[1]
        return {
            "many": co.Target(HOSTS[0], "127.0.0.1", hp, pp),
            "saas_web": co.Target(HOSTS[1], "127.0.0.1", hp, pp),
            "saas_api": co.Target(HOSTS[2], "127.0.0.1", hp, pp),
        }

    def close(self) -> None:
        for srv in (self.https, self.http):
            srv.shutdown()
            srv.server_close()


class CheckOutside(unittest.TestCase):
    def _run(self, **kw: bool) -> list[tuple[bool, str]]:
        days = int(kw.pop("days", 60))  # type: ignore[arg-type]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fake = Fake(Path(tmp.name), days, **kw)
        self.addCleanup(fake.close)
        return co.run(fake.targets(), 14, fake.ctx)

    def test_everything_correct_passes(self) -> None:
        results = self._run()
        self.assertTrue(all(ok for ok, _ in results), [t for ok, t in results if not ok])
        self.assertEqual(len(results), 17)

    def test_a_leaked_exchange_route_fails(self) -> None:
        results = self._run(leak=True)
        bad = [t for ok, t in results if not ok]
        self.assertTrue(any("/auth/sso/exchange" in t for t in bad), bad)

    def test_missing_hsts_fails(self) -> None:
        self.assertTrue(any(not ok and "HSTS" in t for ok, t in self._run(hsts=False)))

    def test_no_redirect_fails(self) -> None:
        self.assertTrue(any(not ok and "redirects" in t for ok, t in self._run(redirect_ok=False)))

    def test_untrusted_certificate_fails(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fake = Fake(Path(tmp.name))
        self.addCleanup(fake.close)
        results = co.run(fake.targets(), 14, ssl.create_default_context())  # no private CA
        self.assertTrue(any(not ok and "certificate" in t for ok, t in results))

    def test_short_lived_certificate_fails(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fake = Fake(Path(tmp.name), days=5)
        self.addCleanup(fake.close)
        results = co.run(fake.targets(), 14, fake.ctx)
        self.assertTrue(any(not ok and "days left" in t for ok, t in results))


if __name__ == "__main__":
    unittest.main()
