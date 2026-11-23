"""커서 잠금과 감시 프로세스. 실제 커서는 건드리지 않음 (Win32 호출을 가짜로 바꿈)."""

import subprocess
import sys
import time
import unittest
from unittest import mock

from features.sign import cursor_guard, watchdog
from storage.files import ROOT

FAKE_WATCHDOG = """
import ctypes, sys
class User32:
    def __init__(self):
        reads = []
        def get(ref):
            reads.append(1)
            lost = 'foreign' in sys.argv and len(reads) > 1
            r = ref._obj
            r.left, r.top, r.right, r.bottom = (7, 7, 8, 8) if lost else (1, 1, 2, 2)
            return 'broken' not in sys.argv
        def clip(_):
            print('released', flush=True)
        def key(_):
            return -32768 if 'esc' in sys.argv else 0
        self.ClipCursor, self.GetClipCursor, self.GetAsyncKeyState = clip, get, key
ctypes.WinDLL = lambda *a, **k: User32()
from features.sign import watchdog
watchdog.main()
"""


class Watchdog(unittest.TestCase):
    def start(self, *args):
        process = subprocess.Popen(
            [sys.executable, "-c", FAKE_WATCHDOG, *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=ROOT,
        )
        self.addCleanup(process.stdout.close)
        self.addCleanup(process.kill)
        return process

    def send(self, process, data: bytes):
        process.stdin.write(data)
        process.stdin.flush()

    def finish(self, process) -> bytes:
        process.stdin.close()
        process.wait(5)
        return process.stdout.read()

    def test_hung_app_is_released(self):
        process = self.start()
        self.send(process, b".")
        began = time.monotonic()
        self.assertIn(b"released", process.stdout.readline())  # stdin 은 열린 채 = 멈춘 본체
        self.assertLess(time.monotonic() - began, watchdog.TIMEOUT + 2.0)
        self.finish(process)

    def test_dead_app_is_released(self):
        process = self.start()
        self.send(process, b".")
        time.sleep(0.3)
        self.assertIn(b"released", self.finish(process))

    def test_escape_releases_even_while_app_is_alive(self):
        process = self.start("esc")
        self.send(process, b".")
        self.assertIn(b"released", process.stdout.readline())
        self.finish(process)

    def test_nothing_is_released_when_we_hold_no_lock(self):
        process = self.start()
        self.send(process, b".")
        time.sleep(0.2)
        self.send(process, b"-")
        time.sleep(0.2)
        self.assertNotIn(b"released", self.finish(process))

    def test_another_programs_lock_survives_hang_exit_and_escape(self):
        for name, args, seconds in (("hang", [], watchdog.TIMEOUT + 0.7), ("exit", [], 0.3),
                                    ("esc", ["esc"], 0.5)):
            with self.subTest(name):
                process = self.start("foreign", *args)
                self.send(process, b"-.=.")  # 잠그기 전 · 잠금 확인 · 심박
                time.sleep(seconds)
                self.assertNotIn(b"released", self.finish(process))

    def test_confirmed_lock_is_still_released(self):
        for args in ([], ["broken"]):  # broken: 현재 잠금을 읽지 못하면 푸는 쪽으로
            with self.subTest(args):
                process = self.start(*args)
                self.send(process, b"-.=.")  # 잠그기 전 · 잠금 확인 · 심박
                time.sleep(0.3)
                self.assertIn(b"released", self.finish(process))


class Guard(unittest.TestCase):
    OURS = (100, 100, 101, 101)
    THEIRS = (-1280, 720, -1279, 721)
    FREE = (0, 0, 1920, 1080)

    def setUp(self):
        self.user32 = mock.MagicMock()
        patcher = mock.patch.object(cursor_guard, "_user32", self.user32)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.guard = cursor_guard.CursorGuard()
        self.guard._send = lambda byte: True
        self.guard._rect, self.guard._home = self.OURS, (5, 6)

    def unlock_while(self, clip):
        with mock.patch.object(cursor_guard, "current_clip", lambda: clip):
            self.guard.unlock()
        self.assertFalse(self.guard.locked)

    def test_our_lock_is_released_and_cursor_goes_back(self):
        self.unlock_while(self.OURS)
        self.user32.ClipCursor.assert_called_once_with(None)
        self.user32.SetCursorPos.assert_called_once_with(5, 6)

    def test_another_programs_lock_is_left_alone(self):
        self.unlock_while(self.THEIRS)
        self.user32.ClipCursor.assert_not_called()
        self.user32.SetCursorPos.assert_not_called()

    def test_lost_lock_does_not_move_the_cursor(self):
        self.unlock_while(self.FREE)
        self.user32.SetCursorPos.assert_not_called()

    def test_watchdog_runs_without_python_in_the_packaged_app(self):
        exe = r"C:\FDP\FDPReader.exe"
        with mock.patch.object(cursor_guard.sys, "frozen", True, create=True):
            with mock.patch.object(cursor_guard.sys, "executable", exe):
                self.assertEqual(cursor_guard.watchdog_command(), [exe, "--fdp-watchdog"])
        self.assertEqual(cursor_guard.watchdog_command()[1:3], ["-I", "-S"])

    def test_lock_tells_watchdog_which_lock_is_ours(self):
        sent = []
        self.guard._send = lambda byte: sent.append(byte) or True
        self.guard._dog = mock.Mock(**{"poll.return_value": None})
        with mock.patch.object(cursor_guard, "current_clip", lambda: self.OURS),                 mock.patch.object(cursor_guard.atexit, "register"):
            self.assertTrue(self.guard.lock(self.OURS))
        self.assertEqual(b"".join(sent), b"-.=")


if __name__ == "__main__":
    unittest.main()
