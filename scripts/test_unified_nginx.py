"""Static checks on nginx/unified.conf. The live behaviour is checked by e2e/phase2/check_nginx.py."""

from __future__ import annotations

import re
from pathlib import Path

CONF = (Path(__file__).resolve().parents[1] / "nginx" / "unified.conf").read_text(encoding="utf-8")


def _server(name_variable: str) -> str:
    """The text of the server block whose server_name is ${name_variable}."""
    blocks = re.split(r"(?m)^server \{", CONF)[1:]
    found = [b for b in blocks if f"server_name ${{{name_variable}}};" in b]
    assert len(found) == 1, name_variable
    return found[0]


def test_saas_hosts_replace_the_client_supplied_forwarded_for_header() -> None:
    # The SaaS API scopes its rate limits by the first X-Forwarded-For value, so the edge must
    # overwrite that header instead of appending to whatever the client sent.
    for host in ("SAAS_WEB_HOST", "SAAS_API_HOST"):
        values = re.findall(r"proxy_set_header X-Forwarded-For (\S+);", _server(host))
        assert values == ["$remote_addr"], (host, values)


def test_every_spelling_of_the_sso_exchange_on_the_many_host_is_rate_limited() -> None:
    many = _server("MANY_HOST")
    for selector in (
        "= /auth/sso/exchange",
        "~* ^/auth/sso/exchange/?$",
        "= /api/auth/sso/exchange",
        "~* ^/api/(?<sso_path>auth/sso/exchange/?)$",
    ):
        match = re.search(
            r"(?m)^\s*location " + re.escape(selector) + r" \{(?P<body>[^}]*)\}", many
        )
        assert match, selector
        assert "limit_req zone=sso_exchange" in match["body"], selector
        assert "limit_req_status 429;" in match["body"], selector
