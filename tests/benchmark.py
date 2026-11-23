"""PRD 8절 성능 목표 측정.  python -m tests.benchmark

새 프로세스로 앱을 띄워 재므로 import 시간까지 포함됨. 사용자 데이터는 건드리지 않음.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TARGETS = {
    "startup_ms": ("시작 + 100쪽 첫 페이지", 1000),
    "page_ms": ("쪽 이동 후 선명한 화면 (최악)", 100),
    "zoom_ms": ("확대 후 선명한 화면 (최악)", 100),
    "stroke_ms": ("접촉 프레임 → 획 그리기 (최악)", 16),
    "memory_mb": ("1,000쪽 메모리 (본체+렌더)", 500),
}


def make(path: Path, pages: int) -> None:
    import pymupdf as mu

    with mu.open() as doc:
        for i in range(pages):
            page = doc.new_page()
            words = f"Page {i + 1}. lorem ipsum dolor sit amet consectetur adipiscing elit. "
            page.insert_textbox(mu.Rect(40, 40, 555, 800), words * 50, fontsize=10)
            page.draw_rect(mu.Rect(40, 700, 300, 780), color=(0, 0, 1), fill=(0.9, 0.9, 1))
        doc.save(path, deflate=True)


def working_set_mb(pid: int) -> float:
    import ctypes as C
    from ctypes import wintypes as W

    class Counters(C.Structure):
        _fields_ = [("cb", W.DWORD), ("faults", W.DWORD)] + [
            (f"size{i}", C.c_size_t) for i in range(8)
        ]

    kernel32 = C.WinDLL("kernel32")
    kernel32.OpenProcess.restype = W.HANDLE
    kernel32.K32GetProcessMemoryInfo.argtypes = [W.HANDLE, C.POINTER(Counters), W.DWORD]
    kernel32.CloseHandle.argtypes = [W.HANDLE]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    counters = Counters(cb=C.sizeof(Counters))
    kernel32.K32GetProcessMemoryInfo(handle, C.byref(counters), counters.cb)
    kernel32.CloseHandle(handle)
    return counters.size1 / 1024 / 1024  # WorkingSetSize


def child(path: str, started: float) -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_SCALE_FACTOR"] = "1.5"
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    from core.render.service import RenderService
    from storage.state import State

    service = RenderService()  # app/__main__ 과 같은 순서: 렌더 프로세스를 먼저 띄우고 UI 를 import
    from app.controller import Controller

    controller = Controller(State(), service)
    window = controller.new_window()
    window.resize(1400, 900)
    window.show()
    tab = controller.open(window, path)
    view = tab.view

    def until_sharp() -> None:
        end = time.monotonic() + 15
        while time.monotonic() < end:
            app.processEvents()
            key = view._scale_key()
            slots = view.visible_slots()
            if slots and all(
                view._tiles.get(("tile", s.pno, key, view.theme, *at))
                for s in slots
                for at in view._tile_range(s, key)
            ):
                view.viewport().repaint()
                return
            time.sleep(0.001)
        raise TimeoutError("render")

    until_sharp()
    print("startup_ms", (time.time() - started) * 1000)

    pages, zooms = [], []
    for pno in range(1, min(tab.doc.page_count, 1000), max(tab.doc.page_count // 25, 1)):
        begun = time.perf_counter()
        view.go_to(pno)
        until_sharp()
        pages.append((time.perf_counter() - begun) * 1000)
    for zoom in (1.0, 1.5, 2.0, 3.0, 1.25):
        begun = time.perf_counter()
        view.set_zoom(zoom)
        until_sharp()
        zooms.append((time.perf_counter() - begun) * 1000)
    print("page_ms", max(pages))
    print("zoom_ms", max(zooms))
    print("memory_mb", working_set_mb(os.getpid()) + working_set_mb(service._process.pid))

    from features.sign import sign_canvas
    from features.sign.contacts import Contact

    dialog = sign_canvas.SignDialog(None, QImage(), 3.0, {"sign_width": 1, "sign_color": 0}, True)
    dialog.resize(1000, 820)
    dialog.show()
    app.processEvents()
    spent = []
    now = time.perf_counter() + 1
    for i in range(300):
        frame = [Contact(0, 0.05 + i * 0.003, 0.5 + (i % 20) * 0.01, True, True)]
        begun = time.perf_counter()
        dialog.handle_frame(frame, now + i * 0.008)
        app.processEvents()
        spent.append((time.perf_counter() - begun) * 1000)
    print("stroke_ms", sorted(spent)[-2])  # 첫 프레임의 1회성 초기화 제외
    dialog.done(0)
    service.shutdown()


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="fdp-bench-"))
    try:
        small, big = folder / "100.pdf", folder / "1000.pdf"
        make(small, 100)
        make(big, 1000)
        environment = {**os.environ, "FDPREADER_DATA": str(folder / "data")}
        results: dict[str, float] = {}
        for path, names in (
            (small, ("startup_ms", "stroke_ms")),
            (big, ("page_ms", "zoom_ms", "memory_mb")),
        ):
            command = [sys.executable, "-m", "tests.benchmark", "child", str(path), str(time.time())]
            run = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=180)
            if run.returncode:
                print(run.stderr)
                raise SystemExit(1)
            for line in run.stdout.splitlines():
                name, _, value = line.partition(" ")
                if name in names:
                    results[name] = float(value)
        for name, (label, target) in TARGETS.items():
            value = results[name]
            print(f"{'OK  ' if value <= target else 'MISS'} {label}: {value:.1f} (목표 {target})")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["child"]:
        child(sys.argv[2], float(sys.argv[3]))
    else:
        main()
