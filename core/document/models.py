"""엔진 밖으로 나가는 자료형. PyMuPDF 타입은 core/document 밖으로 내보내지 않음.

좌표는 모두 "화면 좌표": 페이지 회전·CropBox 가 적용된 왼쪽 위 원점, 단위 pt.
"""

from __future__ import annotations

from dataclasses import dataclass

Rect = tuple[float, float, float, float]


class DocumentError(Exception):
    """code: not_pdf · damaged · permission · read_only · write"""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


class PasswordRequired(Exception):
    def __init__(self, wrong: bool):
        super().__init__("password required")
        self.wrong = wrong


@dataclass(frozen=True)
class Annot:
    xref: int
    pno: int
    kind: str  # PDF Subtype (Highlight, Text, FreeText, Stamp, Ink …)
    rect: Rect
    text: str
    ours: bool  # 이 앱이 만든 주석
    locked: bool
    size: float = 12.0

    @property
    def movable(self) -> bool:
        return not self.locked and self.kind in ("Stamp", "FreeText", "Ink", "Text")

    @property
    def resizable(self) -> bool:
        return self.movable and self.ours and self.kind != "Text"


@dataclass(frozen=True)
class Field:
    xref: int
    pno: int
    kind: str  # text · check · radio · combo · list · signature
    rect: Rect
    name: str
    value: object
    read_only: bool
    multiline: bool = False
    password: bool = False
    editable: bool = False  # 직접 입력되는 드롭다운
    multi: bool = False
    max_len: int = 0
    options: tuple[tuple[str, str], ...] = ()  # (저장값, 보이는 글자)
    date_format: str = ""
    font_size: float = 0.0


@dataclass(frozen=True)
class Link:
    rect: Rect
    kind: str  # page · uri · file · launch
    page: int = 0
    y: float | None = None
    target: str = ""


@dataclass(frozen=True)
class TocItem:
    level: int
    title: str
    page: int
    y: float | None


@dataclass(frozen=True)
class Graphic:
    """문서에 넣을 서명 그림. 좌표는 y 가 아래로 커지는 임의 단위."""

    kind: str  # lines · fill · image
    bounds: Rect
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    segments: tuple = ()  # (x0, y0, x1, y1, 굵기)
    contours: tuple = ()
    image: bytes = b""

    @property
    def aspect(self) -> float:
        x0, y0, x1, y1 = self.bounds
        return max(x1 - x0, 1e-6) / max(y1 - y0, 1e-6)
