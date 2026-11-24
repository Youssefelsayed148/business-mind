"""One-shot: throwaway CA + server cert for the mocked Meta hosts, plus random
per-run fake secrets. Everything is written to a Docker volume (never to git)."""
import datetime
import json
import secrets
import sys
from pathlib import Path

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
HOSTS = ["graph.facebook.com", "graph.instagram.com"]
now = datetime.datetime.now(datetime.timezone.utc)


def name(common: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])


ca_key = ec.generate_private_key(ec.SECP256R1())
ca = (
    x509.CertificateBuilder().subject_name(name("p2e2e throwaway CA")).issuer_name(name("p2e2e throwaway CA"))
    .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
    .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=2))
    .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
    .sign(ca_key, hashes.SHA256())
)
key = ec.generate_private_key(ec.SECP256R1())
cert = (
    x509.CertificateBuilder().subject_name(name(HOSTS[0])).issuer_name(ca.subject)
    .public_key(key.public_key()).serial_number(x509.random_serial_number())
    .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=2))
    .add_extension(x509.SubjectAlternativeName([x509.DNSName(h) for h in HOSTS]), critical=False)
    .sign(ca_key, hashes.SHA256())
)
pem = serialization.Encoding.PEM
(out / "ca.pem").write_bytes(ca.public_bytes(pem))
(out / "server.pem").write_bytes(cert.public_bytes(pem))
(out / "server.key").write_bytes(
    key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
)
env = {
    "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "CHANNEL_SECRET_ENCRYPTION_KEYS": Fernet.generate_key().decode(),
    "JWT_SECRET": secrets.token_hex(24),
    "APP_SECRET_KEY": secrets.token_hex(24),
    "META_APP_SECRET": "fake-meta-" + secrets.token_hex(16),
    "META_WEBHOOK_VERIFY_TOKEN": "fake-verify-" + secrets.token_hex(8),
    "SECRET_INSTAGRAM": "fake-conn-ig-" + secrets.token_hex(20),
    "SECRET_WHATSAPP": "fake-conn-wa-" + secrets.token_hex(20),
    "SECRET_MESSENGER": "fake-conn-fb-" + secrets.token_hex(20),
    "SSL_CERT_FILE": str(out / "ca.pem"),
    "REQUESTS_CA_BUNDLE": str(out / "ca.pem"),
    "CURL_CA_BUNDLE": str(out / "ca.pem"),
}
(out / "env.json").write_text(json.dumps(env))
for path in out.iterdir():
    path.chmod(0o644)
print("pki + fake per-run secrets written to", out)
