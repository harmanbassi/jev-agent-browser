"""Opt-in visual evidence. Pixels are ephemeral and never belong in task results."""
import base64
import binascii
from dataclasses import dataclass, field
import hashlib
import io
import math
import struct
import time
import uuid

from .budget import BudgetExceeded, current
from .config import flag
from .environment import get

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_REPLY_BYTES = 12 * 1024 * 1024
MODES = {"off", "auto", "always"}


class VisionUnavailable(ValueError):
    """A safe pause reason; messages must not contain page data or pixels."""


@dataclass(frozen=True)
class VisionSettings:
    enabled: bool = False
    mode: str = "auto"
    model: str = "typesafe/jev-1.14"
    max_calls: int = 4
    box: bool = False

    def __post_init__(self):
        if (type(self.enabled) is not bool or type(self.box) is not bool
                or not isinstance(self.mode, str) or self.mode not in MODES):
            raise ValueError("Invalid vision permission or mode")
        if type(self.max_calls) is not int or not 1 <= self.max_calls <= 32:
            raise ValueError("JEV_VISION_MAX_CALLS must be an integer from 1 to 32")
        if self.model != "typesafe/jev-1.14":
            raise ValueError("Vision currently supports the tested typesafe/jev-1.14 model")

    @classmethod
    def from_env(cls):
        try:
            maximum = int(get("JEV_VISION_MAX_CALLS", "4"))
        except (TypeError, ValueError):
            raise ValueError("JEV_VISION_MAX_CALLS must be an integer from 1 to 32") from None
        return cls(flag("JEV_VISION_ENABLED"), get("JEV_VISION_MODE", "auto"),
                   get("JEV_VISION_MODEL", "typesafe/jev-1.14"), maximum, flag("JEV_VISION_BOX"))

    def resolve(self, mode=None, require=False):
        if mode is not None and (not isinstance(mode, str) or mode not in MODES):
            raise ValueError("vision must be off, auto or always")
        if type(require) is not bool:
            raise ValueError("require_visual must be a boolean")
        mode = self.mode if mode is None else mode
        if not self.enabled or self.mode == "off" or mode == "off":
            if require or mode == "always":
                raise VisionUnavailable("vision_disabled")
            return "off"
        dependencies()
        return mode


def dependencies():
    try:
        from PIL import Image
    except ImportError:
        raise VisionUnavailable("vision_dependency_missing: install jev-browser with the vision extra") from None
    return Image


@dataclass
class VisionRun:
    settings: VisionSettings
    required: bool = False
    calls: int = 0
    captures: int = 0
    uploaded_bytes: int = 0
    escalations: int = 0
    verified: bool = False
    completion_probability: float | None = None
    models: list = field(default_factory=list)

    def request(self, frame):
        if self.calls >= self.settings.max_calls:
            raise BudgetExceeded("vision_budget")
        if budget := current.get():
            budget.check()
        self.calls += 1
        self.uploaded_bytes += len(frame.pixels)

    def capture(self):
        if budget := current.get():
            budget.check()
        if self.captures >= self.settings.max_calls * 3:
            raise BudgetExceeded("vision_capture_budget")
        self.captures += 1

    def summary(self):
        return {"calls": self.calls, "captures": self.captures, "uploaded_bytes": self.uploaded_bytes,
                "escalations": self.escalations, "required": self.required, "verified": self.verified,
                "models": list(dict.fromkeys(self.models)), "completion_probability": self.completion_probability}


@dataclass(repr=False)
class Frame:
    state: dict
    safe: dict
    capture_id: str
    pixels: bytes
    size: tuple
    source_size: tuple
    scale: float
    offset: tuple
    scale_y: float = 1.0
    received: float = field(default_factory=time.monotonic)

    def __repr__(self):
        return f"Frame(capture_id={self.capture_id!r}, size={self.size!r})"

    @classmethod
    def decode(cls, reply, snapshot_hash):
        try:
            if reply["protocol"] != 1 or reply["snapshotHash"] != snapshot_hash or reply["masked"] is not True:
                raise ValueError
            capture_id = str(uuid.UUID(reply["captureId"]))
            state, safe = reply["snapshot"], reply["safe"]
            if (not isinstance(state, dict) or not isinstance(safe, dict) or safe["url"] != state["url"]
                    or not all(isinstance(safe[k], str) for k in ("url", "title", "text"))
                    or not isinstance(safe["actions"], list)):
                raise ValueError
            if (not all(k in state for k in ("marker", "page_key", "guards", "scroll", "text", "title"))
                    or not isinstance(state["guards"], dict) or not isinstance(state["scroll"], dict)
                    or not isinstance(state["actions"], list) or len(state["actions"]) > 254
                    or not all(type(state[k]) is int for k in ("w", "h"))):
                raise ValueError
            for action in state["actions"]:
                if (not isinstance(action, dict) or not isinstance(action.get("id"), str)
                        or action.get("kind") not in {"click", "fill", "select", "scroll", "wait"}):
                    raise ValueError
                if action["kind"] in {"click", "fill", "select"}:
                    if type(action.get("node")) is not int or not isinstance(action.get("label"), str):
                        raise ValueError
                    if not all(type(action["rect"][k]) in (int, float) and math.isfinite(action["rect"][k])
                               for k in ("x", "y", "w", "h")) or min(action["rect"]["w"], action["rect"]["h"]) <= 0:
                        raise ValueError
            raw_actions = {a["id"]: a for a in state["actions"]}
            if any(a["id"] not in raw_actions or a.get("node") != raw_actions[a["id"]].get("node")
                   or a["kind"] != raw_actions[a["id"]]["kind"] for a in safe["actions"]):
                raise ValueError
            image = reply["image"]
            if image["format"] != "png" or len(image["data"]) > (MAX_IMAGE_BYTES + 2) // 3 * 4:
                raise ValueError
            raw = base64.b64decode(image["data"], validate=True)
            if len(raw) > MAX_IMAGE_BYTES or raw[:8] != b"\x89PNG\r\n\x1a\n":
                raise ValueError
            width, height = struct.unpack(">II", raw[16:24])
            if not (0 < width <= 4096 and 0 < height <= 4096) or (width, height) != (state["w"], state["h"]):
                raise ValueError
            Image = dependencies()
            with Image.open(io.BytesIO(raw)) as original:
                if original.format != "PNG" or getattr(original, "n_frames", 1) != 1:
                    raise ValueError
                original.load()
                image = original.convert("RGB")
            image.thumbnail((1568, 1568), Image.Resampling.LANCZOS)
            scaled = image.size
            size = (max(280, scaled[0]), max(280, scaled[1]))
            offset = ((size[0] - scaled[0]) // 2, (size[1] - scaled[1]) // 2)
            canvas = Image.new("RGB", size, "black")
            canvas.paste(image, offset)
            data = io.BytesIO()
            canvas.save(data, format="PNG")
            return cls(state, safe, capture_id, data.getvalue(), size, (width, height),
                       scaled[0] / width, offset, scaled[1] / height)
        except VisionUnavailable:
            raise
        except (KeyError, TypeError, ValueError, OSError, struct.error, binascii.Error):
            raise VisionUnavailable("vision_invalid_observation") from None

    def image_part(self):
        return {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(self.pixels).decode()}}

    def rect(self, action):
        r = action["rect"]
        return {"x": r["x"] * self.scale + self.offset[0], "y": r["y"] * self.scale_y + self.offset[1],
                "w": r["w"] * self.scale, "h": r["h"] * self.scale_y}

    def unchanged(self, other, action=None):
        if self.source_size != other.source_size or time.monotonic() - self.received > 30:
            return False
        if action is None:
            return hashlib.sha256(self.pixels).digest() == hashlib.sha256(other.pixels).digest()
        r = self.rect(action)
        if not all(type(v) in (int, float) and math.isfinite(v) for v in r.values()):
            return False
        box = (max(0, math.floor(r["x"])), max(0, math.floor(r["y"])),
               min(self.size[0], math.ceil(r["x"] + r["w"])), min(self.size[1], math.ceil(r["y"] + r["h"])))
        if box[0] >= box[2] or box[1] >= box[3]:
            return False
        Image = dependencies()
        with Image.open(io.BytesIO(self.pixels)) as before, Image.open(io.BytesIO(other.pixels)) as after:
            return before.crop(box).tobytes() == after.crop(box).tobytes()


def validate_box(answer, presence, frame, action):
    try:
        values = answer["box"]
        top, bottom, left, right = (values[k] for k in ("top", "bottom", "left", "right"))
        numbers = [top, bottom, left, right, answer["confidence"], presence["noul"]]
        if not all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in numbers):
            raise ValueError
        if not (top < bottom and left < right and answer["confidence"] >= 0.8 and presence["noul"] >= 0.95):
            raise ValueError
        x, y = (left + right) / 2 * frame.size[0], (top + bottom) / 2 * frame.size[1]
        nodes = set()
        for candidate in frame.safe["actions"]:
            if "rect" not in candidate or candidate.get("node") is None:
                continue
            r = frame.rect(candidate)
            if r["x"] <= x <= r["x"] + r["w"] and r["y"] <= y <= r["y"] + r["h"]:
                nodes.add(candidate["node"])
        if nodes != {action["node"]}:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise VisionUnavailable("vision_target_ambiguous") from None
