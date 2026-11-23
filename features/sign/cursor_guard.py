"""서명 중 커서 고정. 어떤 경우에도 풀리도록 감시 프로세스와 짝으로만 동작함."""

from __future__ import annotations

import atexit
import ctypes as C
import logging
import subprocess
import sys
import time
from ctypes import wintypes as W
from pathlib import Path

from .watchdog import TIMEOUT

log = logging.getLogger(__name__)

_user32 = C.WinDLL("user32", use_last_error=True)
_user32.ClipCursor.argtypes = [C.c_void_p]
_user32.GetClipCursor.argtypes = [C.POINTER(W.RECT)]
_user32.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
_user32.GetCursorPos.argtypes = [C.POINTER(W.POINT)]
_user32.SetCursorPos.argtypes = [C.c_int, C.c_int]

_WATCHDOG = Path(__file__).with_name("watchdog.py")


def watchdog_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--fdp-watchdog"]
    return [sys.executable, "-I", "-S", str(_WATCHDOG)]


def window_center(hwnd: int) -> tuple[int, int, int, int]:
    """창 가운데 1픽셀 (물리 픽셀). 클릭되더라도 서명 캔버스 안에 떨어짐."""
    r = W.RECT()
    _user32.GetWindowRect(hwnd, C.byref(r))
    x, y = (r.left + r.right) // 2, (r.top + r.bottom) // 2
    return x, y, x + 1, y + 1


def current_clip() -> tuple[int, int, int, int]:
    r = W.RECT()
    _user32.GetClipCursor(C.byref(r))
    return r.left, r.top, r.right, r.bottom


class CursorGuard:
    def __init__(self):
        self._dog: subprocess.Popen | None = None
        self._rect: tuple[int, int, int, int] | None = None
        self._home: tuple[int, int] | None = None
        self._last = 0.0

    @property
    def locked(self) -> bool:
        return self._rect is not None

    def _send(self, byte: bytes) -> bool:
        try:
            self._dog.stdin.write(byte)
            self._dog.stdin.flush()
            return True
        except (AttributeError, OSError, ValueError):
            return False

    def lock(self, rect: tuple[int, int, int, int]) -> bool:
        """감시 프로세스가 살아 있을 때만 잠금. 실패하면 False."""
        if self._dog is None or self._dog.poll() is not None:
            try:
                self._dog = subprocess.Popen(
                    watchdog_command(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except OSError:
                log.exception("커서 감시 프로세스를 띄우지 못해 커서를 잠그지 않음")
                self._dog = None
                return False
        if not self._send(b"-."):  # 이전 잠금은 잊고 감시부터 시작
            return False
        home = W.POINT()
        _user32.GetCursorPos(C.byref(home))
        if not _user32.ClipCursor(C.byref(W.RECT(*rect))):
            log.warning("ClipCursor 실패: %s", C.WinError(C.get_last_error()))
            self._send(b"-")
            return False
        got = current_clip()
        if got[2] - got[0] > rect[2] - rect[0] or got[3] - got[1] > rect[3] - rect[1]:
            self._send(b"-")  # 앞 창이 아니면 Windows 가 잠금을 바로 풀어 버림
            return False
        self._send(b"=")
        self._rect, self._home = got, (home.x, home.y)
        self._last = time.monotonic()
        atexit.register(self.close)
        return True

    def beat(self) -> bool:
        """주기적으로 부름. False 면 잠금이 이미 풀렸으므로 서명 모드를 멈춰야 함."""
        if not self.locked:
            return False
        now = time.monotonic()
        late, self._last = now - self._last > TIMEOUT, now
        if late or current_clip() != self._rect or not self._send(b"."):
            self.unlock()
            return False
        return True

    def unlock(self) -> None:
        if not self.locked:
            return
        # 이미 풀렸거나 다른 프로그램(게임·원격 데스크톱)이 잠갔으면 건드리지 않음
        if current_clip() == self._rect:
            _user32.ClipCursor(None)
            if self._home:
                _user32.SetCursorPos(*self._home)
        self._rect = self._home = None
        self._send(b"-")

    def close(self) -> None:
        self.unlock()
        atexit.unregister(self.close)
        if self._dog is not None:
            try:
                self._dog.stdin.close()
            except OSError:
                pass
            self._dog = None
