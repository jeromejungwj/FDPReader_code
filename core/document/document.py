"""열린 PDF 한 개 (엔진 어댑터).

PyMuPDF(1.28)는 같은 핸들로 증분 저장을 두 번 하면 파일이 깨짐(0쪽이 됨). 그래서:
- 원본은 잡지 않고 작업 사본에서 일함
- 편집 1회 = 새로 연 핸들에서 증분 저장 1회 → 다시 열기
- Undo = 작업 사본을 편집 전 길이로 자름, Redo = 잘라 둔 꼬리를 다시 붙임
- 저장 = 작업 사본을 원본 자리에 원자적으로 교체 (원본 바이트가 앞부분에 그대로 남음)
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import pymupdf as mu

from storage import files

from . import annots, appearance, engine, fields, pdfobj
from .models import Annot, DocumentError, Field, Graphic, Link, Rect, TocItem
from .text import PageText

log = logging.getLogger(__name__)

TEXT_CACHE = 48


def _work_root() -> Path:
    root = files.data_dir() / "work"
    root.mkdir(exist_ok=True)
    return root


def sweep_stale_copies() -> None:
    """강제 종료로 남은 작업 사본 정리. 살아 있는 프로세스의 alive 파일은 지워지지 않음."""
    for folder in _work_root().iterdir():
        alive = folder / "alive"
        try:
            if alive.exists():
                alive.unlink()
            elif time.time() - folder.stat().st_mtime < 60:
                continue  # 막 만들어지는 중
            shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue


@dataclass
class _Step:
    start: int  # 편집 전 길이
    before: int
    after: int
    pages: tuple[int, ...] | None  # None = 전체
    relayout: bool
    tail: bytes = b""


class Document:
    def __init__(self, path, password: str = ""):
        self.path = Path(os.path.abspath(path))  # resolve() 는 네트워크 드라이브를 UNC 로 바꿔 버림
        self.password = password
        self.rebuilt = False  # 손상돼 다시 쓴 사본이면 True
        self.writable = True

        self._dir = Path(tempfile.mkdtemp(prefix="doc-", dir=_work_root()))
        self._alive = open(self._dir / "alive", "w")  # 열려 있는 동안 다른 프로세스가 못 지움
        self._work = self._dir / "work.pdf"
        self._doc: mu.Document | None = None
        self._renderer: engine.Renderer | None = None
        self._texts: OrderedDict[int, PageText] = OrderedDict()
        self._undo: list[_Step] = []
        self._redo: list[_Step] = []
        self._state = self._last_state = self._saved = 0
        self.version = 0
        try:
            self._stamp = self._disk_stamp()
            shutil.copyfile(self.path, self._work)
            os.chmod(self._work, 0o600)  # 읽기 전용 원본의 속성이 따라오지 않게
            self._doc = engine.open_pdf(self._work, password)
            if self._doc.is_repaired or not self._doc.can_save_incrementally():
                self._rebuild()
            self._length = self._work.stat().st_size
            self.page_count = self._doc.page_count
            self.sizes = engine.page_sizes(self._doc)
            self.permissions = self._doc.permissions
            self.encrypted = bool((self._doc.metadata or {}).get("encryption"))
        except Exception:
            self.close()
            raise
        self.page_gen = [0] * self.page_count
        self._forget()

    def _rebuild(self) -> None:
        fixed = self._dir / "fixed.pdf"
        try:
            self._doc.save(fixed, encryption=mu.PDF_ENCRYPT_KEEP)
            check = engine.open_pdf(fixed, self.password)
            good = check.page_count == self._doc.page_count and check.can_save_incrementally()
            check.close()
        except Exception:
            log.exception("손상된 문서를 다시 쓰지 못함")
            good = False
        if not good:
            self.writable = False  # 보기만 가능
            return
        self._doc.close()
        os.replace(fixed, self._work)
        self._doc = engine.open_pdf(self._work, self.password)
        self.rebuilt = True

    def close(self) -> None:
        self._drop_renderer()
        if self._doc is not None:
            self._doc.close()
            self._doc = None
        self._alive.close()
        shutil.rmtree(self._dir, ignore_errors=True)

    def _reopen(self) -> None:
        if self._doc is not None and not self._doc.is_closed:
            self._doc.close()
        self._doc = engine.open_pdf(self._work, self.password)

    def _drop_renderer(self) -> None:
        if self._renderer is not None:
            self._renderer.doc.close()
            self._renderer = None

    def _forget(self) -> None:
        self._drop_renderer()
        self._annots: dict[int, list[Annot]] = {}
        self._fields: dict[int, list[Field]] = {}
        self._links: dict[int, list[Link]] = {}

    # 권한

    def allows(self, what: str) -> bool:
        p = self.permissions
        if what == "copy":
            return bool(p & mu.PDF_PERM_COPY)
        if what == "print":
            return bool(p & mu.PDF_PERM_PRINT)
        if what == "print_hq":
            return bool(p & mu.PDF_PERM_PRINT_HQ)
        if not self.writable:
            return False
        if what == "annotate":
            return bool(p & mu.PDF_PERM_ANNOTATE)
        if what == "form":
            return bool(p & (mu.PDF_PERM_FORM | mu.PDF_PERM_ANNOTATE))
        if what == "rotate":
            return bool(p & (mu.PDF_PERM_MODIFY | mu.PDF_PERM_ASSEMBLE))
        if what == "flatten":
            return bool(p & mu.PDF_PERM_MODIFY)
        raise ValueError(what)

    # 편집·실행 취소

    def _edit(self, need: str, pages, change, relayout: bool = False):
        if not self.allows(need):
            raise DocumentError("permission" if self.writable else "read_only")
        start = self._length
        try:
            # 읽기만 해도 엔진이 빠진 표시 스트림을 만들어 두므로, 새 핸들에서만 고쳐야 같이 안 저장됨
            self._reopen()
            result = change(self._doc)
            self._doc.save(
                self._work, incremental=True, encryption=mu.PDF_ENCRYPT_KEEP, deflate=True
            )
            self._reopen()
            if self._doc.page_count != self.page_count or self._doc.is_repaired:
                raise DocumentError("write", "verification failed")
            length = self._work.stat().st_size
        except Exception as e:
            log.exception("편집을 되돌림")
            self._rollback(start)
            if isinstance(e, DocumentError):
                raise
            raise DocumentError("write", str(e)) from e
        self._length = length
        self._last_state += 1
        pages = tuple(pages) if pages is not None else None
        self._undo.append(_Step(start, self._state, self._last_state, pages, relayout))
        self._redo.clear()
        self._state = self._last_state
        self._changed(pages, relayout)
        return result

    def _rollback(self, length: int) -> None:
        if self._doc is not None and not self._doc.is_closed:
            self._doc.close()
        os.truncate(self._work, length)
        self._reopen()
        self._forget()

    def _changed(self, pages, relayout: bool) -> None:
        self.version += 1
        self._forget()
        if relayout:
            self.sizes = engine.page_sizes(self._doc)
            self._texts.clear()
        for pno in range(self.page_count) if pages is None else pages:
            self.page_gen[pno] += 1

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def dirty(self) -> bool:
        return self._state != self._saved

    def undo(self) -> _Step | None:
        if not self._undo:
            return None
        step = self._undo[-1]
        with open(self._work, "rb") as f:
            f.seek(step.start)
            step.tail = f.read()
        self._rollback(step.start)
        self._undo.pop()
        self._redo.append(step)
        self._length, self._state = step.start, step.before
        self._changed(step.pages, step.relayout)
        return step

    def redo(self) -> _Step | None:
        if not self._redo:
            return None
        step = self._redo[-1]
        self._doc.close()
        try:
            with open(self._work, "ab") as f:
                f.write(step.tail)
            self._reopen()
        except Exception as e:
            self._rollback(self._length)
            raise DocumentError("write", str(e)) from e
        self._redo.pop()
        self._undo.append(step)
        self._length, self._state = self._work.stat().st_size, step.after
        step.tail = b""
        self._changed(step.pages, step.relayout)
        return step

    # 주석·양식·회전

    def add_markup(self, kind: str, spans: list[tuple[int, list]], color, text="") -> int:
        """spans: [(쪽, PageText.quads 결과)]."""
        def change(doc):
            return [annots.add_markup(doc, p, kind, r, color, text) for p, r in spans][0]

        return self._edit("annotate", [p for p, _ in spans], change)

    def add_note(self, pno: int, x: float, y: float, text: str, color, view_rotation=0) -> int:
        return self._edit(
            "annotate", [pno], lambda d: annots.add_note(d, pno, x, y, text, color, view_rotation)
        )

    def add_text(self, pno: int, rect: Rect, text: str, size: float, view_rotation=0) -> int:
        return self._edit(
            "annotate", [pno], lambda d: annots.add_text(d, pno, rect, text, size, view_rotation)
        )

    def add_signature(
        self, pno: int, rect: Rect, graphic: Graphic, view_rotation=0, as_ink=False
    ) -> int:
        return self._edit(
            "annotate",
            [pno],
            lambda d: annots.add_signature(d, pno, rect, graphic, view_rotation, as_ink),
        )

    def move_annot(self, annot: Annot, rect: Rect) -> None:
        self._edit("annotate", [annot.pno], lambda d: annots.move(d, annot, rect))

    def set_annot_text(self, annot: Annot, text: str, rect: Rect | None = None) -> None:
        self._edit("annotate", [annot.pno], lambda d: annots.set_text(d, annot, text, rect))

    def duplicate_annot(self, annot: Annot, pno: int, rect: Rect) -> int:
        return self._edit("annotate", [pno], lambda d: annots.duplicate(d, annot, pno, rect))

    def page_rotation(self, pno: int) -> int:
        return self._doc[pno].rotation

    def delete_annot(self, annot: Annot) -> None:
        self._edit("annotate", [annot.pno], lambda d: annots.delete(d, annot))

    def set_field(self, field: Field, value) -> None:
        shared = fields.widget_count(self._doc, field.xref) > 1  # 다른 쪽에도 보이는 필드
        whole = shared or fields.needs_appearances(self._doc)

        def change(doc):
            fields.settle_appearances(doc)
            fields.set_value(doc, field, value)

        self._edit("form", None if whole else [field.pno], change)

    def rotate_pages(self, degrees: int) -> None:
        def change(doc):
            for page in doc:
                page.set_rotation((page.rotation + degrees) % 360)

        self._edit("rotate", None, change, relayout=True)

    @staticmethod
    def text_height(text: str, size: float, width: float) -> float:
        return appearance.text_height(text, size, width)

    # 읽기. 손상된 쪽 하나 때문에 앱이 죽지 않도록 쪽 단위로 실패를 삼킴

    def _per_page(self, cache: dict, pno: int, read):
        if pno not in cache:
            try:
                cache[pno] = read(self._doc, pno)
            except Exception:
                log.exception("%d쪽을 읽지 못함", pno + 1)
                cache[pno] = []
        return cache[pno]

    def annots(self, pno: int) -> list[Annot]:
        return self._per_page(self._annots, pno, annots.read)

    def fields(self, pno: int) -> list[Field]:
        return self._per_page(self._fields, pno, fields.read)

    def links(self, pno: int) -> list[Link]:
        return self._per_page(self._links, pno, self._read_links)

    def text(self, pno: int) -> PageText:
        found = self._texts.pop(pno, None)
        if found is None:
            try:
                found = PageText(engine.page_blocks(self._doc, pno))
            except Exception:
                log.exception("%d쪽 글자를 읽지 못함", pno + 1)
                found = PageText()
        self._texts[pno] = found
        if len(self._texts) > TEXT_CACHE:
            self._texts.popitem(last=False)
        return found

    def _target_y(self, doc, pno: int, point) -> float | None:
        # 링크·목차의 목적지는 회전 전 좌표라 회전된 쪽은 맨 위로 이동
        if point is None or doc[pno].rotation:
            return None
        y = float(point.y)
        return y if 0 < y < self.sizes[pno][1] else None

    def _read_links(self, doc, pno: int) -> list[Link]:
        page = doc[pno]
        out = []
        for link in page.get_links():
            box = pdfobj.rect(doc, link["xref"]) if link.get("xref") else None
            shown = box * engine.page_matrix(page) if box else mu.Rect(link["from"])
            rect = tuple(shown.normalize())
            kind = link["kind"]
            target = link.get("page", -1)
            target = int(target) if str(target).lstrip("-").isdigit() else -1
            if kind in (mu.LINK_GOTO, mu.LINK_NAMED) and 0 <= target < self.page_count:
                y = self._target_y(doc, target, link.get("to"))
                out.append(Link(rect, "page", page=target, y=y))
            elif kind == mu.LINK_URI and link.get("uri"):
                out.append(Link(rect, "uri", target=link["uri"]))
            elif kind == mu.LINK_GOTOR and link.get("file"):
                out.append(Link(rect, "file", page=max(target, 0), target=link["file"]))
            elif kind == mu.LINK_LAUNCH and link.get("file"):
                out.append(Link(rect, "launch", target=link["file"]))
        return out

    def toc(self) -> list[TocItem]:
        out = []
        try:
            for level, title, page, *rest in self._doc.get_toc(simple=False):
                pno, y = page - 1, None
                if 0 <= pno < self.page_count and rest:
                    y = self._target_y(self._doc, pno, rest[0].get("to"))
                out.append(TocItem(level, title, pno, y))
        except Exception:
            log.exception("목차를 읽지 못함")
        return out

    @cached_property
    def has_xfa(self) -> bool:
        try:
            catalog = self._doc.pdf_catalog()
            return self._doc.xref_get_key(catalog, "AcroForm/XFA")[0] != "null"
        except Exception:
            return False

    @cached_property
    def has_digital_signature(self) -> bool:
        try:
            for page in self._doc:
                for widget in page.widgets(types=[mu.PDF_WIDGET_TYPE_SIGNATURE]):
                    if widget.is_signed:
                        return True
        except Exception:
            log.exception("서명 필드를 확인하지 못함")
        return False

    def render(self, pno: int, scale: float, clip=None, theme: str = "light"):
        """이 프로세스에서 바로 렌더 (서명 배경·인쇄용). 화면 타일은 core.render 가 맡음."""
        if self._renderer is None:
            copy = engine.open_pdf(self._work.read_bytes(), self.password)
            self._renderer = engine.Renderer(copy)
        return self._renderer.render(pno, scale, clip, theme)

    def render_source(self) -> tuple:
        return str(self._work), self._length, self.version, self.password

    def printer(self, with_annots: bool) -> "PrintCopy":
        if not self.allows("print"):
            raise DocumentError("permission")
        return PrintCopy(self._work.read_bytes(), self.password, with_annots)

    # 저장

    def _disk_stamp(self) -> tuple[int, int]:
        stat = self.path.stat()
        return stat.st_mtime_ns, stat.st_size

    def changed_on_disk(self) -> bool:
        try:
            return self._disk_stamp() != self._stamp
        except OSError:
            return False  # 지워졌으면 덮어쓸 것이 없음

    def save(self, target=None) -> None:
        target = Path(os.path.abspath(target)) if target else self.path
        try:
            files.copy_atomic(self._work, target)
        except OSError as e:
            raise DocumentError("write", str(e)) from e
        self.path, self._saved = target, self._state
        self.rebuilt = False  # 이제 디스크에 있는 파일이 멀쩡한 본임
        self._stamp = self._disk_stamp()

    def export_flattened(self, target) -> None:
        if not self.allows("flatten"):
            raise DocumentError("permission")
        target = Path(os.path.abspath(target))
        if os.path.normcase(target) == os.path.normcase(self.path):
            raise DocumentError("write", "flattened copy must not replace the original")
        copy = engine.open_pdf(self._work.read_bytes(), self.password)
        try:
            fields.settle_appearances(copy)
            for pno in range(copy.page_count):
                engine.hide_sign_tags(copy, pno)
            copy.bake()
            files.write_atomic(
                target,
                lambda tmp: copy.save(
                    tmp, garbage=3, deflate=True, encryption=mu.PDF_ENCRYPT_KEEP
                ),
            )
        except Exception as e:
            raise DocumentError("write", str(e)) from e
        finally:
            copy.close()


class PrintCopy:
    """인쇄용 사본. '주석 제외'여도 양식에 입력한 값은 남김."""

    def __init__(self, data: bytes, password: str, with_annots: bool):
        self._doc = engine.open_pdf(data, password)
        self._with_annots = with_annots

    def render(self, pno: int, scale: float):
        engine.hide_sign_tags(self._doc, pno)
        page = self._doc[pno]
        if not self._with_annots:
            for xref, kind, *_ in page.annot_xrefs():
                if kind not in (mu.PDF_ANNOT_WIDGET, mu.PDF_ANNOT_LINK, mu.PDF_ANNOT_POPUP):
                    page.delete_annot(page.load_annot(xref))
            page = self._doc.reload_page(page)
        pix = page.get_pixmap(matrix=mu.Matrix(scale, scale), colorspace=mu.csRGB, alpha=False)
        return pix.x, pix.y, pix.width, pix.height, pix.stride, pix.samples

    def close(self) -> None:
        self._doc.close()
