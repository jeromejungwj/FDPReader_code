"""서명 보관함. DPAPI 로 암호화 (현재 Windows 계정으로만 복호화됨).

005 ScreenAsk 의 secret.py 와 같은 방식이되, 암호화에 실패하면 평문으로 저장하지 않고 실패함.
"""

from __future__ import annotations

import ctypes as C
import json
import logging
import os
import uuid
from ctypes import wintypes as W
from pathlib import Path

from storage import files

log = logging.getLogger(__name__)

_NO_UI = 0x1  # CRYPTPROTECT_UI_FORBIDDEN


class _Blob(C.Structure):
    _fields_ = [("size", W.DWORD), ("data", C.POINTER(C.c_char))]


_crypt32 = C.WinDLL("crypt32", use_last_error=True)
_kernel32 = C.WinDLL("kernel32", use_last_error=True)
for _name in ("CryptProtectData", "CryptUnprotectData"):
    _function = getattr(_crypt32, _name)
    _function.restype = W.BOOL
    _function.argtypes = [
        C.POINTER(_Blob), C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(_Blob)
    ]
_kernel32.LocalFree.argtypes = [C.c_void_p]


def _crypt(function, data: bytes) -> bytes:
    buffer = C.create_string_buffer(data, len(data))
    source = _Blob(len(data), C.cast(buffer, C.POINTER(C.c_char)))
    result = _Blob()
    if not function(C.byref(source), None, None, None, None, _NO_UI, C.byref(result)):
        raise C.WinError(C.get_last_error())
    try:
        return C.string_at(result.data, result.size)
    finally:
        _kernel32.LocalFree(C.cast(result.data, C.c_void_p))


class SignatureStore:
    def __init__(self, folder: Path | None = None):
        self.folder = folder or files.data_dir() / "signatures"
        self.folder.mkdir(parents=True, exist_ok=True)

    def all(self) -> list[tuple[str, dict]]:
        found = []
        for path in sorted(self.folder.glob("*.sig"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                raw = _crypt(_crypt32.CryptUnprotectData, path.read_bytes())
                found.append((path.stem, json.loads(raw)))
            except (OSError, ValueError):
                log.warning("서명을 복호화하지 못함 (다른 계정에서 만든 파일일 수 있음)")
        return found

    def add(self, signature: dict) -> str:
        name = uuid.uuid4().hex
        sealed = _crypt(_crypt32.CryptProtectData, json.dumps(signature).encode("utf-8"))
        files.write_bytes(self.folder / f"{name}.sig", sealed)
        return name

    def delete(self, name: str) -> None:
        path = self.folder / f"{name}.sig"
        size = path.stat().st_size
        # shortcut: 덮어쓴 뒤 삭제함. SSD 는 이전 블록이 남을 수 있어 DPAPI 암호화가 실제 방어선임
        with open(path, "r+b") as f:
            f.write(b"\0" * size)
            f.flush()
            os.fsync(f.fileno())
        path.unlink()
