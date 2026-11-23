"""커서 잠금 감시 프로세스.

본체가 멈추거나 강제 종료되면 본체 안의 타이머·스레드는 돌지 못하므로 별도 프로세스로 둠.
표준 라이브러리만 씀. 본체가 stdin 으로 보내는 한 바이트:
"." 잠금 중 · "=" 방금 잠금 확인됨 · "-" 잠금 없음.
"""

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

TIMEOUT = 1.5
VK_ESCAPE = 0x1B


def main() -> None:
    user32 = ctypes.WinDLL("user32")
    user32.ClipCursor.argtypes = [ctypes.c_void_p]
    user32.GetAsyncKeyState.restype = ctypes.c_short

    def current() -> tuple[int, int, int, int] | None:
        r = wintypes.RECT()
        if user32.GetClipCursor(ctypes.byref(r)):
            return r.left, r.top, r.right, r.bottom
        return None

    def release() -> None:
        # 내 잠금이 아님이 확실할 때만 그대로 둠. 모르면 푸는 쪽이 안전함
        ours, now = state["ours"], current()
        if ours is None or now is None or now == ours:
            user32.ClipCursor(None)

    fd = sys.stdin.fileno() if sys.stdin else 0  # 창 모드 exe 에서는 sys.stdin 이 없어도 파이프는 0번
    state = {"armed": False, "ours": None, "last": time.monotonic(), "closed": False}

    def listen() -> None:
        try:
            while data := os.read(fd, 64):
                state["last"] = time.monotonic()
                for byte in data:
                    if byte == ord("="):
                        # shortcut: 읽는 시점의 잠금을 기억, 그 수 ms 차이가 문제 되면 좌표를 전송
                        state["ours"] = current()
                    elif byte == ord("-"):
                        state["ours"] = None
                    state["armed"] = byte != ord("-")
        finally:
            state["closed"] = True

    threading.Thread(target=listen, daemon=True).start()
    while not state["closed"]:
        if state["armed"]:
            stalled = time.monotonic() - state["last"] > TIMEOUT
            if stalled or user32.GetAsyncKeyState(VK_ESCAPE) < 0:
                release()
                state["armed"] = False
        time.sleep(0.05)
    if state["armed"]:
        release()


if __name__ == "__main__":
    main()
