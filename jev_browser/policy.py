"""Shared rules for pages sent to an external model; not a network sandbox."""
from dataclasses import dataclass
import ipaddress
import re
import socket
from urllib.parse import parse_qsl, urlsplit


def addresses(host):
    return {entry[4][0] for entry in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}


@dataclass(frozen=True)
class URLPolicy:
    """Public HTTP(S) pages by default. Private pages require an explicit opt-in.

    DNS failures fail closed. A proxy may resolve DNS differently: enforce network
    isolation at the browser/proxy too. Metadata and URL credentials stay blocked
    even when private pages are allowed.
    """
    allow_private: bool = False
    allowed_hosts: tuple[str, ...] = ()

    def __call__(self, url):
        try:
            if not isinstance(url, str) or any(ord(c) < 33 for c in url) or "\\" in url:
                return "Blocked: malformed page URL."
            parsed = urlsplit(url)
            host = (parsed.hostname or "").rstrip(".").lower()
            if parsed.scheme not in {"http", "https"} or not host or not parsed.port and parsed.netloc.endswith(":"):
                return "Blocked: page URL must use HTTP or HTTPS with a valid host."
            if parsed.username is not None or parsed.password is not None:
                return "Blocked: page URL contains credentials."
            for name, _ in parse_qsl(parsed.query + "&" + parsed.fragment, keep_blank_values=True):
                normalized = re.sub(r"[^a-z0-9]", "", name.lower())
                if normalized in {"apikey", "accesstoken", "refreshtoken", "idtoken", "clientsecret"} or re.search(r"(^|[_-])(token|key|secret|password|passwd|authorization|signature|credential|code)($|[_-])", name, re.I):
                    return "Blocked: page URL contains a credential-like query parameter."
            if host in {"metadata.google.internal", "metadata", "instance-data.ec2.internal"}:
                return "Blocked: cloud metadata endpoint."
            if self.allowed_hosts and host not in self.allowed_hosts:
                return "Blocked: page host is outside the configured allowlist."
            try:
                ips = {ipaddress.ip_address(host)}
            except ValueError:
                ips = {ipaddress.ip_address(a) for a in addresses(host)}
            if not ips:
                return "Blocked: page host could not be resolved."
            for ip in ips:
                ip = getattr(ip, "ipv4_mapped", None) or ip
                if ip.is_link_local or str(ip) in {"100.100.100.200", "fd00:ec2::254"}:
                    return "Blocked: metadata or link-local address."
                if not self.allow_private and not ip.is_global:
                    return "Blocked: page host is not a public address; private pages require explicit opt-in."
            return None
        except (ValueError, OSError, UnicodeError):
            return "Blocked: invalid or unresolvable page host."


def action_block(action):
    """Conservative pause for known sensitive controls. This is not full DLP."""
    if action.get("sensitive") or re.search(
        r"\b(password|passcode|credit card|card number|cvv|social security|one.time.code)\b",
        action.get("label", ""), re.I,
    ) or (action.get("kind") == "click" and re.search(
        r"\b(sign\s*in|log\s*in|checkout|pay(?:ment)?|purchase|place order|delete|send message)\b",
        action.get("label", ""), re.I,
    )):
        return "sensitive_action"
    return None
