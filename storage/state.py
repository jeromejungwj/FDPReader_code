"""설정, 최근 문서, 읽던 위치, 세션."""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path

from . import files

log = logging.getLogger(__name__)

DEFAULTS: dict = {
    "language": "",  # 비우면 OS 언어
    "theme": "light",
    "color": "#ffe14d",
    "text_size": 12,
    "sign_width": 1,
    "sign_color": 0,
    "sign_as_ink": False,
    "notice_shown": False,
    "recent": [],  # {"path", "pinned"}
    "positions": {},  # 경로 → 보기 상태
    "session": {"files": [], "active": 0},
    "geometry": "",
}

MAX_RECENT = 20
MAX_POSITIONS = 500


def key_of(path) -> str:
    return os.path.normcase(os.path.abspath(path))


class State:
    def __init__(self, path: Path | None = None):
        self.path = path or files.data_dir() / "state.json"
        self.data = copy.deepcopy(DEFAULTS)
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
            for key, value in stored.items():
                if key in self.data and isinstance(value, type(self.data[key])):
                    self.data[key] = value
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            log.exception("설정을 읽지 못해 기본값을 사용함")

    def __getitem__(self, key: str):
        return self.data[key]

    def __setitem__(self, key: str, value) -> None:
        self.data[key] = value

    def save(self) -> None:
        try:
            raw = json.dumps(self.data, ensure_ascii=False, indent=1).encode("utf-8")
            files.write_bytes(self.path, raw)
        except OSError:
            log.exception("설정을 저장하지 못함")

    def add_recent(self, path) -> None:
        path = os.path.abspath(path)
        items = self.data["recent"]
        old = next((r for r in items if key_of(r["path"]) == key_of(path)), None)
        if old:
            items.remove(old)
        items.insert(0, {"path": path, "pinned": bool(old and old.get("pinned"))})
        loose = [r for r in items if not r.get("pinned")][MAX_RECENT:]
        self.data["recent"] = [r for r in items if r not in loose]

    def recent(self) -> list[dict]:
        return sorted(self.data["recent"], key=lambda r: not r.get("pinned"))

    def toggle_pin(self, path) -> None:
        for item in self.data["recent"]:
            if key_of(item["path"]) == key_of(path):
                item["pinned"] = not item.get("pinned")

    def position(self, path) -> dict:
        return self.data["positions"].get(key_of(path), {})

    def set_position(self, path, value: dict) -> None:
        positions = self.data["positions"]
        positions.pop(key_of(path), None)
        positions[key_of(path)] = value
        while len(positions) > MAX_POSITIONS:
            del positions[next(iter(positions))]
