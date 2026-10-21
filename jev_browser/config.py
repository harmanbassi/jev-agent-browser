"""Environment configuration shared by the CLI and MCP adapters."""
from dataclasses import dataclass, field
import ipaddress
from urllib.parse import urlsplit

from .policy import URLPolicy
from .environment import get


def placeholder_key(value):
    """Recognize documentation placeholders without assuming a provider key format."""
    return value.strip().lower().startswith("replace-with-")


def flag(name):
    value = get(name, "0").lower()
    if value not in {"0", "1", "false", "true"}:
        raise ValueError(f"{name} must be 0 or 1")
    return value in {"1", "true"}


def endpoint(url, name, *, allow_http=False):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in ({"http", "https"} if allow_http else {"https"}) or not parsed.hostname
                or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
                or any(ord(c) < 33 for c in url) or "\\" in url):
            raise ValueError
        parsed.port
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a valid {'HTTP(S)' if allow_http else 'HTTPS'} URL without credentials or query parameters") from None
    return url.rstrip("/")


@dataclass(frozen=True)
class Settings:
    camofox_url: str = "http://127.0.0.1:9377"
    camofox_api_key: str = field(default="", repr=False)
    policy: URLPolicy = field(default_factory=URLPolicy)

    def __post_init__(self):
        if placeholder_key(self.camofox_api_key):
            raise ValueError("Replace the example CAMOFOX_ACCESS_KEY/CAMOFOX_API_KEY with your browser's actual key")
        endpoint(self.camofox_url, "CAMOFOX_URL", allow_http=True)
        parsed = urlsplit(self.camofox_url)
        try:
            local = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            local = parsed.hostname == "localhost"
        if parsed.scheme == "http" and not local and not flag("JEV_ALLOW_INSECURE_CAMOFOX"):
            raise ValueError("Remote Camofox needs HTTPS; use a tunnel or explicitly set JEV_ALLOW_INSECURE_CAMOFOX=1 on a trusted network")

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.camofox_api_key}"} if self.camofox_api_key else {}

    @classmethod
    def from_env(cls):
        hosts = tuple(h.strip().rstrip(".").lower() for h in get("JEV_ALLOWED_HOSTS", "").split(",") if h.strip())
        return cls(get("CAMOFOX_URL", "http://127.0.0.1:9377"),
                   get("CAMOFOX_ACCESS_KEY") or get("CAMOFOX_API_KEY", ""),
                   URLPolicy(flag("JEV_ALLOW_PRIVATE_URLS"), hosts))
