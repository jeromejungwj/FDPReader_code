"""서명 입력 창. 트랙패드 면 전체 = 안내 틀 (절대 좌표)."""

from __future__ import annotations

import logging
import math
import time
from ctypes import wintypes

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QGuiApplication, QImage, QPainter, QPen, QPixmap, QTabletEvent,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.i18n import T

from . import cursor_guard, touchpad_input
from .contacts import FingerTracker
from .stroke_processor import COLORS, WIDTHS, StrokeBuilder, stroke_segments

log = logging.getLogger(__name__)

IDLE_SECONDS = 30.0
SETTLE_SECONDS = 0.35  # 창이 뜨는 순간 이미 닿아 있던 손가락(영역을 드래그하던 손)은 무시
MOUSE_ASPECT = 1.5


class SignCanvas(QWidget):
    changed = Signal()

    def __init__(self, aspect: float, backdrop: QImage, region_aspect: float, parent=None):
        super().__init__(parent)
        self.setAccessibleName(T("서명 입력 칸", "Signature pad"))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.setMinimumSize(360, 240)
        self.aspect = aspect
        self.region_aspect = region_aspect
        self.backdrop = QPixmap.fromImage(backdrop)
        self.thickness = WIDTHS[1]
        self.color = COLORS[0]
        self.strokes: list[list[tuple]] = []
        self.by_hand = False  # 마우스·펜으로 그리는 중
        self.paused = False
        self.pause_text = ""
        self._stroke: list[tuple] | None = None
        self._builder: StrokeBuilder | None = None
        self._ink = QPixmap()

    def pad(self) -> QRectF:
        room = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        w = min(room.width(), room.height() * self.aspect)
        h = w / self.aspect
        return QRectF(room.center().x() - w / 2, room.center().y() - h / 2, w, h)

    def guide(self) -> QRectF:
        pad = self.pad()
        w = min(pad.width(), pad.height() * self.region_aspect)
        h = w / self.region_aspect
        return QRectF(pad.center().x() - w / 2, pad.center().y() - h / 2, w, h)

    # 획

    def begin(self, x: float, y: float, t: float, *pressure) -> None:
        self.end()
        self._stroke = [(x, y, t, *pressure)]
        self._builder = StrokeBuilder(self.thickness)
        self._builder.add(x * self.aspect, y, t, *pressure)

    def extend(self, x: float, y: float, t: float, *pressure) -> None:
        if self._stroke is not None:
            self._stroke.append((x, y, t, *pressure))
            self._paint_segments(self._builder.add(x * self.aspect, y, t, *pressure))

    def end(self) -> None:
        if self._stroke is None:
            return
        self._paint_segments(self._builder.finish())
        self.strokes.append(self._stroke)
        self._stroke = self._builder = None
        self.changed.emit()

    def cancel(self) -> None:
        if self._stroke is not None:
            self._stroke = self._builder = None
            self.redraw()

    def undo(self) -> None:
        if self._stroke is not None:
            self.cancel()
        elif self.strokes:
            self.strokes.pop()
            self.redraw()
        self.changed.emit()

    def clear(self) -> None:
        self._stroke = self._builder = None
        self.strokes.clear()
        self.redraw()
        self.changed.emit()

    # 그리기: 입력마다 새 선분 주변만 다시 그림

    def _new_layer(self) -> None:
        ratio = self.devicePixelRatioF()
        self._ink = QPixmap(math.ceil(self.width() * ratio), math.ceil(self.height() * ratio))
        self._ink.setDevicePixelRatio(ratio)
        self._ink.fill(Qt.GlobalColor.transparent)

    def redraw(self) -> None:
        self._new_layer()
        strokes = self.strokes + ([self._stroke] if self._stroke else [])
        segments = [s for st in strokes for s in stroke_segments(st, self.aspect, self.thickness)]
        self._paint_segments(segments)
        self.update()

    def _paint_segments(self, segments) -> None:
        if not segments:
            return
        if self._ink.isNull():
            self._new_layer()
        pad = self.pad()
        unit = pad.height()
        painter = QPainter(self._ink)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor.fromRgbF(*self.color))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        dirty = QRectF()
        for x0, y0, x1, y1, width in segments:
            pen.setWidthF(width * unit)
            painter.setPen(pen)
            a = QPointF(pad.x() + x0 * unit, pad.y() + y0 * unit)
            b = QPointF(pad.x() + x1 * unit, pad.y() + y1 * unit)
            if a == b:
                painter.drawPoint(a)
            else:
                painter.drawLine(a, b)
            grow = width * unit + 2
            around = QRectF(a, b).normalized().adjusted(-grow, -grow, grow, grow)
            dirty = around if dirty.isEmpty() else dirty.united(around)
        painter.end()
        self.update(dirty.toAlignedRect())

    def resizeEvent(self, event) -> None:
        self.redraw()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setClipRegion(event.region())
        pad, guide = self.pad(), self.guide()
        painter.fillRect(pad, QColor("white"))
        if not self.backdrop.isNull():
            painter.setOpacity(0.35)
            painter.drawPixmap(guide, self.backdrop, QRectF(self.backdrop.rect()))
            painter.setOpacity(1.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#8a8a8a"), 1, Qt.PenStyle.DashLine))
        painter.drawRect(guide)
        painter.setPen(QPen(QColor("#2f6fde"), 2))
        painter.drawRect(pad)
        if not self._ink.isNull():
            painter.drawPixmap(0, 0, self._ink)
        if self.paused:
            painter.fillRect(pad, QColor(0, 0, 0, 110))
            painter.setPen(QColor("white"))
            font = painter.font()
            font.setPointSize(14)
            painter.setFont(font)
            flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
            painter.drawText(pad, flags, self.pause_text)

    # 마우스·펜·터치스크린

    def _normal(self, position: QPointF) -> tuple[float, float]:
        pad = self.pad()
        x = (position.x() - pad.x()) / pad.width()
        y = (position.y() - pad.y()) / pad.height()
        return min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)

    def mousePressEvent(self, event) -> None:
        if self.by_hand and event.button() == Qt.MouseButton.LeftButton:
            if self.pad().contains(event.position()):
                self.begin(*self._normal(event.position()), time.perf_counter())

    def mouseMoveEvent(self, event) -> None:
        if self.by_hand:
            self.extend(*self._normal(event.position()), time.perf_counter())

    def mouseReleaseEvent(self, event) -> None:
        if self.by_hand:
            self.end()

    def tabletEvent(self, event: QTabletEvent) -> None:
        if not self.by_hand:
            event.ignore()
            return
        event.accept()
        sample = (*self._normal(event.position()), time.perf_counter(), event.pressure())
        if event.type() == QEvent.Type.TabletPress and self.pad().contains(event.position()):
            self.begin(*sample)
        elif event.type() == QEvent.Type.TabletMove:
            self.extend(*sample)
        elif event.type() == QEvent.Type.TabletRelease:
            self.end()


class SignDialog(QDialog):
    def __init__(self, parent, backdrop: QImage, region_aspect: float, state, by_hand=False):
        super().__init__(parent)
        self.setWindowTitle(T("서명", "Sign"))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.signature: dict | None = None
        self._state = state
        self._guard = cursor_guard.CursorGuard()
        self._tracker = FingerTracker()
        self._mode = "idle"  # idle · touch · paused · hand
        self._hidden_cursor = False
        self._since = self._active_at = self._shown_at = 0.0
        self._clears = 0
        self._ignore_contact = False

        devices = []
        if not by_hand:
            try:
                devices = touchpad_input.find_touchpads()
            except OSError:
                log.exception("트랙패드 검색 실패")
        self._pad_found = bool(devices)
        self._input = touchpad_input.TouchpadInput(devices) if devices else None

        aspect = devices[0].aspect if devices else MOUSE_ASPECT
        self.canvas = SignCanvas(aspect, backdrop, max(region_aspect, 0.05), self)
        self._width_index = min(max(state["sign_width"], 0), len(WIDTHS) - 1)
        self._color_index = min(max(state["sign_color"], 0), len(COLORS) - 1)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.gesture_hint = QLabel(
            T(
                "3·4손가락 제스처는 Windows가 처리하므로 사용하지 마세요. "
                "정전식 스타일러스로 쓰면 더 정밀합니다.",
                "Avoid 3- and 4-finger gestures (Windows handles them). "
                "A capacitive stylus is more precise.",
            )
        )
        self.gesture_hint.setWordWrap(True)
        self.gesture_hint.setVisible(self._pad_found)

        self._width_button = self._button(self._cycle_width)
        self._color_button = self._button(self._cycle_color)
        self._undo_button = self._button(self.undo, T("획 취소 (Ctrl+Z)", "Undo stroke (Ctrl+Z)"))
        self._clear_button = self._button(self.clear, T("전체 지우기 (Backspace)", "Clear (Backspace)"))
        self._mode_button = self._button(self.toggle_mode)
        self._mode_button.setVisible(self._pad_found)
        self.keep = QCheckBox(T("이 서명 저장 (S)", "Save this signature (S)"))
        self.keep.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._cancel_button = self._button(self.reject, T("취소 (Esc)", "Cancel (Esc)"))
        self._ok_button = self._button(self.confirm, T("확정 (Enter)", "Done (Enter)"))

        tools = QHBoxLayout()
        for widget in (
            self._width_button, self._color_button, self._undo_button,
            self._clear_button, self._mode_button,
        ):
            tools.addWidget(widget)
        tools.addStretch()
        finish = QHBoxLayout()
        finish.addWidget(self.keep)
        finish.addStretch()
        finish.addWidget(self._cancel_button)
        finish.addWidget(self._ok_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.hint)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.gesture_hint)
        layout.addLayout(tools)
        layout.addLayout(finish)

        screen = (parent.screen() if parent else QGuiApplication.primaryScreen()).availableGeometry()
        self.resize(int(min(screen.width() * 0.8, 1000)), int(min(screen.height() * 0.85, 820)))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._beat = QTimer(self)
        self._beat.timeout.connect(self._tick)
        self.canvas.changed.connect(self._refresh)
        self._apply_style()
        self._refresh()

    def _button(self, slot, text: str = "") -> QPushButton:
        button = QPushButton(text)
        # Space·Enter 는 서명 모드 키라 단추가 가져가지 않게 함 (모든 단추에 단축키가 있음)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAutoDefault(False)
        button.clicked.connect(slot)
        return button

    def _apply_style(self) -> None:
        self.canvas.thickness = WIDTHS[self._width_index]
        self.canvas.color = COLORS[self._color_index]
        widths = (T("가늘게", "Thin"), T("보통", "Medium"), T("굵게", "Thick"))
        colors = (T("검정", "Black"), T("파랑", "Blue"))
        self._width_button.setText(T("굵기", "Width") + f": {widths[self._width_index]} (W)")
        self._color_button.setText(T("색", "Color") + f": {colors[self._color_index]} (C)")
        self.canvas.redraw()

    def _cycle_width(self) -> None:
        self._width_index = (self._width_index + 1) % len(WIDTHS)
        self._apply_style()

    def _cycle_color(self) -> None:
        self._color_index = (self._color_index + 1) % len(COLORS)
        self._apply_style()

    def undo(self) -> None:
        self.canvas.undo()

    def clear(self) -> None:
        if self.canvas.strokes:
            self._clears += 1
        self.canvas.clear()

    def _refresh(self) -> None:
        has_ink = bool(self.canvas.strokes)
        for button in (self._ok_button, self._undo_button, self._clear_button):
            button.setEnabled(has_ink)
        if self._mode in ("touch", "paused", "idle") and self._pad_found:
            text = T(
                "트랙패드 전체가 파란 틀과 1:1로 대응됩니다. "
                "한 손가락으로 쓰고 Enter로 확정하세요. 취소는 Esc입니다.",
                "The whole touchpad maps to the blue frame. "
                "Write with one finger, press Enter when done, Esc to cancel.",
            )
            self._mode_button.setText(T("마우스·펜으로 (M)", "Use mouse/pen (M)"))
        else:
            text = T(
                "파란 틀 안에 마우스·펜·터치로 서명하고 Enter로 확정하세요.",
                "Sign inside the blue frame with mouse, pen or touch, then press Enter.",
            )
            if self._input is None and not self._pad_found:
                text = (
                    T("정밀 터치패드를 사용하지 않는 입력입니다. ", "Not using a Precision Touchpad. ")
                    + text
                )
            self._mode_button.setText(T("트랙패드로 (M)", "Use touchpad (M)"))
        self.hint.setText(text)

    # 모드: 커서를 잠그는 곳은 _start_touch 하나, 푸는 곳은 _release 하나

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.setFocus()
        self._shown_at = time.perf_counter()
        if not self._pad_found:
            self._use_hand()
        else:
            QTimer.singleShot(250, self._start_when_active)

    def _start_when_active(self) -> None:
        if not self.isVisible() or self._mode != "idle":
            return
        if self.isActiveWindow():
            self._start_touch()
        elif time.perf_counter() - self._shown_at < 2.0:
            QTimer.singleShot(100, self._start_when_active)
        else:
            self._pause()

    def _start_touch(self) -> None:
        try:
            hwnd = int(self.winId())
            self._input.start(hwnd)
        except OSError:
            log.exception("트랙패드 서명 모드를 시작하지 못해 마우스 입력으로 전환")
            self._use_hand()
            return
        if not self._guard.lock(cursor_guard.window_center(hwnd)):
            log.warning("커서를 고정하지 못해 일시정지")
            self._pause()
            return
        self._mode = "touch"
        self.canvas.by_hand = self.canvas.paused = False
        self.canvas.update()
        self._tracker.reset()
        self._since = self._active_at = time.perf_counter()
        QApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)
        self._hidden_cursor = True
        self._beat.start(200)
        self._refresh()

    def _release(self) -> None:
        self._beat.stop()
        self._guard.unlock()
        if self._hidden_cursor:
            QApplication.restoreOverrideCursor()
            self._hidden_cursor = False
        if self._input:
            self._input.stop()

    def _pause(self) -> None:
        self._release()
        self.canvas.end()
        self._mode = "paused"
        self.canvas.by_hand = False
        self.canvas.paused = True
        self.canvas.pause_text = T(
            "커서 고정이 풀렸습니다\nSpace: 이어서 쓰기 · M: 마우스로 쓰기 · Enter: 확정",
            "Cursor released\nSpace: continue · M: use mouse · Enter: done",
        )
        self.canvas.update()

    def _use_hand(self) -> None:
        self._release()
        self._mode = "hand"
        self.canvas.by_hand = True
        self.canvas.paused = False
        self.canvas.update()
        self._refresh()

    def toggle_mode(self) -> None:
        if self._mode != "hand":
            self.canvas.end()
            self._use_hand()
        elif self._input:
            self._start_touch()

    def _tick(self) -> None:
        if self._mode != "touch":
            return
        if time.perf_counter() - self._active_at > IDLE_SECONDS or not self._guard.beat():
            self._pause()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            if self._mode == "touch":
                self._pause()

    def nativeEvent(self, event_type, message):
        # PySide6 는 튜플 반환을 요구함. WM_INPUT 은 DefWindowProc 까지 가야 하므로 항상 False
        if self._mode == "touch":
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == touchpad_input.WM_INPUT:
                    for frame in self._input.read(msg.lParam):
                        self.handle_frame(frame, time.perf_counter())
            except Exception:
                log.exception("트랙패드 입력 처리 실패")
                self._pause()
        return False, 0

    def handle_frame(self, frame, now: float) -> None:
        self._active_at = now
        for event in self._tracker.feed(frame, now):
            kind, *values = event
            if kind == "down":
                self._ignore_contact = now - self._since < SETTLE_SECONDS
                if not self._ignore_contact:
                    self.canvas.begin(*values)
            elif self._ignore_contact:
                continue
            elif kind == "move":
                self.canvas.extend(*values)
            elif kind == "up":
                self.canvas.end()
            else:
                self.canvas.cancel()

    # 키·종료

    def keyPressEvent(self, event) -> None:
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        self._active_at = time.perf_counter()
        if key == Qt.Key.Key_Escape:
            self.reject()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.confirm()
        elif key == Qt.Key.Key_Z and ctrl:
            self.undo()
        elif key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.clear()
        elif key == Qt.Key.Key_Space and self._mode == "paused":
            self._start_touch()
        # 한글 입력 상태에서도 되도록 글자가 아니라 물리 키(VK)로 판정
        elif event.nativeVirtualKey() == ord("W"):
            self._cycle_width()
        elif event.nativeVirtualKey() == ord("C"):
            self._cycle_color()
        elif event.nativeVirtualKey() == ord("S"):
            self.keep.toggle()
        elif event.nativeVirtualKey() == ord("M") and self._pad_found:
            self.toggle_mode()

    def confirm(self) -> None:
        self.canvas.end()
        if not self.canvas.strokes:
            return
        self.signature = {
            "kind": "ink",
            "aspect": self.canvas.aspect,
            "width": WIDTHS[self._width_index],
            "color": list(COLORS[self._color_index]),
            "strokes": [[list(point) for point in s] for s in self.canvas.strokes],
        }
        self._state["sign_width"] = self._width_index
        self._state["sign_color"] = self._color_index
        seconds = time.perf_counter() - self._shown_at
        log.info("서명 확정: %.1f초, 전체 지우기 %d회", seconds, self._clears)
        self.accept()

    def done(self, result: int) -> None:
        self._mode = "idle"
        self._release()
        self._guard.close()
        super().done(result)

    def hideEvent(self, event) -> None:
        if self._mode == "touch":
            self._pause()
        super().hideEvent(event)
