"""Explicit internal-channel policy; an empty setting selects legacy behavior."""

import ipaddress
import logging
import os
import re
from urllib.parse import urlsplit

SETTING = "CHANNEL_INTERNAL_ALLOWED_HOSTS"
_LABEL = re.compile(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_PRIVATE = tuple(
    ipaddress.ip_network(value)
    for value in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "fc00::/7",
    )
)


def parse_hosts(raw: str) -> frozenset[str]:
    if not raw:
        return frozenset()
    entries = raw.split(",")
    for host in entries:
        # Single-label service names only: no dots, so no DNS suffix can be granted.
        if not _LABEL.fullmatch(host) or host == "localhost":
            raise ValueError(
                "Invalid CHANNEL_INTERNAL_ALLOWED_HOSTS: use single-label service names only"
            )
    if len(entries) != len(set(entries)):
        raise ValueError("Duplicate CHANNEL_INTERNAL_ALLOWED_HOSTS entry")
    return frozenset(entries)


HOSTS = parse_hosts(os.environ.get(SETTING, ""))
if HOSTS:
    logging.getLogger(__name__).warning(
        "Internal channel host allowlist enabled: %s", ",".join(sorted(HOSTS))
    )


def enabled() -> bool:
    return bool(HOSTS)


def parse_url(raw: str, *, require_https: bool = False) -> str:
    # Deliberately reject aliases/spellings rather than normalize them into a grant.
    if not raw or any(ord(char) <= 32 or ord(char) >= 127 for char in raw):
        raise ValueError("Channel URL must be ASCII without whitespace or controls")
    parsed = urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Invalid channel URL")
    if require_https and parsed.scheme != "https":
        raise ValueError("Channel URL must use HTTPS in production")
    if (
        parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
        or "%" in parsed.netloc
        or "\\" in raw
        or "?" in raw
        or "#" in raw
    ):
        raise ValueError("Channel URL must not include credentials, escapes, query or fragment")
    host = parsed.hostname
    # Reject every IP literal and alternate numeric encoding under the opt-in policy.
    if (
        host != host.lower()
        or not all(_LABEL.fullmatch(label) for label in host.split("."))
        or parsed.netloc.split(":", 1)[0] != host
    ):
        raise ValueError("Channel URL must use a canonical lowercase DNS hostname")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid channel URL port")
    return host


def check_addresses(raw: str, addresses: list[str]) -> None:
    host = parse_url(raw)
    if not addresses:
        raise ValueError("Channel host resolved to no addresses")
    for value in addresses:
        address = ipaddress.ip_address(value)
        if address.is_global and not (address.is_multicast or address.is_reserved):
            continue
        if host not in HOSTS or not any(address in subnet for subnet in _PRIVATE):
            raise ValueError("Channel host resolved to a forbidden address")
