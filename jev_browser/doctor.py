"""Read-only diagnostics by default; never print keys or proxy credentials."""
import requests

from .camofox import Camofox, CamofoxAuthError, CamofoxError, StalePage, Page, READ_STATE
from .config import Settings, endpoint, flag, placeholder_key
from .jev import api_key, DECISIONS_URL, CHAT_URL, ModelError
from .budget import BudgetExceeded
from .environment import get


def diagnose(*, probe=False, vision=False, vision_model_probe=False):
    checks = []

    def add(name, ok, message):
        checks.append({"name": name, "ok": ok, "message": message})

    try:
        settings = Settings.from_env()
        add("configuration", True, "Configuration is valid")
    except ValueError as e:
        return {"ok": False, "checks": [{"name": "configuration", "ok": False, "message": str(e)}]}
    key = api_key()
    configured = bool(key.strip()) and not placeholder_key(key)
    add("model_key", configured, "Key configured; provider access not verified" if configured else
        "Set JEV_OPENROUTER_KEY or OPENROUTER_API_KEY to your actual OpenRouter key; replace example placeholders")
    try:
        for name, default in (("JEV_URL", DECISIONS_URL), ("JEV_TEXT_URL", CHAT_URL)):
            endpoint(get(name, default), name, allow_http=flag("JEV_ALLOW_INSECURE_MODEL_URLS"))
        add("model_endpoints", True, "Endpoints valid; no paid model call made")
    except ValueError as e:
        add("model_endpoints", False, str(e))
    try:
        response = requests.get(settings.camofox_url.rstrip("/") + "/health", headers=settings.headers,
                                timeout=5, allow_redirects=False)
        if response.status_code in {401, 403}:
            add("camofox", False, "Camofox rejected browser authentication; check CAMOFOX_ACCESS_KEY/CAMOFOX_API_KEY")
        else:
            data = response.json()
            healthy = response.status_code == 200 and isinstance(data, dict) and (
                data.get("ok") is True or data.get("status") in ("ok", "healthy"))
            add("camofox", healthy, "Browser reachable" if healthy else "Check Camofox health and authentication")
    except (requests.RequestException, ValueError):
        add("camofox", False, "Cannot read Camofox health; check CAMOFOX_URL and start Camofox")
    visual = None
    if vision or vision_model_probe:
        from .vision import VisionSettings, VisionRun
        try:
            import hashlib
            visual = VisionRun(VisionSettings.from_env(), True)
            visual.settings.resolve("always", True)
            capabilities = Camofox(settings.camofox_url, "doctor", None, headers=settings.headers)._request(
                "get", "/jev/vision", reply_limit=16384)
            valid = (isinstance(capabilities, dict) and capabilities.get("protocol") == 1 and capabilities.get("masked") is True
                     and capabilities.get("snapshotHash") == hashlib.sha256(READ_STATE.encode()).hexdigest())
            add("vision", valid, "Masked capture protocol compatible; no image uploaded" if valid else
                "Rebuild Camofox from this checkout; masked capture protocol does not match")
            if not valid:
                visual = None
        except (ValueError, CamofoxError, StalePage) as e:
            add("vision", False, str(e))
            visual = None
    if (probe or vision or vision_model_probe) and configured:
        cf = None
        opened = False
        try:
            import uuid
            identity = "jev-doctor-" + uuid.uuid4().hex
            cf = Camofox(settings.camofox_url, identity, None, headers=settings.headers)
            cf = Camofox.open(settings.camofox_url, identity, identity, "https://example.com",
                              headers=settings.headers, guard=settings.policy)
            opened = True
            add("evaluate", cf.evaluate("1+1") == 2, "Checked /tabs and /evaluate on a throwaway tab")
            if visual is not None:
                frame = Page(cf).observe_vision("https://example.com/", visual)
                add("masked_capture", True, "Captured a masked throwaway viewport; pixels were not saved")
                if vision_model_probe:
                    from .jev import verify_visual
                    verified = verify_visual(frame, "The page visibly explains that this domain is for documentation examples", visual)
                    add("vision_model", verified, "Paid image request completed; resolved model: " +
                        ", ".join(visual.models))
        except (ValueError, ModelError, BudgetExceeded) as e:
            add("vision", False, str(e))
        except CamofoxAuthError as e:
            add("authentication", False, str(e))
            if not opened:
                cf = None  # Rejected creation allocated no identity to clean up.
        except (CamofoxError, StalePage) as e:
            add("evaluate", False, str(e) + "; check Camofox evaluate configuration/version")
        finally:
            if cf:
                try:
                    if cf.close_session() is False:
                        add("cleanup", False, "Browser context closed; legacy server denied saved-profile reset; check CAMOFOX_API_KEY")
                except CamofoxAuthError as e:
                    add("cleanup", False, str(e))
                except (CamofoxError, StalePage):
                    add("cleanup", False, "Doctor session cleanup failed; check browser idle reaper")
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
