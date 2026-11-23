"""PDF 표준 주석 읽기·쓰기."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import replace

import pymupdf as mu

from . import appearance, pdfobj
from .engine import page_matrix
from .models import Annot, Graphic, Rect
from .pdfobj import numbers as n

OURS = "fdp-"
NOTE_SIZE = 20.0
NOTE_STAMP = "/FDPNote"
_SKIP = {"Link", "Popup", "Widget"}
_HIDDEN, _READ_ONLY, _NO_VIEW, _LOCKED = 2, 64, 32, 128
_PRINT = 4
_NO_ZOOM, _NO_ROTATE = 8, 16


def _pinned(subtype: str, flags: int) -> bool:
    """회전·확대를 안 따르는 아이콘. MuPDF 는 사각형의 왼위 모서리(사용자 좌표)에 20pt 로 그림."""
    return subtype == "Text" or bool(flags & (_NO_ZOOM | _NO_ROTATE))


def _user_rect(page: mu.Page, rect: Rect) -> mu.Rect:
    return (mu.Rect(rect) * ~page_matrix(page)).normalize()


def read(doc: mu.Document, pno: int) -> list[Annot]:
    page = doc[pno]
    matrix = page_matrix(page)
    found = []
    for xref, *_ in page.annot_xrefs():
        kind = pdfobj.get(doc, xref, "Subtype")[1].lstrip("/")
        box = pdfobj.rect(doc, xref)
        if kind in _SKIP or box is None:
            continue
        flag_type, flag_value = pdfobj.get(doc, xref, "F")
        flags = int(flag_value) if flag_type == "int" else 0
        if flags & (_HIDDEN | _NO_VIEW):
            continue
        text_type, text = pdfobj.get(doc, xref, "Contents")
        name_type, name = pdfobj.get(doc, xref, "NM")
        size = re.search(r"([\d.]+)\s+Tf", pdfobj.get(doc, xref, "DA")[1])
        if _pinned(kind, flags):
            at = mu.Point(box.x0, box.y1) * matrix
            shown = mu.Rect(at.x, at.y, at.x + NOTE_SIZE, at.y + NOTE_SIZE)
        else:
            shown = (box * matrix).normalize()
        if kind == "Stamp" and pdfobj.get(doc, xref, "Name")[1] == NOTE_STAMP:
            kind = "Text"
        found.append(
            Annot(
                xref=xref,
                pno=pno,
                kind=kind,
                rect=tuple(shown),
                text=text if text_type == "string" else "",
                ours=name_type == "string" and name.startswith(OURS),
                locked=bool(flags & (_READ_ONLY | _LOCKED)),
                size=float(size.group(1)) if size else 12.0,
            )
        )
    return found


def _add(doc, page: mu.Page, subtype: str, box: mu.Rect, ap: int, extra: str = "") -> int:
    stamp = time.strftime("D:%Y%m%d%H%M%S")
    xref = pdfobj.new_object(
        doc,
        f"<</Type/Annot/Subtype/{subtype}/Rect[{n(*box)}]/F {_PRINT}/P {page.xref} 0 R"
        f"/NM({OURS}{uuid.uuid4().hex})/M({stamp})/AP<</N {ap} 0 R>>{extra}>>",
    )
    pdfobj.append_annot(doc, page, xref)
    return xref


def add_markup(doc, pno: int, kind: str, quads: list, color, text: str = "") -> int:
    page = doc[pno]
    back = ~page_matrix(page)
    quads = [tuple(mu.Point(p) * back for p in quad) for quad in quads]
    xs = [p.x for q in quads for p in q]
    ys = [p.y for q in quads for p in q]
    box = mu.Rect(min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1)
    ap = appearance.markup(doc, kind, box, quads, color)
    points = n(*(v for q in quads for p in q for v in p))
    extra = f"/C[{n(*color)}]/QuadPoints[{points}]"
    if text:
        extra += f"/Contents {pdfobj.text_string(text)}"
    return _add(doc, page, kind, box, ap, extra)


def add_note(doc, pno: int, x: float, y: float, text: str, color, view_rotation: int) -> int:
    page = doc[pno]
    x = min(max(x, 0), max(page.rect.width - NOTE_SIZE, 0))
    y = min(max(y, 0), max(page.rect.height - NOTE_SIZE, 0))
    box = _user_rect(page, (x, y, x + NOTE_SIZE, y + NOTE_SIZE))
    rotation = (page.rotation + view_rotation) % 360
    ap = appearance.note_icon(doc, color, rotation)
    extra = f"/C[{n(*color)}]/Contents {pdfobj.text_string(text)}"
    if page.rotation or view_rotation:
        # Text 주석은 회전된 쪽에서 리더(MuPDF·PDFium)마다 다른 자리에 그려져 Stamp 로 넣음
        return _add(doc, page, "Stamp", box, ap, f"/Name{NOTE_STAMP}{extra}")
    return _add(doc, page, "Text", box, ap, f"/Name/Comment{extra}")


def add_text(doc, pno: int, rect: Rect, text: str, size: float, view_rotation: int) -> int:
    page = doc[pno]
    box = _user_rect(page, rect)
    rotation = (page.rotation + view_rotation) % 360
    ap = appearance.text_box(
        doc, *appearance.upright_size(box, rotation), text, size, (0, 0, 0), rotation
    )
    extra = (
        f"/IT/FreeTextTypeWriter/DA(0 g /Helv {n(size)} Tf)/Rotate {rotation}"
        f"/Contents {pdfobj.text_string(text)}"
    )
    return _add(doc, page, "FreeText", box, ap, extra)


def add_signature(
    doc, pno: int, rect: Rect, g: Graphic, view_rotation: int, as_ink: bool = False
) -> int:
    page = doc[pno]
    box = _user_rect(page, rect)
    rotation = (page.rotation + view_rotation) % 360
    w, h = appearance.upright_size(box, rotation)
    ap = appearance.graphic(doc, g, w, h, rotation)
    # Contents 를 넣으면 Edge·Acrobat 이 서명 옆에 메모 말풍선을 띄움
    label = f"/Subj {pdfobj.text_string('Signature')}"
    if not (as_ink and g.kind == "lines"):
        return _add(doc, page, "Stamp", box, ap, f"/Name/FDPSignature{label}")

    x0, y0, x1, y1 = g.bounds
    sx, sy = w / max(x1 - x0, 1e-6), h / max(y1 - y0, 1e-6)

    def place(x, y) -> str:  # 똑바로 선 서명 좌표 → 사용자 좌표
        u, v = (x - x0) * sx / w, 1 - (y - y0) * sy / h
        for _ in range(rotation // 90):
            u, v = 1 - v, u
        return n(box.x0 + u * box.width, box.y0 + v * box.height)

    paths: list[list[str]] = []
    end = None
    for ax, ay, bx, by, _ in g.segments:
        if end != (ax, ay):
            paths.append([place(ax, ay)])
        paths[-1].append(place(bx, by))
        end = (bx, by)
    width = sum(s[4] for s in g.segments) / max(len(g.segments), 1) * (sx + sy) / 2
    ink = "".join(f"[{' '.join(p)}]" for p in paths)
    extra = f"/InkList[{ink}]/C[{n(*g.color)}]/BS<</W {n(width)}>>{label}"
    return _add(doc, page, "Ink", box, ap, extra)


def move(doc, annot: Annot, rect: Rect) -> None:
    page = doc[annot.pno]
    box = _user_rect(page, rect)
    old = pdfobj.rect(doc, annot.xref)
    subtype = pdfobj.get(doc, annot.xref, "Subtype")[1].lstrip("/")
    flag_type, flag_value = pdfobj.get(doc, annot.xref, "F")
    if old and _pinned(subtype, int(flag_value) if flag_type == "int" else 0):
        at = mu.Point(rect[0], rect[1]) * ~page_matrix(page)
        box = mu.Rect(at.x, at.y - old.height, at.x + old.width, at.y)
    doc.xref_set_key(annot.xref, "Rect", f"[{n(*box)}]")
    if annot.kind == "Ink" and old and not old.is_empty:
        sx, sy = box.width / old.width, box.height / old.height
        paths = []
        raw = pdfobj.body(doc, pdfobj.get(doc, annot.xref, "InkList"))
        for group in re.findall(r"\[([^\[\]]*)\]", raw):
            v = [float(s) for s in group.split()]
            moved = []
            for x, y in zip(v[::2], v[1::2]):
                moved += (box.x0 + (x - old.x0) * sx, box.y0 + (y - old.y0) * sy)
            paths.append(f"[{n(*moved)}]")
        if paths:
            doc.xref_set_key(annot.xref, "InkList", f"[{''.join(paths)}]")
    elif annot.ours and annot.kind == "FreeText" and old:
        resized = abs(old.width - box.width) > 0.1 or abs(old.height - box.height) > 0.1
        if resized:  # 글자가 늘어나지 않게 줄을 다시 나눔
            _redraw_text(doc, annot.xref, box, annot.text, annot.size)


def _redraw_text(doc, xref: int, box: mu.Rect, text: str, size: float) -> None:
    kind, value = pdfobj.get(doc, xref, "Rotate")
    rotation = int(value) % 360 if kind == "int" else 0
    ap = appearance.text_box(
        doc, *appearance.upright_size(box, rotation), text, size, (0, 0, 0), rotation
    )
    doc.xref_set_key(xref, "AP", f"<</N {ap} 0 R>>")


def set_text(doc, annot: Annot, text: str, rect: Rect | None = None) -> None:
    doc.xref_set_key(annot.xref, "Contents", pdfobj.text_string(text))
    if pdfobj.get(doc, annot.xref, "RC")[0] != "null":
        doc.xref_set_key(annot.xref, "RC", "null")  # 서식본이 남으면 옛 글이 보임
    if annot.ours and annot.kind == "FreeText":
        box = _user_rect(doc[annot.pno], rect or annot.rect)
        doc.xref_set_key(annot.xref, "Rect", f"[{n(*box)}]")
        _redraw_text(doc, annot.xref, box, text, annot.size)


def duplicate(doc, annot: Annot, pno: int, rect: Rect) -> int:
    """같은 문서의 pno 쪽 rect 자리에 복제. 겉모양(AP)은 원본과 함께 씀 (이 앱은 AP 를 고치지 않고 늘 새로 만듦)."""
    page = doc[pno]
    xref = pdfobj.new_object(doc, doc.xref_object(annot.xref, compressed=True))
    for key in ("Popup", "IRT", "StructParent", "Parent"):  # 원본에 매인 연결은 끊음
        if pdfobj.get(doc, xref, key)[0] != "null":
            doc.xref_set_key(xref, key, "null")
    doc.xref_set_key(xref, "NM", f"({OURS if annot.ours else ''}{uuid.uuid4().hex})")
    doc.xref_set_key(xref, "M", f"({time.strftime('D:%Y%m%d%H%M%S')})")
    doc.xref_set_key(xref, "P", f"{page.xref} 0 R")
    pdfobj.append_annot(doc, page, xref)
    move(doc, replace(annot, xref=xref, pno=pno), rect)
    return xref


def delete(doc, annot: Annot) -> None:
    page = doc[annot.pno]
    page.delete_annot(page.load_annot(annot.xref))
