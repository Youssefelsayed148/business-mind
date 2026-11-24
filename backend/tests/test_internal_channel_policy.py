import pytest

from app.services import internal_channel_policy as policy


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(policy, "HOSTS", frozenset({"saas-api", "many-api"}))


@pytest.mark.parametrize("host", ["saas-api", "many-api"])
def test_exact_internal_host(host):
    policy.check_addresses(f"http://{host}:8000", ["172.30.0.4", "fd00::4"])


@pytest.mark.parametrize("url", [
    "http://SaAs-Api:8000", "http://saas-api.:8000", "http://saas-api..:8000",
    "http://saas-api@evil.example", "http://@saas-api", "http://saas-api:pass@evil.example",
    "http://saas-api.evil.example", "http://other-api", "http://prefix-saas-api",
    "http://127.0.0.1", "http://10.0.0.4", "http://8.8.8.8", "http://[fd00::1]",
    "http://2130706433", "http://0x7f000001", "http://0177.0.0.1",
    "http://saas-api%2eevil.example", "http://saas-api\\@evil.example",
    "http://saas-api\n", "http://saas-api?x=1", "http://saas-api#fragment",
])
def test_private_target_aliases_and_tricks_rejected(url):
    with pytest.raises(ValueError):
        policy.check_addresses(url, ["172.30.0.4"])


@pytest.mark.parametrize("address", [
    "127.0.0.1", "::1", "169.254.169.254", "fe80::1", "0.0.0.0", "::",
    "224.0.0.1", "ff02::1", "192.0.2.1", "::ffff:172.30.0.4",
])
def test_special_ranges_not_granted(address):
    with pytest.raises(ValueError):
        policy.check_addresses("http://saas-api", [address])


def test_mixed_dns_fails_closed():
    with pytest.raises(ValueError):
        policy.check_addresses("http://saas-api", ["172.30.0.4", "169.254.169.254"])
    with pytest.raises(ValueError):
        policy.check_addresses("http://saas-api", [])


@pytest.mark.parametrize("raw", [
    "*", "*.example", ".example", "SAAS-API", "saas-api.", "127.0.0.1", "[::1]",
    "saas-api@evil.example", "saas-api:8000", "saas-api,", "saas-api,saas-api",
    "localhost", "svc.local", "saas-api, many-api",
    "saas-api.example", "a.b", "saas-api.internal", "saas-api,many-api.example",
    "many-api.", "1saas", "-saas", "saas-",
])
def test_bad_setting_rejected(raw):
    with pytest.raises(ValueError):
        policy.parse_hosts(raw)


def test_empty_and_production_tls(monkeypatch):
    assert policy.parse_hosts("") == frozenset()
    monkeypatch.setattr(policy, "HOSTS", frozenset())
    assert not policy.enabled()
    with pytest.raises(ValueError):
        policy.parse_url("http://saas-api", require_https=True)
    assert policy.parse_url("https://saas-api", require_https=True) == "saas-api"


@pytest.mark.parametrize(
    "addresses",
    [
        ["8.8.8.8", "172.30.0.4"],
        ["172.30.0.4", "8.8.8.8"],
        ["fd00::4", "2001:4860:4860::8888"],
        ["172.30.0.4", "2001:4860:4860::8888"],
    ],
)
def test_listed_host_mixed_public_and_private_rejected(addresses):
    with pytest.raises(ValueError):
        policy.check_addresses("http://saas-api:8000", addresses)


@pytest.mark.parametrize("addresses", [["8.8.8.8"], ["2001:4860:4860::8888"], ["8.8.8.8", "1.1.1.1"]])
def test_listed_host_public_only_rejected(addresses):
    with pytest.raises(ValueError):
        policy.check_addresses("http://saas-api:8000", addresses)


@pytest.mark.parametrize(
    "addresses",
    [["172.30.0.4"], ["10.1.2.3", "192.168.0.9"], ["fd00::4"], ["172.30.0.4", "fd00::4"]],
)
def test_listed_host_private_only_allowed(addresses):
    policy.check_addresses("http://saas-api:8000", addresses)


def test_unlisted_host_private_rejected_even_with_public(monkeypatch):
    with pytest.raises(ValueError):
        policy.check_addresses("http://other-svc:8000", ["172.30.0.4", "8.8.8.8"])


def test_public_dns_still_allowed():
    policy.check_addresses("https://public.example", ["8.8.8.8"])


def test_many_validation_integration(monkeypatch):
    from app.services import saas_delegation_service as svc
    monkeypatch.setattr(svc.settings, "APP_ENV", "production")
    monkeypatch.setattr(svc.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("172.30.0.4", 443))])
    assert svc.validate_base_url("https://saas-api") == "https://saas-api"
    with pytest.raises(svc.DelegationConfigError):
        svc.validate_base_url("https://other-api")
    monkeypatch.setattr(policy, "HOSTS", frozenset())
    with pytest.raises(svc.DelegationConfigError):
        svc.validate_base_url("https://saas-api")


def test_redirect_not_followed(monkeypatch):
    import httpx
    from app.services import saas_forwarder
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://other-api/steal"})
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    with saas_forwarder.new_http_client() as client:
        response = client.post("http://saas-api/start", content=b"fake")
    assert response.status_code == 302
    assert seen == ["http://saas-api/start"]


def test_startup_validation_and_warning():
    import subprocess
    import sys
    command = [sys.executable, "-c", "import runpy, sys; runpy.run_path(sys.argv[1])", policy.__file__]
    result = subprocess.run(command, env={policy.SETTING: "many-api"}, capture_output=True, text=True)
    assert result.returncode == 0
    assert "Internal channel host allowlist enabled: many-api" in result.stderr
    result = subprocess.run(command, env={policy.SETTING: "*"}, capture_output=True, text=True)
    assert result.returncode != 0
    result = subprocess.run(command, env={policy.SETTING: ""}, capture_output=True, text=True)
    assert result.returncode == 0
    assert "allowlist enabled" not in result.stderr
