"""데이터 폴더와 원자적 파일 쓰기."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

APP_NAME = "FDPReader"
# 배포용 exe 면 exe 가 있는 폴더 (portable.flag 위치)
ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


def is_portable() -> bool:
    return (ROOT / "portable.flag").exists()


def data_dir() -> Path:
    """설정·서명 위치. 포터블이면 프로그램 옆 data 폴더."""
    override = os.environ.get("FDPREADER_DATA")  # 테스트가 실제 사용자 데이터를 건드리지 않게 함
    if override:
        path = Path(override)
    elif is_portable():
        path = ROOT / "data"
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_atomic(target: Path, write: Callable[[Path], None]) -> None:
    """같은 폴더의 임시 파일에 다 쓴 뒤 교체. 중간에 실패해도 target 은 그대로임."""
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".fdp-", suffix=".tmp")
    os.close(fd)
    tmp = Path(name)
    try:
        write(tmp)
        with open(tmp, "r+b") as f:
            os.fsync(f.fileno())
        for attempt in range(6):
            try:
                os.replace(tmp, target)
                return
            except PermissionError:  # 백신·동기화 프로그램이 잠깐 잡고 있을 수 있음
                if attempt == 5:
                    raise
                time.sleep(0.1)
    finally:
        tmp.unlink(missing_ok=True)


def write_bytes(target: Path, data: bytes) -> None:
    write_atomic(target, lambda tmp: tmp.write_bytes(data))


def copy_atomic(source: Path, target: Path) -> None:
    write_atomic(target, lambda tmp: shutil.copyfile(source, tmp))
