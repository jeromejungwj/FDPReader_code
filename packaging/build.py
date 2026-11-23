"""배포본 빌드: exe 폴더(PyInstaller) → 점검 → 설치 파일(Inno Setup).

    .venv\\Scripts\\python packaging\\build.py

필요: requirements-build.txt, Inno Setup 6 (ISCC.exe). 결과는 dist\\ 에 생김.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD, DIST = ROOT / "build", ROOT / "dist"
APP = DIST / "FDPReader"
ICON = BUILD / "FDPReader.ico"
ISCC = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"


def version() -> str:
    scope: dict = {}
    exec((ROOT / "app" / "__init__.py").read_text(encoding="utf-8"), scope)
    return scope["__version__"]


def make_icon() -> None:
    """파란 바탕의 문서 + 서명 획. 별도 그림 파일 없이 Qt 로 그림."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen

    app = QGuiApplication.instance() or QGuiApplication([])
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#2f6fde"))
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 48, 48)
    page = QPainterPath()
    page.moveTo(68, 40)
    page.lineTo(156, 40)
    page.lineTo(196, 80)
    page.lineTo(196, 216)
    page.lineTo(68, 216)
    page.closeSubpath()
    p.setBrush(QColor("white"))
    p.drawPath(page)
    p.setBrush(QColor("#c9d8f5"))
    p.drawPolygon([QPointF(156, 40), QPointF(196, 80), QPointF(156, 80)])
    stroke = QPainterPath(QPointF(84, 178))
    stroke.cubicTo(100, 120, 118, 120, 116, 168)
    stroke.cubicTo(114, 196, 140, 132, 150, 160)
    stroke.cubicTo(156, 176, 168, 166, 182, 150)
    p.setPen(QPen(QColor("#1b2a4a"), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(stroke)
    p.end()
    BUILD.mkdir(exist_ok=True)
    if not image.save(str(ICON), "ICO"):
        raise SystemExit("아이콘을 만들지 못함 (Qt ICO 플러그인 확인)")
    del app


def freeze() -> None:
    import PyInstaller.__main__

    PyInstaller.__main__.run([
        str(ROOT / "FDPReader.pyw"),
        "--name", "FDPReader",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--icon", str(ICON),
        "--paths", str(ROOT),
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
        "--exclude-module", "tests",
        "--exclude-module", "tkinter",
    ])
    for name in ("LICENSE", "THIRD-PARTY-NOTICES.md"):
        shutil.copy2(ROOT / name, APP / name)
    shutil.copytree(ROOT / "packaging" / "licenses", APP / "licenses", dirs_exist_ok=True)


def self_test() -> None:
    """만든 exe 로 PDF 를 열어 첫 화면·감시 프로세스를 확인. 화면에는 아무것도 띄우지 않음."""
    import pymupdf

    with tempfile.TemporaryDirectory(prefix="fdp-build-") as folder:
        pdf, result = Path(folder) / "check.pdf", Path(folder) / "result.json"
        with pymupdf.open() as doc:
            for i in range(3):
                doc.new_page().insert_text((72, 72), f"FDP Reader check {i + 1} 한글", fontname="korea")
            doc.save(pdf)
        env = {
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "FDPREADER_DATA": str(Path(folder) / "data"),
            "FDPREADER_SELF_TEST": str(result),
        }
        subprocess.run([str(APP / "FDPReader.exe"), str(pdf)], env=env, timeout=90, check=False)
        report = json.loads(result.read_text(encoding="utf-8")) if result.exists() else {}
        print("self-test:", report)
        if not (report.get("rendered") and report.get("watchdog") and report.get("pages") == 3):
            raise SystemExit("배포본 점검 실패")


def installer() -> Path:
    if not ISCC.exists():
        raise SystemExit(f"Inno Setup 6 이 없음: {ISCC}")
    subprocess.run(
        [str(ISCC), f"/DAppVersion={version()}", f"/O{DIST}", str(ROOT / "packaging" / "FDPReader.iss")],
        check=True,
    )
    return DIST / f"FDPReader-Setup-{version()}.exe"


if __name__ == "__main__":
    make_icon()
    freeze()
    self_test()
    print("installer:", installer())
    sys.exit(0)
