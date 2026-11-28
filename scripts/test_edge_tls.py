"""Phase 6A checks that run without Docker: the internal PKI really verifies (and fails for a wrong
name), and nginx/unified.conf is accepted by `nginx -t` in the dev mode and in the HTTPS + verified
upstream mode (skipped when nginx or openssl is missing). Live behaviour is checked on staging."""

from __future__ import annotations

import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOSTS = {"MANY_HOST": "many.test", "SAAS_WEB_HOST": "saas.test", "SAAS_API_HOST": "api.test"}


def _pki(tmp: Path) -> Path:
    pki = tmp / "pki"
    subprocess.run([str(ROOT / "scripts/tls/make_internal_pki.sh"), str(pki)], check=True, capture_output=True)
    return pki


@unittest.skipUnless(shutil.which("openssl"), "openssl missing")
class InternalPki(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pki = _pki(Path(self._tmp.name))

    def _serve_once(self, name: str) -> int:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.pki / f"{name}.pem", self.pki / f"{name}.key")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)

        def run() -> None:
            try:
                conn, _ = sock.accept()
                with ctx.wrap_socket(conn, server_side=True) as tls:
                    tls.recv(1)
            except (ssl.SSLError, OSError):
                pass
            finally:
                sock.close()

        threading.Thread(target=run, daemon=True).start()
        return sock.getsockname()[1]

    def _connect(self, port: int, server_name: str, cafile: Path | None) -> None:
        ctx = ssl.create_default_context(cafile=str(cafile) if cafile else None)
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with ctx.wrap_socket(raw, server_hostname=server_name) as tls:
                tls.send(b"x")

    def test_service_certificate_verifies_for_its_own_name_with_the_private_ca(self) -> None:
        self._connect(self._serve_once("many-api"), "many-api", self.pki / "ca.pem")

    def test_wrong_service_name_is_refused(self) -> None:
        with self.assertRaises(ssl.SSLCertVerificationError):
            self._connect(self._serve_once("many-api"), "saas-api", self.pki / "ca.pem")

    def test_without_the_private_ca_it_is_refused(self) -> None:
        with self.assertRaises(ssl.SSLCertVerificationError):
            self._connect(self._serve_once("saas-api"), "saas-api", None)

    def test_bundle_keeps_public_roots_and_adds_the_private_ca(self) -> None:
        bundle = (self.pki / "ca-bundle.pem").read_text()
        self.assertTrue(bundle.endswith((self.pki / "ca.pem").read_text()))
        self.assertGreater(bundle.count("BEGIN CERTIFICATE"), 2)

    def test_check_script_catches_a_swapped_certificate(self) -> None:
        check = [str(ROOT / "scripts/tls/check_internal_pki.sh"), str(self.pki)]
        self.assertEqual(subprocess.run(check, capture_output=True).returncode, 0)
        (self.pki / "many-api.pem").write_bytes((self.pki / "saas-api.pem").read_bytes())
        self.assertEqual(subprocess.run(check, capture_output=True).returncode, 1)

    def test_ca_key_is_not_next_to_the_mounted_files(self) -> None:
        self.assertFalse((self.pki / "ca.key").exists())
        self.assertEqual((self.pki / "ca-private").stat().st_mode & 0o777, 0o700)


@unittest.skipUnless(shutil.which("nginx") and shutil.which("openssl"), "nginx or openssl missing")
class NginxAcceptsTheTemplate(unittest.TestCase):
    def _nginx_t(self, mode: str) -> subprocess.CompletedProcess[str]:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        pki = _pki(tmp)
        (tmp / "le/live/edge").mkdir(parents=True)
        for src, dst in (("many-api.pem", "fullchain.pem"), ("many-api.key", "privkey.pem")):
            shutil.copy(pki / src, tmp / "le/live/edge" / dst)
        https = mode == "https"
        shutil.copytree(ROOT / ("nginx/edge/https" if https else "nginx/edge/http"), tmp / "edge")
        shutil.copytree(ROOT / ("nginx/upstream/tls" if https else "nginx/upstream/plain"), tmp / "upstream")
        text = (ROOT / "nginx/unified.conf").read_text()
        for key, value in HOSTS.items():
            text = text.replace("${" + key + "}", value)
        text = text.replace("${UPSTREAM_SCHEME}", "https" if https else "http")
        for name in ("many-api", "saas-api", "many-dashboard", "saas-web"):
            text = text.replace(f"server {name}:", "server 127.0.0.1:")
        confs = [text]
        if https:
            redirect = (ROOT / "nginx/redirect.conf.template").read_text()
            for key, value in HOSTS.items():
                redirect = redirect.replace("${" + key + "}", value)
            confs.append(redirect.replace("/var/www/certbot", str(tmp)))
        body = "\n".join(confs)
        swaps = (
            ("/etc/nginx/edge", str(tmp / "edge")),
            ("/etc/nginx/upstream", str(tmp / "upstream")),
            ("/etc/letsencrypt", str(tmp / "le")),
            ("/pki/ca.pem", str(pki / "ca.pem")),
        )
        for old, new in swaps:
            body = body.replace(old, new)
        for snippet in [*(tmp / "edge").iterdir(), *(tmp / "upstream").iterdir()]:
            content = snippet.read_text()
            for old, new in swaps:
                content = content.replace(old, new)
            snippet.write_text(content)
        (tmp / "nginx.conf").write_text(
            f"pid {tmp}/n.pid;\nerror_log {tmp}/e.log;\nevents {{}}\nhttp {{\n{body}\n}}\n"
        )
        return subprocess.run(
            ["nginx", "-t", "-p", str(tmp), "-c", str(tmp / "nginx.conf")],
            capture_output=True,
            text=True,
        )

    def test_dev_mode_is_valid(self) -> None:
        result = self._nginx_t("http")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_https_with_verified_upstreams_is_valid(self) -> None:
        result = self._nginx_t("https")
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
