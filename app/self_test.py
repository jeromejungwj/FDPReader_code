"""배포본 점검. FDPREADER_SELF_TEST=결과.json 으로 PDF 를 열면 첫 화면과 감시 프로세스를 보고 종료함.

실제 커서는 잠그지 않음 (감시 프로세스에는 "잠금 없음"만 보냄).
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QTimer

from features.sign import cursor_guard

LIMIT = 20.0


def watchdog_starts() -> bool:
    """떠서 입력을 기다리다가, 입력이 닫히면 스스로 끝나야 함."""
    process = subprocess.Popen(
        cursor_guard.watchdog_command(),
        stdin=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    process.stdin.write(b"-")
    process.stdin.flush()
    time.sleep(1.0)
    waiting = process.poll() is None
    process.stdin.close()
    try:
        process.wait(5)
    except subprocess.TimeoutExpired:
        process.kill()
        return False
    return waiting and process.returncode == 0


def _sharp(view) -> bool:
    if view is None or view._layout is None:
        return False
    key = view._scale_key()
    slots = view.visible_slots()
    return bool(slots) and all(
        view._tiles.get(("tile", s.pno, key, view.theme, *at))
        for s in slots
        for at in view._tile_range(s, key)
    )


def run(app, controller, out: str) -> None:
    began = time.monotonic()

    def check() -> None:
        window = controller.windows[0] if controller.windows else None
        tab = window.current() if window else None
        view = tab.view if tab else None
        rendered = _sharp(view)
        if not rendered and time.monotonic() - began < LIMIT:
            QTimer.singleShot(100, check)
            return
        result = {
            "rendered": rendered,
            "pages": tab.doc.page_count if tab else 0,
            "seconds": round(time.monotonic() - began, 2),
            "watchdog": watchdog_starts(),
        }
        Path(out).write_text(json.dumps(result), encoding="utf-8")
        app.quit()

    QTimer.singleShot(100, check)
