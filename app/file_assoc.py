"""PDF 연결 프로그램 등록 (현재 사용자만). 기본 앱 선택 자체는 Windows 가 사용자에게만 허용함."""

from __future__ import annotations

import ctypes
import sys
import winreg
from pathlib import Path

from storage import files

PROG_ID = "FDPReader.pdf"
CAPABILITIES = r"Software\FDPReader\Capabilities"
REGISTERED = r"Software\RegisteredApplications"
OPEN_WITH = r"Software\Classes\.pdf\OpenWithProgids"
NAME = "FDP Reader"


def open_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'
    runner = Path(sys.executable).with_name("pythonw.exe")
    return f'"{runner}" "{files.ROOT / "FDPReader.pyw"}" "%1"'


def entries() -> list[tuple[str, str, str]]:
    classes = rf"Software\Classes\{PROG_ID}"
    return [
        (classes, "", "PDF (FDP Reader)"),
        (classes, "FriendlyTypeName", "PDF (FDP Reader)"),
        (rf"{classes}\Application", "ApplicationName", NAME),
        (rf"{classes}\shell\open", "FriendlyAppName", NAME),
        (rf"{classes}\shell\open\command", "", open_command()),
        (OPEN_WITH, PROG_ID, ""),
        (CAPABILITIES, "ApplicationName", NAME),
        (CAPABILITIES, "ApplicationDescription", "PDF reader with touchpad signatures"),
        (rf"{CAPABILITIES}\FileAssociations", ".pdf", PROG_ID),
        (REGISTERED, NAME, CAPABILITIES),
    ]


def _notify() -> None:
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED


def register() -> None:
    for key, name, value in entries():
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
            winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)
    _notify()


def unregister() -> None:
    """우리가 쓴 것만 지움. 다른 앱과 공유하는 키는 값만 지움."""
    root = winreg.HKEY_CURRENT_USER
    for key, name in ((OPEN_WITH, PROG_ID), (REGISTERED, NAME)):
        try:
            with winreg.OpenKey(root, key, 0, winreg.KEY_SET_VALUE) as handle:
                winreg.DeleteValue(handle, name)
        except FileNotFoundError:
            pass
    classes = rf"Software\Classes\{PROG_ID}"
    for key in (
        rf"{classes}\shell\open\command", rf"{classes}\shell\open", rf"{classes}\shell",
        rf"{classes}\Application", classes,
        rf"{CAPABILITIES}\FileAssociations", CAPABILITIES, r"Software\FDPReader",
    ):
        try:
            winreg.DeleteKey(root, key)
        except FileNotFoundError:
            pass
    _notify()
