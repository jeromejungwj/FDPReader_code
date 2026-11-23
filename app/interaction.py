"""선택, 주석, 양식, 서명 배치. 마우스와 키보드 양쪽으로 모두 조작됨."""

from __future__ import annotations

import logging

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QApplication, QMenu, QToolTip

from core.document.models import Annot, DocumentError, Field, Graphic, Link
from features.annot.editors import TextEditor, ask_note
from features.forms.editors import FieldEditor

from . import ui
from .i18n import T
from .page_view import PageView

log = logging.getLogger(__name__)

MARKUPS = ("Highlight", "Underline", "StrikeOut")
TEXT_MARKS = (*MARKUPS, "Squiggly")
NOTE_YELLOW = (1.0, 0.85, 0.25)
PLACE_WIDTH = 150.0  # 저장 서명을 클릭으로 놓을 때 폭(pt)
TEXT_BOX_WIDTH = 240.0
MIN_AREA = 8.0  # 이보다 작게 끌면 클릭으로 봄 (px)
MIN_SIZE = 8.0  # 주석 최소 크기 (pt)
HANDLE = 10.0
FILLABLE = QColor(47, 111, 222, 28)
SELECTION = QColor(47, 111, 222, 80)
FOUND = QColor(255, 170, 0, 80)
FOUND_NOW = QColor(255, 100, 0, 130)
ACCENT = QColor("#2f6fde")


def contains(rect, x: float, y: float, slack: float = 0.0) -> bool:
    x0, y0, x1, y1 = rect
    return x0 - slack <= x <= x1 + slack and y0 - slack <= y <= y1 + slack


def area(rect) -> float:
    return (rect[2] - rect[0]) * (rect[3] - rect[1])


class EditView(PageView):
    edited = Signal()
    tool_changed = Signal()
    selection_changed = Signal()
    sign_requested = Signal(int, object)  # 쪽, 영역
    open_requested = Signal(object)  # Link
    message = Signal(str)

    def __init__(self, document, service, state, parent=None):
        super().__init__(document, service, state["theme"], parent)
        self.settings = state
        self.tool = "select"
        self.hits: dict[int, list] = {}  # 검색 결과: 쪽 → [(a, b)]
        self.hit_now: tuple | None = None

        self._placing: Graphic | None = None
        self._selection: tuple | None = None  # ((쪽, 글자), (쪽, 글자))
        self._picked: Annot | None = None
        self._picked_rect: tuple | None = None  # 움직이는 중의 자리
        self._focused: Field | Link | None = None
        self._focused_page = 0
        self._press: dict | None = None
        self._rubber: QRectF | None = None
        self._editor: TextEditor | FieldEditor | None = None
        self._editing: dict = {}
        self._last_double: QPointF | None = None
        self._triple = QTimer(self, singleShot=True)
        self._triple.timeout.connect(self._forget_double)
        self._nudge = QTimer(self, singleShot=True, interval=500)
        self._nudge.timeout.connect(self._finish_nudge)
        self._autoscroll = QTimer(self, interval=30)
        self._autoscroll.timeout.connect(self._scroll_while_dragging)
        QApplication.instance().focusChanged.connect(self._focus_moved)

    # 공통

    def run_edit(self, change) -> tuple[bool, object]:
        try:
            result = change()
        except DocumentError as error:
            ui.warn(self.window(), ui.error_text(error))
            self.after_change()
            return False, None
        self.after_change()
        return True, result

    def after_change(self) -> None:
        if self._picked is not None:
            xref, pno = self._picked.xref, self._picked.pno
            found = next((a for a in self.doc.annots(pno) if a.xref == xref), None)
            self._set_picked(found)
        if isinstance(self._focused, Field):
            old = self._focused
            fields = self.doc.fields(old.pno)
            self._focused = next((f for f in fields if f.xref == old.xref), None)
        self.after_move()
        self.edited.emit()

    def commit(self) -> bool:
        """입력 중인 것을 문서에 반영. 저장·실행 취소·탭 닫기 전에 반드시 부름."""
        self._finish_nudge()
        return self._close_editor(True)

    def allowed(self, what: str) -> bool:
        if self.doc.allows(what):
            return True
        code = "read_only" if what != "copy" and not self.doc.writable else "permission"
        self.message.emit(ui.error_text(DocumentError(code)))
        return False

    def set_tool(self, tool: str, graphic: Graphic | None = None) -> None:
        self.commit()
        if tool != "select" and not self.allowed("annotate"):
            tool, graphic = "select", None
        self.tool, self._placing = tool, graphic
        self._rubber = None
        if tool in MARKUPS and self._selection:
            self.markup(tool)
        elif tool != "select":
            self._set_picked(None)
        hints = {
            "select": "",
            "note": T("메모를 놓을 자리를 클릭하세요.", "Click where the note should go."),
            "text": T("글자를 넣을 자리를 클릭하세요.", "Click where the text should go."),
            "sign": T(
                "서명할 영역을 드래그하거나 서명 필드를 클릭하세요. Enter는 화면 가운데입니다.",
                "Drag the area to sign or click a signature field. Enter uses the screen centre.",
            ),
            "place": T(
                "서명을 놓을 자리를 클릭하거나 드래그하세요. Enter는 화면 가운데입니다.",
                "Click or drag where the signature goes. Enter uses the screen centre.",
            ),
        }
        self.message.emit(hints.get(tool, T("글자를 드래그하세요. Esc로 끝냅니다.",
                                            "Drag over text. Esc to finish.")))
        shape = Qt.CursorShape.ArrowCursor if tool == "select" else Qt.CursorShape.CrossCursor
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor if tool in MARKUPS else shape)
        self.setFocus()
        self.after_move()
        self.tool_changed.emit()

    def _set_picked(self, annot: Annot | None) -> None:
        self._picked = annot
        self._picked_rect = annot.rect if annot else None
        self.selection_changed.emit()

    def deselect(self) -> None:
        self._finish_nudge()
        self._selection = self._focused = None
        self._set_picked(None)
        self.viewport().update()

    def page_geometry_changed(self) -> None:
        self._selection = self._focused = None
        self._set_picked(None)
        super().page_geometry_changed()

    # 글자 선택

    def spans(self) -> list[tuple[int, int, int]]:
        if not self._selection:
            return []
        (p0, a), (p1, b) = sorted(self._selection)
        if p0 == p1:
            return [(p0, a, b)] if a < b else []
        out = [(p0, a, len(self.doc.text(p0).text))]
        out += [(p, 0, len(self.doc.text(p).text)) for p in range(p0 + 1, p1)]
        out.append((p1, 0, b))
        return out

    @property
    def has_selection(self) -> bool:
        return bool(self._selection) and self._selection[0] != self._selection[1]

    def copy(self) -> None:
        if not self.has_selection or not self.allowed("copy"):
            return
        parts = [self.doc.text(p).copy_text(a, b) for p, a, b in self.spans()]
        QGuiApplication.clipboard().setText("\n".join(p for p in parts if p))
        self.message.emit(T("복사했습니다.", "Copied."))

    def select_page(self) -> None:
        self._set_picked(None)
        self._selection = ((self.page, 0), (self.page, len(self.doc.text(self.page).text)))
        self.viewport().update()
        self.selection_changed.emit()

    def markup(self, kind: str, text: str = "") -> None:
        pages = [(p, self.doc.text(p).quads(a, b)) for p, a, b in self.spans()]
        pages = [(p, quads) for p, quads in pages if quads]
        if not pages or not self.allowed("annotate"):
            return
        color = QColor(self.settings["color"])
        rgb = color.redF(), color.greenF(), color.blueF()
        self._selection = None
        self.run_edit(lambda: self.doc.add_markup(kind, pages, rgb, text))

    def markup_with_note(self) -> None:
        if self.has_selection and self.allowed("annotate"):
            text = ask_note(self.window())
            if text is not None:
                self.markup("Highlight", text)

    def _extend_selection(self, key) -> None:
        if not self._selection:
            self._selection = ((self.page, 0), (self.page, 0))
        start, (pno, index) = self._selection
        page = self.doc.text(pno)
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            index += 1 if key == Qt.Key.Key_Right else -1
            if index < 0 and pno > 0:
                pno -= 1
                index = len(self.doc.text(pno).text)
            elif index > len(page.text) and pno + 1 < self.doc.page_count:
                pno, index = pno + 1, 0
        elif page.lines:
            start_of_line, _ = page.line(min(max(index, 0), len(page.text) - 1))
            row = next(i for i, line in enumerate(page.lines) if line.start == start_of_line)
            column = index - start_of_line
            row += 1 if key == Qt.Key.Key_Down else -1
            if row < 0:
                index = 0
            elif row >= len(page.lines):
                index = len(page.text)
            else:
                line = page.lines[row]
                index = min(line.start + column, line.end)
        index = min(max(index, 0), len(self.doc.text(pno).text))
        self._selection = (start, (pno, index))
        self.viewport().update()
        self.selection_changed.emit()

    # 무엇 위에 있나

    def _annot_at(self, pno, x, y) -> Annot | None:
        w, h = self.doc.sizes[pno]
        for annot in reversed(self.doc.annots(pno)):
            if not contains(annot.rect, x, y):
                continue
            if annot.kind in TEXT_MARKS:
                continue  # 글자 선택을 막지 않게 따로 처리
            if not annot.ours and area(annot.rect) > 0.5 * w * h:
                continue  # 쪽 전체를 덮는 워터마크
            return annot
        return None

    def _mark_at(self, pno, x, y) -> Annot | None:
        return next(
            (
                a for a in reversed(self.doc.annots(pno))
                if a.kind in TEXT_MARKS and contains(a.rect, x, y)
            ),
            None,
        )

    def _field_at(self, pno, x, y) -> Field | None:
        return next((f for f in self.doc.fields(pno) if contains(f.rect, x, y)), None)

    def _link_at(self, pno, x, y) -> Link | None:
        return next((k for k in self.doc.links(pno) if contains(k.rect, x, y)), None)

    def _handle_at(self, position: QPointF) -> int | None:
        if not self._picked or not self._picked.resizable:
            return None
        box = self.to_view(self._picked.pno, self._picked_rect)
        if box is None:
            return None
        corners = (box.topLeft(), box.topRight(), box.bottomRight(), box.bottomLeft())
        for index, corner in enumerate(corners):
            if (corner - position).manhattanLength() <= HANDLE:
                return index
        return None

    # 마우스

    def mousePressEvent(self, event) -> None:
        self.setFocus()
        position = event.position()
        self.commit()
        where = self.hit(position)
        if where is None or event.button() != Qt.MouseButton.LeftButton:
            return
        pno, x, y, inside = where
        self._focused = None
        press = self._press = {"at": position, "page": pno, "xy": (x, y), "moved": False}

        if self._last_double is not None:
            near = (position - self._last_double).manhattanLength() < 8
            self._forget_double()
            if near and self.tool in ("select", *MARKUPS):  # 세 번 클릭 = 한 줄
                page = self.doc.text(pno)
                index = page.char_at(x, y)
                if index is not None:
                    a, b = page.line(index)
                    self._selection = ((pno, a), (pno, b))
                    press["do"] = "word"
                    self.viewport().update()
                    return

        if self.tool in ("note", "text", "sign", "place"):
            press["do"] = "area" if inside else "none"
            return
        if self.tool == "select":
            handle = self._handle_at(position)
            if handle is not None:
                press.update(do="resize", handle=handle, rect=self._picked.rect)
                press["page"] = self._picked.pno
                return
            if inside:
                annot = self._annot_at(pno, x, y)
                if annot:
                    self._selection = None
                    self._set_picked(annot)
                    press.update(do="move" if annot.movable else "none", rect=annot.rect)
                    self.viewport().update()
                    return
                field = self._field_at(pno, x, y)
                if field:
                    self.deselect()
                    press.update(do="field", field=field)
                    return
                press["link"] = self._link_at(pno, x, y)
                press["mark"] = self._mark_at(pno, x, y)
        self._set_picked(None)
        caret = self.doc.text(pno).caret(x, y)
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and self._selection:
            self._selection = (self._selection[0], (pno, caret))
        else:
            self._selection = ((pno, caret), (pno, caret))
        press["do"] = "text"
        self.viewport().update()

    def mouseMoveEvent(self, event) -> None:
        if not self._press:
            self._hover(event)
            return
        position = event.position()
        if not self._press["moved"]:
            if (position - self._press["at"]).manhattanLength() < 4:
                return
            self._press["moved"] = True
        self._drag(position)
        outside = not self.viewport().rect().contains(position.toPoint())
        if self._press.get("do") == "text" and outside:
            self._autoscroll.start()
        else:
            self._autoscroll.stop()

    def _drag(self, position: QPointF) -> None:
        press = self._press
        what = press.get("do")
        if what == "text":
            where = self.hit(position)
            if where:
                pno, x, y, _ = where
                self._selection = (self._selection[0], (pno, self.doc.text(pno).caret(x, y)))
        elif what == "area":
            self._rubber = QRectF(press["at"], position).normalized()
            page = self.to_view(press["page"], (0, 0, *self.doc.sizes[press["page"]]))
            self._rubber = self._rubber.intersected(page)
        elif what in ("move", "resize") and self._picked:
            transform = self.transform_of(press["page"])
            if transform is None:
                return
            point = transform.inverted()[0].map(position)
            dx, dy = point.x() - press["xy"][0], point.y() - press["xy"][1]
            if what == "move":
                self._picked_rect = self._moved(press["rect"], press["page"], dx, dy)
            else:
                self._picked_rect = self._resize_rect(
                    press["rect"], press["page"], press["handle"], point
                )
        self.viewport().update()

    def _moved(self, rect, pno: int, dx: float, dy: float) -> tuple:
        x0, y0, x1, y1 = rect
        w, h = self.doc.sizes[pno]
        dx = min(max(dx, -x0), max(w - x1, -x0))
        dy = min(max(dy, -y0), max(h - y1, -y0))
        return x0 + dx, y0 + dy, x1 + dx, y1 + dy

    def _resize_rect(self, rect, pno: int, handle: int, point: QPointF) -> tuple:
        x0, y0, x1, y1 = rect
        # 화면에서 잡은 모서리의 맞은편(고정점)을 쪽 좌표로 구함
        box = self.to_view(pno, rect)
        corners = (box.topLeft(), box.topRight(), box.bottomRight(), box.bottomLeft())
        fixed = self.transform_of(pno).inverted()[0].map(corners[(handle + 2) % 4])
        sx = 1 if fixed.x() < (x0 + x1) / 2 else -1
        sy = 1 if fixed.y() < (y0 + y1) / 2 else -1
        w = max((point.x() - fixed.x()) * sx, MIN_SIZE)
        h = max((point.y() - fixed.y()) * sy, MIN_SIZE)
        page_w, page_h = self.doc.sizes[pno]
        room_w = max(page_w - fixed.x() if sx > 0 else fixed.x(), MIN_SIZE)
        room_h = max(page_h - fixed.y() if sy > 0 else fixed.y(), MIN_SIZE)
        if self._picked.kind == "FreeText":
            w, h = min(w, room_w), min(h, room_h)
        else:  # 서명은 비율 유지
            ow, oh = max(x1 - x0, 1e-3), max(y1 - y0, 1e-3)
            factor = min(max(w / ow, h / oh), room_w / ow, room_h / oh)
            w, h = ow * factor, oh * factor
        ax, bx = sorted((fixed.x(), fixed.x() + sx * w))
        ay, by = sorted((fixed.y(), fixed.y() + sy * h))
        return ax, ay, bx, by

    def _scroll_while_dragging(self) -> None:
        if not self._press:
            self._autoscroll.stop()
            return
        position = QPointF(self.viewport().mapFromGlobal(self.cursor().pos()))
        below = position.y() - self.viewport().height()
        step = below if below > 0 else min(position.y(), 0)
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + int(step / 3))
        self._drag(position)

    def mouseReleaseEvent(self, event) -> None:
        self._autoscroll.stop()
        press, self._press = self._press, None
        if not press:
            return
        what, moved = press.get("do"), press["moved"]
        if what == "area":
            rubber, self._rubber = self._rubber, None
            self._area_chosen(press, rubber)
        elif what in ("move", "resize"):
            if moved and self._picked and self._picked_rect != self._picked.rect:
                annot, rect = self._picked, self._picked_rect
                self.run_edit(lambda: self.doc.move_annot(annot, rect))
        elif what == "field" and not moved:
            self.activate(press["field"])
        elif what == "text":
            if not moved:
                if press.get("link"):
                    self._selection = None
                    self.follow(press["link"])
                elif press.get("mark"):
                    self._selection = None
                    self._set_picked(press["mark"])
            elif self.tool in MARKUPS:
                self.markup(self.tool)
            self.selection_changed.emit()
        elif what == "word" and self.tool in MARKUPS:
            self.markup(self.tool)
        self.viewport().update()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        where = self.hit(event.position())
        if not where or not where[3] or self.tool not in ("select", *MARKUPS):
            self.mousePressEvent(event)
            return
        pno, x, y, _ = where
        if self.tool == "select":
            annot = self._annot_at(pno, x, y)
            if annot:
                self.edit_annot(annot)
                return
            if self._field_at(pno, x, y):
                return
            mark = self._mark_at(pno, x, y)
            if mark:
                self.edit_annot(mark)
                return
        page = self.doc.text(pno)
        index = page.char_at(x, y)
        if index is not None:
            a, b = page.word(index)
            self._selection = ((pno, a), (pno, b))
            self._press = {"at": event.position(), "page": pno, "xy": (x, y),
                           "moved": False, "do": "word"}
            if self.tool == "select":
                self._last_double = event.position()
                self._triple.start(QApplication.doubleClickInterval())
            self.viewport().update()
            self.selection_changed.emit()

    def _forget_double(self) -> None:
        self._last_double = None
        self._triple.stop()

    def _hover(self, event) -> None:
        if self.tool != "select":
            return
        position = event.position()
        shape, tip = Qt.CursorShape.ArrowCursor, ""
        handle = self._handle_at(position)
        where = self.hit(position)
        if handle is not None:
            diagonal = handle % 2 == 0
            shape = Qt.CursorShape.SizeFDiagCursor if diagonal else Qt.CursorShape.SizeBDiagCursor
        elif where and where[3]:
            pno, x, y, _ = where
            annot = self._annot_at(pno, x, y) or self._mark_at(pno, x, y)
            if annot and annot.movable:
                shape = Qt.CursorShape.SizeAllCursor
            if annot and annot.kind not in ("FreeText", "Stamp", "Ink"):
                tip = annot.text
            if shape == Qt.CursorShape.ArrowCursor:
                field = self._field_at(pno, x, y)
                link = None if field else self._link_at(pno, x, y)
                if field and not field.read_only:
                    typed = field.kind in ("text", "combo")
                    shape = Qt.CursorShape.IBeamCursor if typed else Qt.CursorShape.PointingHandCursor
                elif link:
                    shape = Qt.CursorShape.PointingHandCursor
                    tip = tip or link.target
                elif not field and self.doc.text(pno).char_at(x, y) is not None:
                    shape = Qt.CursorShape.IBeamCursor
        self.viewport().setCursor(shape)
        if tip:
            QToolTip.showText(event.globalPosition().toPoint(), ui.plain_tooltip(tip), self.viewport())
        else:
            QToolTip.hideText()

    def _area_chosen(self, press: dict, rubber: QRectF | None) -> None:
        pno, (x, y) = press["page"], press["xy"]
        dragged = rubber is not None and rubber.width() >= MIN_AREA and rubber.height() >= MIN_AREA
        rect = self.to_page_rect(pno, rubber) if dragged else None
        field = None if dragged else self._field_at(pno, x, y)
        if field and field.kind == "signature":
            if field.value:
                self.message.emit(T("이미 디지털 서명된 필드입니다.", "This field is already signed."))
                return
            rect = field.rect
        if self.tool == "note":
            self.set_tool("select")
            self.add_note(pno, x, y)
        elif self.tool == "text":
            box = rubber if dragged else None
            self.set_tool("select")
            self.begin_text(pno, x, y, box)
        elif self.tool == "sign":
            if rect is None:
                self.message.emit(
                    T("서명할 영역을 드래그해 주세요.", "Drag to mark the area to sign.")
                )
                return
            self.set_tool("select")
            self.sign_requested.emit(pno, rect)
        elif self.tool == "place" and self._placing:
            graphic = self._placing
            rect = rect or self.default_area(pno, x, y, graphic.aspect)
            self.set_tool("select")
            self.place_signature(pno, rect, graphic)

    # 만들기

    def default_area(self, pno: int, x: float, y: float, aspect: float) -> tuple:
        """(x, y) 가운데의 기본 크기 서명 자리."""
        page_w, page_h = self.doc.sizes[pno]
        ratio = 1 / aspect if self.rotation % 180 else aspect
        w = PLACE_WIDTH * ratio if self.rotation % 180 else PLACE_WIDTH
        h = w / ratio
        shrink = min(1.0, page_w / w, page_h / h, 120 / min(w, h))
        w, h = w * shrink, h * shrink
        x0 = min(max(x - w / 2, 0), page_w - w)
        y0 = min(max(y - h / 2, 0), page_h - h)
        return x0, y0, x0 + w, y0 + h

    def place_signature(self, pno: int, rect, graphic: Graphic) -> bool:
        """영역 안에 비율을 유지해 넣고, 이어서 옮기거나 크기를 바꿀 수 있게 선택해 둠."""
        x0, y0, x1, y1 = rect
        ratio = 1 / graphic.aspect if self.rotation % 180 else graphic.aspect
        w = min(x1 - x0, (y1 - y0) * ratio)
        h = w / ratio
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        target = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        as_ink = self.settings["sign_as_ink"]
        ok, xref = self.run_edit(
            lambda: self.doc.add_signature(pno, target, graphic, self.rotation, as_ink)
        )
        if ok:
            self._pick_xref(pno, xref)
        return ok

    def _pick_xref(self, pno: int, xref: int) -> None:
        self._selection = None
        self._set_picked(next((a for a in self.doc.annots(pno) if a.xref == xref), None))
        self.setFocus()
        self.viewport().update()

    def add_note(self, pno: int, x: float, y: float) -> None:
        text = ask_note(self.window())
        if text is not None:
            ok, xref = self.run_edit(
                lambda: self.doc.add_note(pno, x, y, text, NOTE_YELLOW, self.rotation)
            )
            if ok:
                self._pick_xref(pno, xref)

    def begin_text(self, pno: int, x: float, y: float, box: QRectF | None = None) -> None:
        size = float(self.settings["text_size"])
        page = self.to_view(pno, (0, 0, *self.doc.sizes[pno]))
        if box is None:
            top_left = self.transform_of(pno).map(QPointF(x, y))
            top_left.setX(min(top_left.x(), page.right() - 40))
            width = min(TEXT_BOX_WIDTH * self.scale, page.right() - top_left.x())
            box = QRectF(top_left, top_left + QPointF(width, size * 1.6 * self.scale))
        editor = TextEditor(self.viewport())
        self._show_editor(editor, pno, self.to_page_rect(pno, box), size)

    def edit_annot(self, annot: Annot) -> None:
        self.commit()
        self._set_picked(annot)
        writable = not annot.locked and self.doc.allows("annotate")
        if annot.kind == "FreeText" and annot.ours and writable:
            editor = TextEditor(self.viewport(), annot.text)
            self._show_editor(editor, annot.pno, annot.rect, annot.size, annot)
            return
        # 다른 앱의 타자기 글은 모양을 다시 만들 수 없어 보기만 함
        read_only = not writable or annot.kind == "FreeText"
        text = ask_note(self.window(), annot.text, read_only)
        if text is not None and text != annot.text:
            self.run_edit(lambda: self.doc.set_annot_text(annot, text))

    def activate(self, field: Field) -> None:
        if field.kind == "signature":
            if field.value:
                self.message.emit(T("이미 디지털 서명된 필드입니다.", "This field is already signed."))
            elif self.allowed("annotate"):
                self.sign_requested.emit(field.pno, field.rect)
            return
        if field.read_only:
            self.message.emit(T("읽기 전용 필드입니다.", "This field is read-only."))
            return
        if not self.allowed("form"):
            return
        self._focused = field
        if field.kind in ("check", "radio"):
            if field.kind == "check" or not field.value:
                self.run_edit(lambda: self.doc.set_field(field, not field.value))
            return
        box = self.to_view(field.pno, field.rect)
        if box is None:
            return
        size = field.font_size or (11 if field.multiline else min(box.height() / self.scale * 0.6, 12))
        editor = FieldEditor(self.viewport(), field, max(int(size * self.scale), 9))
        self._show_editor(editor, field.pno, field.rect, size)

    # 입력기

    def _show_editor(self, editor, pno: int, rect, size: float, annot: Annot | None = None) -> None:
        self._editor = editor
        self._editing = {"page": pno, "rect": rect, "size": size, "annot": annot}
        if isinstance(editor, TextEditor):
            editor.done.connect(lambda ok: self._editor_finished(ok))
            editor.textChanged.connect(self._fit_editor)
        else:
            editor.done.connect(self._editor_finished)
        self._fit_editor()
        editor.show()
        editor.setFocus()
        if isinstance(editor, TextEditor):
            cursor = editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            editor.setTextCursor(cursor)

    def _fit_editor(self) -> None:
        editor = self._editor
        if editor is None:
            return
        box = self.to_view(self._editing["page"], self._editing["rect"])
        if box is None:
            editor.move(-5000, 0)
            return
        if isinstance(editor, TextEditor):
            size = self._editing["size"]
            font = editor.font()
            font.setFamilies(["Malgun Gothic"])
            font.setPixelSize(max(int(size * self.scale), 6))
            editor.setFont(font)
            needed = self.doc.text_height(editor.toPlainText() + " ", size, box.width() / self.scale)
            box.setHeight(max(box.height(), needed * self.scale + 4))
        elif editor.field.kind not in ("list",) and not editor.field.multiline:
            box.setHeight(max(box.height(), 20))
            box.setWidth(max(box.width(), 90 if editor.field.date_format else 40))
        editor.setGeometry(box.toAlignedRect())

    def after_move(self) -> None:
        super().after_move()
        self._fit_editor()

    def _editor_finished(self, ok: bool, step: int = 0) -> None:
        was = self._focused
        self._close_editor(ok)
        self.setFocus()
        if step:
            if self._focused is None:
                self._focused = was
            self.focus_item(step, fields_only=True)

    def _close_editor(self, keep: bool) -> bool:
        editor = self._editor
        if editor is None:
            return True
        if keep:
            QGuiApplication.inputMethod().commit()  # 조합 중인 한글까지 확정
        self._editor = None
        editing = self._editing
        value = None
        if isinstance(editor, FieldEditor):
            field = editor.field
            value = editor.value()
            if isinstance(value, str):
                same = value == str(field.value).replace("\r\n", "\n").replace("\r", "\n")
            else:
                same = sorted(value) == sorted(field.value)
            change = lambda: self.doc.set_field(field, value)
        else:
            pno, rect, size = editing["page"], editing["rect"], editing["size"]
            annot, value = editing["annot"], editor.toPlainText().rstrip()
            same = not value or (annot is not None and value == annot.text)
            if not same:
                target = self._text_area(pno, rect, value, size, keep_height=annot is not None)
                if annot:
                    change = lambda: self.doc.set_annot_text(annot, value, target)
                else:
                    change = lambda: self.doc.add_text(pno, target, value, size, self.rotation)
        editor.hide()
        editor.deleteLater()
        if not keep or same:
            self.viewport().update()
            return True
        ok, _ = self.run_edit(change)
        if not ok and isinstance(value, str):
            QGuiApplication.clipboard().setText(value)  # 입력한 글을 잃지 않게
        return ok

    def _text_area(self, pno: int, rect, text: str, size: float, keep_height: bool) -> tuple:
        """보는 방향의 아래로 늘어난 글상자. 쪽이 화면에 없어도 되도록 쪽 좌표로만 계산함."""
        x0, y0, x1, y1 = rect
        sideways = self.rotation % 180 != 0
        width, old = (y1 - y0, x1 - x0) if sideways else (x1 - x0, y1 - y0)
        tall = self.doc.text_height(text, size, width)
        if keep_height:
            tall = max(tall, old)
        page_w, page_h = self.doc.sizes[pno]
        if sideways:
            tall = min(tall, page_w)
            left = x0 if self.rotation == 90 else x1 - tall
            left = min(max(left, 0.0), page_w - tall)
            return left, y0, left + tall, y1
        tall = min(tall, page_h)
        top = y0 if self.rotation == 0 else y1 - tall
        top = min(max(top, 0.0), page_h - tall)
        return x0, top, x1, top + tall

    def _focus_moved(self, _old, new) -> None:
        editor = self._editor
        if editor is None or new is None:
            return
        if new is editor or editor.isAncestorOf(new):
            return
        if new.window() is not self.window():
            return  # 달력·드롭다운·IME 창
        self._close_editor(True)

    # 링크

    def follow(self, link: Link) -> None:
        if link.kind == "page":
            self.go_to(link.page, link.y, remember=True)
        else:
            self.open_requested.emit(link)

    # 키보드

    def focusNextPrevChild(self, next_: bool) -> bool:
        return False  # Tab 은 문서 안의 필드·주석·링크를 돎

    def _items(self, pno: int, fields_only: bool) -> list:
        fields = [f for f in self.doc.fields(pno) if not f.read_only]
        others = [] if fields_only else [*self.doc.annots(pno), *self.doc.links(pno)]
        ordered = [(item.rect, index, item) for index, item in enumerate([*fields, *others])]
        ordered.sort(key=lambda t: (round(t[0][1] / 6), t[0][0], t[1]))
        return [(pno, item) for _, _, item in ordered]

    def focus_item(self, step: int, fields_only: bool = False) -> None:
        current = self._picked or self._focused
        pno = getattr(current, "pno", None)
        if pno is None:
            pno = self._focused_page if current else self.page
        items = self._items(pno, fields_only)
        position = next((i for i, (_, item) in enumerate(items) if item == current), None)
        if position is None and current is not None:
            xref = getattr(current, "xref", None)
            position = next(
                (i for i, (_, item) in enumerate(items)
                 if xref and getattr(item, "xref", None) == xref),
                None,
            )
        index = (0 if step > 0 else len(items) - 1) if position is None else position + step
        # shortcut: 빈 쪽은 50쪽까지만 건너뜀, 더 드문드문한 양식이 있으면 늘릴 것
        for _ in range(50):
            if 0 <= index < len(items):
                break
            pno += step
            if not 0 <= pno < self.doc.page_count:
                return
            items = self._items(pno, fields_only)
            index = 0 if step > 0 else len(items) - 1
        else:
            return
        pno, item = items[index]
        self._selection = None
        self._focused_page = pno
        if isinstance(item, Annot):
            self._focused = None
            self._set_picked(item)
        else:
            self._set_picked(None)
            self._focused = item
        self.reveal(pno, item.rect)
        self.viewport().update()
        what = getattr(item, "name", "") or getattr(item, "text", "") or getattr(item, "target", "")
        self.message.emit(str(what))
        if fields_only and item.kind not in ("check", "radio", "signature"):
            self.activate(item)

    def _centre_of_view(self) -> tuple[int, float, float]:
        middle = QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        pno, x, y, _ = self.hit(middle)
        w, h = self.doc.sizes[pno]
        return pno, min(max(x, 0), w), min(max(y, 0), h)

    def _enter(self) -> None:
        if self.tool in MARKUPS:
            self.markup(self.tool)
        elif self.tool != "select":
            pno, x, y = self._centre_of_view()
            tool, graphic = self.tool, self._placing
            self.set_tool("select")
            if tool == "note":
                self.add_note(pno, x, y)
            elif tool == "text":
                self.begin_text(pno, x, y)
            elif tool == "sign":
                self.sign_requested.emit(pno, self.default_area(pno, x, y, 3.0))
            elif tool == "place" and graphic:
                self.place_signature(pno, self.default_area(pno, x, y, graphic.aspect), graphic)
        elif self._picked:
            self._finish_nudge()
            self.edit_annot(self._picked)
        elif isinstance(self._focused, Field):
            self.activate(self._focused)
        elif isinstance(self._focused, Link):
            self.follow(self._focused)

    def delete_picked(self) -> None:
        self._nudge.stop()
        annot = self._picked
        if annot is None:
            return
        if annot.locked:
            self.message.emit(T("잠긴 주석입니다.", "This annotation is locked."))
        elif self.allowed("annotate"):
            self._set_picked(None)
            self.run_edit(lambda: self.doc.delete_annot(annot))

    def _nudge_by(self, key, resize: bool) -> None:
        # 화면에서 본 방향 → 쪽 방향
        dx = {Qt.Key.Key_Left: -2, Qt.Key.Key_Right: 2}.get(key, 0)
        dy = {Qt.Key.Key_Up: -2, Qt.Key.Key_Down: 2}.get(key, 0)
        rect, pno = self._picked_rect, self._picked.pno
        if resize:
            if not self._picked.resizable:
                return
            x0, y0, x1, y1 = rect
            w, h = x1 - x0, y1 - y0
            if self._picked.kind == "FreeText":
                w, h = max(w + dx * 2, MIN_SIZE), max(h + dy * 2, MIN_SIZE)
            else:
                factor = 1.06 if dx + dy > 0 else 1 / 1.06
                if min(w, h) * factor < MIN_SIZE and factor < 1:
                    return
                w, h = w * factor, h * factor
            page_w, page_h = self.doc.sizes[pno]
            if x0 + w <= page_w and y0 + h <= page_h:
                self._picked_rect = (x0, y0, x0 + w, y0 + h)
        else:
            turn = {0: (dx, dy), 90: (dy, -dx), 180: (-dx, -dy), 270: (-dy, dx)}[self.rotation]
            self._picked_rect = self._moved(rect, pno, *turn)
        self._nudge.start()
        self.viewport().update()

    def _finish_nudge(self) -> None:
        if not self._nudge.isActive() and (self._press or not self._picked):
            return
        self._nudge.stop()
        if self._picked and self._picked_rect and self._picked_rect != self._picked.rect:
            annot, rect = self._picked, self._picked_rect
            self.run_edit(lambda: self.doc.move_annot(annot, rect))

    def escape(self) -> None:
        self._press = self._rubber = None
        self._autoscroll.stop()
        if self._picked:
            self._nudge.stop()
        if self.tool != "select":
            self.set_tool("select")
        self._selection = self._focused = None
        self._set_picked(None)
        self.viewport().update()

    def keyPressEvent(self, event) -> None:
        key, modifiers = event.key(), event.modifiers()
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        plain = not modifiers & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        )
        arrows = (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down)
        if key == Qt.Key.Key_Escape:
            self.escape()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._enter()
        elif key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self._finish_nudge()
            self.focus_item(-1 if shift or key == Qt.Key.Key_Backtab else 1)
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._picked:
            self.delete_picked()
        elif key == Qt.Key.Key_Space and isinstance(self._focused, Field):
            self.activate(self._focused)
        elif plain and key in arrows and self._picked and self._picked.movable:
            if self.allowed("annotate"):
                self._nudge_by(key, shift)
        elif plain and key in arrows and shift:
            self._extend_selection(key)
        elif key == Qt.Key.Key_Home:
            self.go_to(0, remember=True)
        elif key == Qt.Key.Key_End:
            self.go_to(self.doc.page_count - 1, remember=True)
        elif key == Qt.Key.Key_PageDown or (key == Qt.Key.Key_Space and not shift):
            self.next_page()
        elif key == Qt.Key.Key_PageUp or (key == Qt.Key.Key_Space and shift):
            self.previous_page()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.commit()
        if event.reason() == event.Reason.Mouse:
            where = self.hit(QPointF(event.pos()))
            if where and where[3]:
                pno, x, y, _ = where
                annot = self._annot_at(pno, x, y) or self._mark_at(pno, x, y)
                if annot:
                    self._selection = None
                    self._set_picked(annot)
                    self.viewport().update()
        menu = QMenu(self)
        editable = self.doc.allows("annotate")
        if self._picked:
            menu.addAction(T("편집·메모", "Edit / note"), lambda: self.edit_annot(self._picked))
            action = menu.addAction(T("삭제", "Delete"), self.delete_picked)
            action.setEnabled(editable and not self._picked.locked)
        elif self.has_selection:
            menu.addAction(T("복사", "Copy"), self.copy).setEnabled(self.doc.allows("copy"))
            menu.addSeparator()
            for label, kind in (
                (T("형광펜", "Highlight"), "Highlight"),
                (T("밑줄", "Underline"), "Underline"),
                (T("취소선", "Strikeout"), "StrikeOut"),
            ):
                action = menu.addAction(label)
                action.setEnabled(editable)
                action.triggered.connect(lambda _=False, k=kind: self.markup(k))
            action = menu.addAction(T("형광펜 + 메모", "Highlight + note"), self.markup_with_note)
            action.setEnabled(editable)
        else:
            menu.addAction(T("이 쪽 글자 모두 선택", "Select all text on page"), self.select_page)
        menu.exec(event.globalPos())

    # 덧그리기

    def paint_overlay(self, painter: QPainter) -> None:
        # spans() 는 사이에 낀 모든 쪽의 글자를 읽으므로 그릴 때는 보이는 쪽만 계산
        first, last = sorted(self._selection) if self.has_selection else ((1, 0), (0, 0))
        for slot in self.visible_slots():
            pno = slot.pno
            for field in self.doc.fields(pno):
                if field.read_only:
                    continue
                box = self.to_view(pno, field.rect)
                if field.kind == "signature":
                    if not field.value:
                        painter.setPen(QPen(ACCENT, 1, Qt.PenStyle.DashLine))
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawRect(box)
                        if not any(
                            a.kind in ("Stamp", "Ink") and contains(
                                field.rect, (a.rect[0] + a.rect[2]) / 2, (a.rect[1] + a.rect[3]) / 2
                            )
                            for a in self.doc.annots(pno)
                        ):
                            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, T("서명", "Sign"))
                else:
                    painter.fillRect(box, FILLABLE)
            if pno in self.hits:
                page = self.doc.text(pno)
                for a, b in self.hits[pno]:
                    color = FOUND_NOW if self.hit_now == (pno, a, b) else FOUND
                    for rect in page.rects(a, b):
                        painter.fillRect(self.to_view(pno, rect), color)
            if first[0] <= pno <= last[0]:
                page = self.doc.text(pno)
                a = first[1] if pno == first[0] else 0
                b = last[1] if pno == last[0] else len(page.text)
                for rect in page.rects(a, b):
                    painter.fillRect(self.to_view(pno, rect), SELECTION)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._focused is not None:
            pno = getattr(self._focused, "pno", self._focused_page)
            box = self.to_view(pno, self._focused.rect)
            if box is not None:
                painter.setPen(QPen(ACCENT, 2))
                painter.drawRect(box)
        if self._picked is not None:
            box = self.to_view(self._picked.pno, self._picked_rect)
            if box is not None:
                painter.setPen(QPen(ACCENT, 1, Qt.PenStyle.DashLine))
                painter.drawRect(box)
                if self._picked.resizable:
                    for corner in (box.topLeft(), box.topRight(), box.bottomRight(), box.bottomLeft()):
                        square = QRectF(corner.x() - 4, corner.y() - 4, 8, 8)
                        painter.fillRect(square, ACCENT)
        if self._rubber is not None:
            painter.setPen(QPen(ACCENT, 1, Qt.PenStyle.DashLine))
            painter.fillRect(self._rubber, FILLABLE)
            painter.drawRect(self._rubber)
