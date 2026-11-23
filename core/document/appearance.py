"""Appearance Stream (표시 스트림) 생성.

다른 리더에서도 같게 보이도록 주석·양식의 그림은 전부 여기서 만듦. 엔진 기본 생성기는 한글을
글꼴 포함 없이 전각으로 써서 리더마다 다르게 보임.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import pymupdf as mu
from pymupdf import mupdf

from .models import Graphic
from .pdfobj import numbers as n

KOREAN_FONT = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts" / "malgun.ttf"
LINE_HEIGHT = 1.3
PADDING = 2.0

_HELV = (
    "<</Font<</Helv<</Type/Font/Subtype/Type1/BaseFont/Helvetica"
    "/Encoding/WinAnsiEncoding>>>>>>"
)
_MATRIX = {0: "1 0 0 1 0 0", 90: "0 1 -1 0 0 0", 180: "-1 0 0 -1 0 0", 270: "0 -1 1 0 0 0"}


def upright_size(user: mu.Rect, rotation: int) -> tuple[float, float]:
    """rotation 만큼 돌려 보는 사람에게 똑바로 보일 때의 폭·높이."""
    if rotation % 180:
        return user.height, user.width
    return user.width, user.height


def form(doc: mu.Document, box, content: str, rotation: int = 0, resources: str = "<<>>") -> int:
    xref = doc.get_new_xref()
    doc.update_object(
        xref,
        f"<</Type/XObject/Subtype/Form/BBox[{n(*box)}]"
        f"/Matrix[{_MATRIX[rotation % 360]}]/Resources {resources}>>",
    )
    doc.update_stream(xref, content.encode("latin-1", "replace"), new=True)
    return xref


def _import_page(doc: mu.Document, page: mu.Page, rotation: int, before="", after="") -> int:
    """임시 문서의 한 쪽을 글꼴·그림과 함께 Form XObject 로 가져옴."""
    src = page.parent
    kind, resources = src.xref_get_key(page.xref, "Resources")
    if kind == "null":
        resources = "<<>>"
    xref = src.get_new_xref()
    src.update_object(
        xref,
        f"<</Type/XObject/Subtype/Form/BBox[{n(0, 0, page.rect.width, page.rect.height)}]"
        f"/Matrix[{_MATRIX[rotation % 360]}]/Resources {resources}>>",
    )
    data = before.encode("latin-1") + b"\n" + page.read_contents() + b"\n" + after.encode("latin-1")
    src.update_stream(xref, data, new=True)
    obj = mupdf.pdf_graft_object(
        mu._as_pdf_document(doc), mupdf.pdf_new_indirect(mu._as_pdf_document(src), xref, 0)
    )
    return mupdf.pdf_to_num(obj)


@lru_cache(maxsize=2)
def _font(korean: bool) -> mu.Font:
    if korean and KOREAN_FONT.exists():
        return mu.Font(fontfile=str(KOREAN_FONT))
    return mu.Font("korea" if korean else "helv")


def needs_korean(text: str) -> bool:
    return any(ord(c) > 126 for c in text)


@lru_cache(maxsize=8192)
def _advance(korean: bool, code: int) -> float:
    return _font(korean).glyph_advance(code)


def text_width(text: str, size: float, korean: bool) -> float:
    return sum(_advance(korean, ord(c)) for c in text) * size


def wrap(text: str, size: float, width: float, korean: bool) -> list[str]:
    lines = []
    for paragraph in text.replace("\t", "    ").splitlines() or [""]:
        line, used = "", 0.0
        for ch in paragraph:
            step = _advance(korean, ord(ch)) * size
            if line and used + step > width:
                cut = line.rfind(" ")
                if ch == " " or cut <= 0:
                    lines.append(line)
                    line, used = "", 0.0
                    if ch == " ":
                        continue
                else:
                    lines.append(line[:cut])
                    line = line[cut + 1 :]
                    used = text_width(line, size, korean)
            line += ch
            used += step
        lines.append(line)
    return lines


def text_height(text: str, size: float, width: float) -> float:
    lines = wrap(text, size, width - 2 * PADDING, needs_korean(text))
    return len(lines) * size * LINE_HEIGHT + 2 * PADDING


def _draw_text(doc, w, h, runs, size, color, rotation, before="", after="") -> int:
    """runs: (x, 위에서부터 잰 기준선 y, 글자)."""
    runs = [r for r in runs if r[2].strip()]
    if not any(needs_korean(text) for _, _, text in runs):
        ops = []
        if runs:
            ops.append(f"BT {n(*color)} rg /Helv {n(size)} Tf")
            for x, y, text in runs:
                safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                ops.append(f"1 0 0 1 {n(x, h - y)} Tm ({safe}) Tj")
            ops.append("ET")
        return form(doc, (0, 0, w, h), "\n".join([before, *ops, after]), rotation, _HELV)

    with mu.open() as src:
        page = src.new_page(width=w, height=h)
        writer = mu.TextWriter(page.rect)
        font = _font(True)
        for x, y, text in runs:
            writer.append((x, y), text, font=font, fontsize=size)
        writer.write_text(page, color=color)
        src.subset_fonts(fallback=False)  # 안 하면 글꼴 전체(7MB)가 들어감
        return _import_page(doc, page, rotation, before, after)


def text_box(doc, w: float, h: float, text: str, size: float, color, rotation: int) -> int:
    korean = needs_korean(text)
    while True:
        lines = wrap(text, size, w - 2 * PADDING, korean)
        if size <= 4 or len(lines) * size * LINE_HEIGHT <= h - 2 * PADDING + 0.5:
            break
        size *= 0.93
    runs = [(PADDING, PADDING + size * (1 + i * LINE_HEIGHT), s) for i, s in enumerate(lines)]
    return _draw_text(doc, w, h, runs, size, color, rotation)


def _field_decor(w, h, background, border) -> str:
    ops = ""
    if background:
        ops += f"q {n(*background)} rg 0 0 {n(w, h)} re f Q\n"
    if border:
        ops += f"q {n(*border)} RG 1 w 0.5 0.5 {n(w - 1, h - 1)} re S Q\n"
    return ops


def text_field(
    doc, w, h, text, size, color, rotation, *,
    align=0, multiline=False, comb=0, background=None, border=None,
) -> tuple[int, float]:
    """(Form XObject, 실제로 쓴 글자 크기)."""
    korean = needs_korean(text)
    inner = max(w - 2 * PADDING, 1.0)
    runs = []
    if comb:
        size = size or min(max(h * 0.65, 4), 12)
        size = min(size, w / comb * 0.95)
        base = (h + size * 0.72) / 2
        for i, ch in enumerate(text[:comb]):
            runs.append(((i + 0.5) * w / comb - text_width(ch, size, korean) / 2, base, ch))
    else:
        if multiline:
            if not size:
                size = 12.0
                while size > 4 and len(wrap(text, size, inner, korean)) * size * LINE_HEIGHT > h:
                    size *= 0.92
            lines = wrap(text, size, inner, korean)
            top = PADDING + size
        else:
            one = text.replace("\r", "").replace("\n", " ")
            if not size:
                size = min(max(h * 0.65, 4), 12)
                wide = text_width(one, size, korean)
                if wide > inner:
                    size = max(size * inner / wide, 3)
            lines, top = [one], (h + size * 0.72) / 2
        for i, line in enumerate(lines):
            wide = text_width(line, size, korean)
            x = PADDING + (max(inner - wide, 0) * (0.5 if align == 1 else 1) if align else 0)
            runs.append((x, top + i * size * LINE_HEIGHT, line))
    before = _field_decor(w, h, background, border) + f"/Tx BMC q 0 0 {n(w, h)} re W n"
    return _draw_text(doc, w, h, runs, size, color, rotation, before, "Q EMC"), size


def list_field(
    doc, w, h, labels, selected: set[int], size, color, rotation, decor
) -> tuple[int, float]:
    size = size or 10.0
    step = size * LINE_HEIGHT
    room = max(int(h / step), 1)
    first = min(selected) if selected and min(selected) >= room else 0
    before = _field_decor(w, h, *decor) + f"/Tx BMC q 0 0 {n(w, h)} re W n\n"
    runs = []
    for row, index in enumerate(range(first, min(len(labels), first + room))):
        if index in selected:
            before += f"0.6 0.76 0.93 rg 0 {n(h - (row + 1) * step, w, step)} re f\n"
        runs.append((PADDING, row * step + size, labels[index]))
    return _draw_text(doc, w, h, runs, size, color, rotation, before, "Q EMC"), size


def check(doc, w, h, on: bool, radio: bool, rotation: int, background=None, border=None) -> int:
    ops = _field_decor(w, h, background, None if radio else border)
    if on and radio:  # 길이 0 + 둥근 끝 = 점
        ops += f"q 0 G 1 J {n(min(w, h) * 0.5)} w {n(w / 2, h / 2)} m {n(w / 2, h / 2)} l S Q"
    elif on:
        ops += (
            f"q 0 G 1 J 1 j {n(min(w, h) * 0.12)} w {n(w * 0.2, h * 0.5)} m "
            f"{n(w * 0.42, h * 0.25)} l {n(w * 0.8, h * 0.78)} l S Q"
        )
    return form(doc, (0, 0, w, h), ops, rotation)


def markup(doc, kind: str, box: mu.Rect, quads, color) -> int:
    """quads: PDF 사용자 좌표 (왼위, 오위, 왼아래, 오아래)."""
    ops, resources = [], "<<>>"
    if kind == "Highlight":
        resources = "<</ExtGState<</GS<</BM/Multiply>>>>>>"
        ops.append(f"/GS gs {n(*color)} rg")
        for ul, ur, ll, lr in quads:
            ops.append(f"{n(*ul)} m {n(*ur)} l {n(*lr)} l {n(*ll)} l f")
    else:
        ops.append(f"{n(*color)} RG")
        at = 0.06 if kind == "Underline" else 0.45  # 아래 변에서 위로 올라간 비율
        for ul, ur, ll, lr in quads:
            a, b = ll + (ul - ll) * at, lr + (ur - lr) * at
            ops.append(f"{n(max(abs(ul - ll) * 0.06, 0.6))} w {n(*a)} m {n(*b)} l S")
    return form(doc, tuple(box), "\n".join(ops), 0, resources)


def note_icon(doc, color, rotation: int) -> int:
    ops = (
        f"{n(*color)} rg 0.3 G 0.8 w 1 5 18 14 re B "
        f"{n(*color)} rg 5 5 m 5 1 l 10 5 l B "
        "0.25 G 4 14.5 m 16 14.5 l S 4 11.5 m 16 11.5 l S 4 8.5 m 12 8.5 l S"
    )
    return form(doc, (0, 0, 20, 20), ops, rotation)


def graphic(doc, g: Graphic, w: float, h: float, rotation: int) -> int:
    if g.kind == "image":
        with mu.open() as src:
            page = src.new_page(width=w, height=h)
            page.insert_image(page.rect, stream=g.image, keep_proportion=False)
            return _import_page(doc, page, rotation)

    x0, y0, x1, y1 = g.bounds
    sx, sy = w / max(x1 - x0, 1e-6), h / max(y1 - y0, 1e-6)

    def at(x, y) -> str:
        return n((x - x0) * sx, h - (y - y0) * sy)

    if g.kind == "fill":
        ops = [f"{n(*g.color)} rg"]
        for contour in g.contours:
            if len(contour) > 2:
                ops.append(f"{at(*contour[0])} m")
                ops += [f"{at(*p)} l" for p in contour[1:]]
                ops.append("h")
        ops.append("f")
    else:
        ops = [f"{n(*g.color)} RG 1 J 1 j"]
        scale = (sx + sy) / 2
        for ax, ay, bx, by, thick in g.segments:
            ops.append(f"{thick * scale:.3f} w {at(ax, ay)} m {at(bx, by)} l S")
    return form(doc, (0, 0, w, h), "\n".join(ops), rotation)
