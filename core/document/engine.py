"""PyMuPDF 읽기·렌더. 렌더 프로세스도 import 하므로 Qt 에 의존하지 않음."""

from __future__ import annotations

import gc
import logging

import pymupdf as mu
from pymupdf import mupdf

from . import pdfobj
from .models import DocumentError, PasswordRequired

log = logging.getLogger(__name__)

mu.TOOLS.mupdf_display_errors(False)
mu.TOOLS.mupdf_display_warnings(False)
mu.set_messages(pylogging=True)  # pythonw 에는 stdout 이 없음

TEXT_FLAGS = mu.TEXT_PRESERVE_WHITESPACE | mu.TEXT_MEDIABOX_CLIP
A4 = (595.0, 842.0)

# (원래 검정이 바뀔 색, 원래 흰색이 바뀔 색, 밝기 반전 여부)
THEMES = {
    "dark": (0x1E1E1E, 0xDCDCDC, True),
    "sepia": (0x3B2A1A, 0xF4ECD8, False),
    "gray": (0x101010, 0xC4C4C4, False),
}
FULL_PAGE_IMAGE = 0.85  # 이보다 큰 그림은 스캔한 쪽으로 보고 글자처럼 색을 바꿈


def open_pdf(source, password: str = "") -> mu.Document:
    """source 는 경로 또는 bytes."""
    doc, failure = None, ""
    try:
        if isinstance(source, (bytes, bytearray)):
            doc = mu.open(stream=source, filetype="pdf")
        else:
            doc = mu.open(str(source), filetype="pdf")
    except Exception as e:
        failure = str(e) or type(e).__name__
    if doc is None:
        gc.collect()  # 실패한 Document 가 파일을 쥔 채 남으면 작업 사본을 못 지움
        raise DocumentError("damaged", failure)
    if not doc.is_pdf:
        doc.close()
        raise DocumentError("not_pdf")
    if doc.needs_pass and not (password and doc.authenticate(password)):
        doc.close()
        raise PasswordRequired(wrong=bool(password))
    try:
        mupdf.pdf_disable_js(mu._as_pdf_document(doc))  # PDF JavaScript 는 실행하지 않음
        if doc.page_count < 1:
            raise DocumentError("damaged", "no pages")
    except Exception:
        doc.close()
        raise
    return doc


def page_matrix(page: mu.Page) -> mu.Matrix:
    """PDF 사용자 좌표 → 화면 좌표.

    page.transformation_matrix 는 회전과 CropBox 가 함께 있으면 어긋나서 쓰지 않음.
    """
    box, m = mupdf.FzRect(), mupdf.FzMatrix()
    mupdf.pdf_page_transform(mu._as_pdf_page(page), box, m)
    return mu.Matrix(m.a, m.b, m.c, m.d, m.e, m.f)


def page_sizes(doc: mu.Document) -> list[tuple[float, float]]:
    sizes = []
    for pno in range(doc.page_count):
        try:
            rect = doc[pno].rect
            ok = rect.width >= 1 and rect.height >= 1
            sizes.append((rect.width, rect.height) if ok else A4)
        except Exception:
            log.warning("%d쪽 크기를 읽지 못함", pno + 1)
            sizes.append(A4)
    return sizes


def page_blocks(doc: mu.Document, pno: int) -> list[dict]:
    display = doc[pno].get_displaylist(annots=False)
    return mu.TextPage(display.get_textpage(TEXT_FLAGS)).extractRAWDICT()["blocks"]


def hide_sign_tags(doc: mu.Document, pno: int) -> None:
    """MuPDF 는 미서명 서명 필드의 표시 스트림 대신 빨간 "SIGN" 표식을 그리고 평탄화에도 넣음.

    필드 종류를 누름단추로 바꿔 원래 모양대로 그리게 함. 저장하지 않는 사본에서만 부를 것.
    """
    annots = pdfobj.get(doc, doc.page_xref(pno), "Annots")
    for xref in pdfobj.refs(doc, annots):
        if pdfobj.get(doc, xref, "Subtype")[1] != "/Widget":
            continue
        if pdfobj.inherited(doc, xref, "FT")[1] != "/Sig":
            continue
        if pdfobj.inherited(doc, xref, "V")[0] == "null":
            doc.xref_set_key(xref, "FT", "/Btn")
            doc.xref_set_key(xref, "Ff", str(1 << 16))


class Renderer:
    """문서 하나의 렌더러. 같은 쪽의 타일은 DisplayList 를 재사용함.

    doc 은 저장하지 않는 사본이어야 함 (hide_sign_tags 가 객체를 바꿈).
    """

    KEEP = 8

    def __init__(self, doc: mu.Document):
        self.doc = doc
        self._lists: dict[int, mu.DisplayList] = {}
        self._images: dict[int, list[mu.Rect]] = {}

    def _display(self, pno: int) -> mu.DisplayList:
        display = self._lists.pop(pno, None)
        if display is None:
            hide_sign_tags(self.doc, pno)
            display = self.doc[pno].get_displaylist(annots=True)
        self._lists[pno] = display
        while len(self._lists) > self.KEEP:
            del self._lists[next(iter(self._lists))]
        return display

    def _pictures(self, pno: int) -> list[mu.Rect]:
        if pno not in self._images:
            page = self.doc[pno]
            limit = abs(page.rect) * FULL_PAGE_IMAGE
            turn = page.rotation_matrix  # bboxlog 는 회전 전 좌표로 옴
            boxes = [
                (mu.Rect(box) * turn).normalize() & page.rect
                for kind, box in page.get_bboxlog()
                if kind == "fill-image"
            ]
            self._images[pno] = [b for b in boxes if not b.is_empty and abs(b) < limit]
        return self._images[pno]

    def render(self, pno: int, scale: float, clip=None, theme: str = "light"):
        """(x, y, 폭, 높이, stride, RGB bytes). x·y·폭·높이는 scale 적용된 픽셀."""
        display = self._display(pno)
        area = mu.Rect(clip) if clip else display.rect
        pix = display.get_pixmap(
            matrix=mu.Matrix(scale, scale), colorspace=mu.csRGB, alpha=0, clip=area
        )
        if theme in THEMES:
            self._recolor(pix, pno, scale, theme)
        return pix.x, pix.y, pix.width, pix.height, pix.stride, pix.samples

    def _recolor(self, pix: mu.Pixmap, pno: int, scale: float, theme: str) -> None:
        black, white, invert = THEMES[theme]
        bounds = pix.irect
        keep = [
            part
            for box in self._pictures(pno)
            if not (part := (box * mu.Matrix(scale, scale)).irect & bounds).is_empty
        ]
        original = None
        if keep:
            original = mu.Pixmap(pix.colorspace, bounds, False)
            original.copy(pix, bounds)
        if invert:
            mupdf.fz_invert_pixmap_luminance(pix.this)  # 색상은 두고 밝기만 뒤집음
        pix.tint_with(black, white)
        for part in keep:
            pix.copy(original, part)
