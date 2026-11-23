"""문서 보기: 배치, 확대, 이동, 타일 렌더. 편집·선택은 interaction.EditView 가 얹음."""

from __future__ import annotations

import logging
import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAccessible, QColor, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QAbstractScrollArea, QFrame

from core.document.document import Document
from core.render.service import Job, RenderService

from . import layout
from .i18n import T
from .tile_cache import Tile, TileCache

log = logging.getLogger(__name__)

PT_TO_PX = 96 / 72
MIN_ZOOM, MAX_ZOOM = 0.08, 16.0  # 1.0 = 실제 크기
TILE = 900
PREVIEW_SIDE = 260
PAPER = {"light": "#ffffff", "dark": "#1e1e1e", "sepia": "#f4ecd8", "gray": "#c4c4c4"}
BACKDROP = {"light": "#9a9da3", "dark": "#101012", "sepia": "#8f8778", "gray": "#6e6e6e"}


class PageView(QAbstractScrollArea):
    page_changed = Signal(int)
    zoom_changed = Signal()
    preview_ready = Signal(int)
    history_changed = Signal()

    def __init__(self, document: Document, service: RenderService, theme: str, parent=None):
        super().__init__(parent)
        self.doc = document
        self.service = service
        self.theme = theme
        self.mode = "continuous"
        self.fit = "width"  # width · page · "" (고정 배율)
        self.zoom = 1.0
        self.rotation = 0  # 보기 회전
        self.page = 0

        self._layout: layout.Layout | None = None
        self._restore: dict | None = None
        self._tiles = TileCache(120 * 1024 * 1024)
        self._previews = TileCache(32 * 1024 * 1024)
        self._thumbs_wanted: dict[int, None] = {}
        self._fallback_scale = 0  # 확대 직후 새 타일이 오기 전까지 보여 줄 배율
        self._moving = False
        self._resized = False
        self._wheel_turn = 0
        self._back: list[dict] = []
        self._forward: list[dict] = []
        self._request_timer = QTimer(self, singleShot=True, interval=0)
        self._request_timer.timeout.connect(self._request)

        self.setFrameShape(QFrame.Shape.NoFrame)
        # 폭 맞춤 ↔ 스크롤바 표시가 서로를 바꾸며 떨리지 않게 항상 표시
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalScrollBar().setSingleStep(24)
        self.horizontalScrollBar().setSingleStep(24)
        self.viewport().setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAccessibleName(T("문서", "Document"))

    # 좌표: 쪽 좌표(pt) ↔ 뷰포트(px)

    @property
    def scale(self) -> float:
        return self.zoom * PT_TO_PX

    def shown_sizes(self) -> list[tuple[float, float]]:
        if self.rotation % 180:
            return [(h, w) for w, h in self.doc.sizes]
        return self.doc.sizes

    def _snap(self, value: float, offset: int) -> float:
        # 장치 픽셀 경계에 맞춰야 타일이 흐려지지 않음
        ratio = self.devicePixelRatioF()
        return round((value + offset) * ratio) / ratio - offset

    def transform_of(self, pno: int) -> QTransform | None:
        slot = self._layout.slot(pno) if self._layout else None
        if slot is None:
            return None
        origin = self.viewport().mapTo(self.window(), self.viewport().rect().topLeft())
        x = self._snap(slot.x - self.horizontalScrollBar().value(), origin.x())
        y = self._snap(slot.y - self.verticalScrollBar().value(), origin.y())
        w, h = self.doc.sizes[pno]
        z = self.scale
        if self.rotation == 90:
            return QTransform(0, z, -z, 0, x + h * z, y)
        if self.rotation == 180:
            return QTransform(-z, 0, 0, -z, x + w * z, y + h * z)
        if self.rotation == 270:
            return QTransform(0, -z, z, 0, x, y + w * z)
        return QTransform(z, 0, 0, z, x, y)

    def to_view(self, pno: int, rect) -> QRectF | None:
        transform = self.transform_of(pno)
        if transform is None:
            return None
        x0, y0, x1, y1 = rect
        return transform.mapRect(QRectF(QPointF(x0, y0), QPointF(x1, y1)))

    def to_page_rect(self, pno: int, rect: QRectF) -> tuple:
        mapped = self.transform_of(pno).inverted()[0].mapRect(rect)
        w, h = self.doc.sizes[pno]
        return (
            max(mapped.left(), 0.0), max(mapped.top(), 0.0),
            min(mapped.right(), w), min(mapped.bottom(), h),
        )

    def hit(self, position: QPointF) -> tuple[int, float, float, bool] | None:
        """(쪽, x, y, 쪽 안쪽인지). 바깥이면 가장 가까운 쪽 기준."""
        if self._layout is None:
            return None
        slot = self._layout.nearest(
            position.x() + self.horizontalScrollBar().value(),
            position.y() + self.verticalScrollBar().value(),
        )
        point = self.transform_of(slot.pno).inverted()[0].map(position)
        w, h = self.doc.sizes[slot.pno]
        return slot.pno, point.x(), point.y(), 0 <= point.x() <= w and 0 <= point.y() <= h

    def visible_slots(self) -> list[layout.Slot]:
        if self._layout is None:
            return []
        top = self.verticalScrollBar().value()
        return self._layout.visible(top, top + self.viewport().height())

    # 배치

    def relayout(self, anchor: dict | None = None) -> None:
        size = self.viewport().size()
        if size.width() < 50 or not self.isVisible():
            return
        if anchor is None:
            anchor = self._restore or self.state()
        self._restore = None
        self.page = min(max(int(anchor.get("page", self.page)), 0), self.doc.page_count - 1)
        sizes = self.shown_sizes()
        before = self.scale
        if self.fit:
            wanted = layout.fit_zoom(
                sizes, self.mode, self.page, size.width(), size.height(), self.fit == "page"
            )
            self.zoom = min(max(wanted / PT_TO_PX, MIN_ZOOM), MAX_ZOOM)
        if self._layout and abs(before - self.scale) > 1e-6:
            self._fallback_scale = round(before * self.devicePixelRatioF() * 1000)
        self._layout = layout.Layout(
            sizes, self.mode, self.scale, size.width(), size.height(), self.page
        )
        self._moving = True
        for bar, total, room in (
            (self.horizontalScrollBar(), self._layout.width, size.width()),
            (self.verticalScrollBar(), self._layout.height, size.height()),
        ):
            # 반올림 오차로 스크롤바가 생겨 폭 맞춤이 떨리지 않게 0.5 여유
            bar.setRange(0, max(math.ceil(total - room - 0.5), 0))
            bar.setPageStep(room)
        slot = self._layout.slot(self.page)
        at = anchor.get("at", (0, 0))
        screen = anchor.get("screen", (0, 0))
        if "at" in anchor:
            x = slot.x + at[0] * self.scale - screen[0]
            self.horizontalScrollBar().setValue(round(x))
        else:
            middle = slot.x + slot.w / 2 - size.width() / 2
            self.horizontalScrollBar().setValue(round(middle))
        top = slot.y + at[1] * self.scale - screen[1]
        if "at" not in anchor:
            top -= layout.MARGIN
        self.verticalScrollBar().setValue(round(top))
        self._moving = False
        if self._resized:  # 가로 스크롤바가 생기거나 없어져 뷰포트 크기가 바뀜
            self._resized = False
            self.relayout(anchor)
            return
        self._page_moved()
        self.zoom_changed.emit()
        self.after_move()

    def state(self) -> dict:
        """지금 보는 자리."""
        if self._layout is None:
            return self._restore or {"page": self.page}
        slot = self._layout.slot(self.page)
        if slot is None:
            return {"page": self.page}
        return {
            "page": self.page,
            "at": (
                (self.horizontalScrollBar().value() - slot.x) / self.scale,
                (self.verticalScrollBar().value() - slot.y) / self.scale,
            ),
        }

    def saved_state(self) -> dict:
        return {
            **self.state(),
            "zoom": self.zoom, "fit": self.fit, "mode": self.mode, "rotation": self.rotation,
        }

    def restore_state(self, saved: dict) -> None:
        try:
            if saved.get("mode") in layout.MODES:
                self.mode = saved["mode"]
            if saved.get("fit") in ("width", "page", ""):
                self.fit = saved["fit"]
            if saved.get("rotation") in (0, 90, 180, 270):
                self.rotation = saved["rotation"]
            if "zoom" in saved:
                self.zoom = min(max(float(saved["zoom"]), MIN_ZOOM), MAX_ZOOM)
            page = min(max(int(saved.get("page", 0)), 0), self.doc.page_count - 1)
            anchor = {"page": page}
            at = saved.get("at")
            if at and len(at) == 2:
                anchor["at"] = (float(at[0]), float(at[1]))
        except (TypeError, ValueError):
            log.warning("저장된 보기 상태가 잘못되어 무시함")
            return
        self.page, self._restore = page, anchor
        self.relayout(anchor)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._moving:
            self._resized = True
        else:
            self.relayout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.relayout()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        if self._moving or self._layout is None:
            return
        self._find_page()
        self.after_move()

    def after_move(self) -> None:
        self.viewport().update()
        self.schedule_render()

    def _find_page(self) -> None:
        if self.mode == "single":
            return
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        slots = self.visible_slots()
        if not slots:
            return
        best = max(slots, key=lambda s: round(min(bottom, s.y + s.h) - max(top, s.y)))
        # 두 쪽 보기에서는 같은 줄이면 쪽 번호를 바꾸지 않음
        if self.page not in layout.spread_of(best.pno, self.mode) and best.pno != self.page:
            self.page = best.pno
            self._page_moved()

    def _page_moved(self) -> None:
        self.page_changed.emit(self.page)
        if QAccessible.isActive():  # 화면 낭독기에게 현재 쪽 글을 알려 줌
            self.setAccessibleDescription(self.doc.text(self.page).text[:4000])

    # 이동·확대

    def go_to(self, pno: int, y: float | None = None, remember: bool = False) -> None:
        if remember:
            self._back.append(self.state())
            del self._back[:-100]
            self._forward.clear()
            self.history_changed.emit()
        pno = min(max(pno, 0), self.doc.page_count - 1)
        anchor: dict = {"page": pno}
        if y is not None and not self.rotation:
            anchor.update(at=(0, y), screen=(layout.MARGIN, 24))
        self.page = pno
        if self._layout is None or not self.isVisible():
            self._restore = anchor
        else:
            self.relayout(anchor)

    def reveal(self, pno: int, rect) -> None:
        """rect 가 보이도록 필요한 만큼만 움직임."""
        if self._layout is None:
            self.go_to(pno)
            return
        if self._layout.slot(pno) is None:
            self.go_to(pno)
        box = self.to_view(pno, rect)
        if box is None:
            return
        room = QRectF(self.viewport().rect()).adjusted(10, 10, -10, -10)
        if room.contains(box):
            return
        self._moving = True
        if box.left() < room.left() or box.right() > room.right():
            bar = self.horizontalScrollBar()
            bar.setValue(round(bar.value() + box.center().x() - room.center().x()))
        if box.top() < room.top() or box.bottom() > room.bottom():
            bar = self.verticalScrollBar()
            bar.setValue(round(bar.value() + box.center().y() - room.height() / 3))
        self._moving = False
        self.page = pno
        self._page_moved()
        self.after_move()

    def next_page(self) -> None:
        last = layout.spread_of(self.page, self.mode)[-1]
        if last + 1 < self.doc.page_count:
            self.go_to(last + 1)
        else:
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def previous_page(self) -> None:
        first = layout.spread_of(self.page, self.mode)[0]
        if first > 0:
            self.go_to(layout.spread_of(first - 1, self.mode)[0])
        else:
            self.verticalScrollBar().setValue(0)

    @property
    def can_go_back(self) -> bool:
        return bool(self._back)

    @property
    def can_go_forward(self) -> bool:
        return bool(self._forward)

    def go_back(self) -> None:
        self._travel(self._back, self._forward)

    def go_forward(self) -> None:
        self._travel(self._forward, self._back)

    def _travel(self, source: list, other: list) -> None:
        if source:
            other.append(self.state())
            self.relayout(source.pop())
            self.history_changed.emit()

    def set_zoom(self, zoom: float, around: QPointF | None = None) -> None:
        zoom = min(max(zoom, MIN_ZOOM), MAX_ZOOM)
        anchor = None
        if self._layout is not None:
            point = around or QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
            slot = self._layout.nearest(
                point.x() + self.horizontalScrollBar().value(),
                point.y() + self.verticalScrollBar().value(),
            )
            anchor = {
                "page": slot.pno,
                "at": (
                    (point.x() + self.horizontalScrollBar().value() - slot.x) / self.scale,
                    (point.y() + self.verticalScrollBar().value() - slot.y) / self.scale,
                ),
                "screen": (point.x(), point.y()),
            }
            self._fallback_scale = round(self.scale * self.devicePixelRatioF() * 1000)
        self.fit, self.zoom = "", zoom
        self.relayout(anchor)

    def set_fit(self, fit: str) -> None:
        self.fit = fit
        self.relayout({"page": self.page})

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.relayout({"page": self.page})

    def rotate_view(self, degrees: int) -> None:
        self.rotation = (self.rotation + degrees) % 360
        self.relayout({"page": self.page})

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.after_move()

    def page_geometry_changed(self) -> None:
        self._tiles.clear()
        self._previews.clear()
        self.relayout({"page": self.page})

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            self.after_move()
        return super().event(event)

    def viewportEvent(self, event) -> bool:
        if event.type() == QEvent.Type.NativeGesture:
            if event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
                self.set_zoom(self.zoom * (1 + event.value()), event.position())
                return True
        return super().viewportEvent(event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:  # 트랙패드 핀치도 여기로 옴
            if delta.y():
                self.set_zoom(self.zoom * 1.15 ** (delta.y() / 120), event.position())
            event.accept()
            return
        if self.mode == "single" and abs(delta.y()) > abs(delta.x()):
            bar = self.verticalScrollBar()
            down = delta.y() < 0
            if bar.value() == (bar.maximum() if down else bar.minimum()):
                self._wheel_turn += delta.y()
                if abs(self._wheel_turn) >= 120:
                    self._wheel_turn = 0
                    if down and self.page + 1 < self.doc.page_count:
                        self.go_to(self.page + 1)
                    elif not down and self.page > 0:
                        self.go_to(self.page - 1)
                        bar.setValue(bar.maximum())
                event.accept()
                return
        super().wheelEvent(event)

    # 렌더 요청

    def schedule_render(self) -> None:
        if not self._request_timer.isActive():
            self._request_timer.start()

    def _scale_key(self) -> int:
        return round(self.scale * self.devicePixelRatioF() * 1000)

    def _preview_scale(self, pno: int) -> float:
        return PREVIEW_SIDE / max(self.doc.sizes[pno])

    def _tile_range(self, slot, key: int):
        """그 쪽에서 보이는 타일 번호들."""
        s = key / 1000
        transform = self.transform_of(slot.pno)
        seen = transform.inverted()[0].mapRect(QRectF(self.viewport().rect()))
        w, h = self.doc.sizes[slot.pno]
        x0, x1 = max(seen.left(), 0.0) * s, min(seen.right(), w) * s
        y0, y1 = max(seen.top(), 0.0) * s, min(seen.bottom(), h) * s
        if x1 <= x0 or y1 <= y0:
            return []
        return [
            (tx, ty)
            for ty in range(int(y0 // TILE), math.ceil(y1 / TILE))
            for tx in range(int(x0 // TILE), math.ceil(x1 / TILE))
        ]

    def _request(self) -> None:
        if self._layout is None:
            return
        source = self.doc.render_source()
        running = self.service.running(self)
        theme, gens = self.theme, self.doc.page_gen
        sharp, rough, thumbs, ahead = [], [], [], []

        def need(cache, key, pno, scale, clip, into) -> None:
            tile = cache.get(key)
            if (tile is None or tile.gen != gens[pno]) and (key, gens[pno]) not in running:
                into.append(Job(key, source, gens[pno], pno, scale, clip, theme, self._arrived))

        def need_preview(pno, into) -> None:
            need(self._previews, ("preview", pno, theme), pno, self._preview_scale(pno), None, into)

        if self.isVisible():
            key = self._scale_key()
            s = key / 1000
            slots = sorted(self.visible_slots(), key=lambda slot: slot.pno != self.page)
            for slot in slots:
                w, h = self.doc.sizes[slot.pno]
                preview = self._previews.get(("preview", slot.pno, theme))
                for tx, ty in self._tile_range(slot, key):
                    clip = (
                        tx * TILE / s, ty * TILE / s,
                        min((tx + 1) * TILE / s, w), min((ty + 1) * TILE / s, h),
                    )
                    tile_key = ("tile", slot.pno, key, theme, tx, ty)
                    need(self._tiles, tile_key, slot.pno, s, clip, sharp)
                if preview is None:
                    need_preview(slot.pno, rough)
                else:
                    need_preview(slot.pno, ahead)
            if slots:
                for pno in (max(s.pno for s in slots) + 1, min(s.pno for s in slots) - 1):
                    if 0 <= pno < self.doc.page_count:
                        need_preview(pno, ahead)
            for pno in reversed(list(self._thumbs_wanted)):
                need_preview(pno, thumbs)
        self.service.want(self, rough + sharp + thumbs + ahead)

    def _arrived(self, job: Job, result) -> None:
        stale_failure = result is None and job.source[2] != self.doc.version
        if job.gen != self.doc.page_gen[job.pno] or stale_failure:
            self.schedule_render()
            return
        pixmap, x, y = None, 0, 0
        if result is not None:
            x, y, image = result
            pixmap = QPixmap.fromImage(image)
        cache = self._previews if job.key[0] == "preview" else self._tiles
        cache.put(job.key, Tile(job.gen, x, y, job.scale, pixmap))
        if job.key[0] == "preview":
            self._thumbs_wanted.pop(job.pno, None)
            self.preview_ready.emit(job.pno)
        self._update_area(job.pno, job.clip if pixmap else None)

    def _update_area(self, pno: int, clip: tuple | None) -> None:
        """도착한 타일 자리만 다시 그림. 화면 전체를 그리면 타일마다 5~10ms 가 듦."""
        box = self.to_view(pno, clip or (0, 0, *self.doc.sizes[pno]))
        if box is None:
            return
        area = box.adjusted(-2, -2, 2, 2).toAlignedRect() & self.viewport().rect()
        if not area.isEmpty():
            self.viewport().update(area)

    def thumbnail(self, pno: int) -> QPixmap | None:
        tile = self._previews.get(("preview", pno, self.theme))
        if tile is None or tile.gen != self.doc.page_gen[pno]:
            self._thumbs_wanted.pop(pno, None)
            self._thumbs_wanted[pno] = None
            while len(self._thumbs_wanted) > 24:
                del self._thumbs_wanted[next(iter(self._thumbs_wanted))]
            self.schedule_render()
        return tile.pixmap if tile else None

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.service.want(self, [])
        self._tiles.clear()  # 뒤에 있는 탭은 메모리를 쓰지 않음

    # 그리기

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        painter.fillRect(event.rect(), QColor(BACKDROP[self.theme]))
        if self._layout is None:
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        key = self._scale_key()
        changed = QRectF(event.rect())
        painter.setClipRect(changed)
        for slot in self.visible_slots():
            w, h = self.doc.sizes[slot.pno]
            if self.to_view(slot.pno, (0, 0, w, h)).intersects(changed):
                self._paint_page(painter, slot, key, changed)
        painter.resetTransform()
        self.paint_overlay(painter)

    def _paint_page(self, painter: QPainter, slot, key: int, changed: QRectF) -> None:
        pno = slot.pno
        w, h = self.doc.sizes[pno]
        page = QRectF(0, 0, w, h)
        painter.save()
        painter.setTransform(self.transform_of(pno))
        painter.fillRect(page, QColor(PAPER[self.theme]))
        painter.setClipRect(page, Qt.ClipOperation.IntersectClip)
        dirty = painter.transform().inverted()[0].mapRect(changed)

        def draw(tile: Tile | None) -> bool:
            if tile is None or tile.pixmap is None:
                return False
            s, pixmap = tile.scale, tile.pixmap
            target = QRectF(tile.x / s, tile.y / s, pixmap.width() / s, pixmap.height() / s)
            if target.intersects(dirty):
                painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
            return True

        wanted = self._tile_range(slot, key)
        tiles = [self._tiles.get(("tile", pno, key, self.theme, *at)) for at in wanted]
        failed = False
        s = key / 1000
        uncovered = any(
            (tile is None or tile.pixmap is None)
            and QRectF(tx * TILE / s, ty * TILE / s, TILE / s, TILE / s).intersects(dirty)
            for (tx, ty), tile in zip(wanted, tiles)
        )
        if uncovered:
            # 선명한 타일이 올 때까지 저해상도 미리보기
            preview = self._previews.get(("preview", pno, self.theme))
            draw(preview)
            failed = any(t is not None and t.pixmap is None for t in [preview, *tiles])
            old = self._fallback_scale
            if old and old != key:
                for at in self._tile_range(slot, old):
                    draw(self._tiles.get(("tile", pno, old, self.theme, *at)))
        for tile in tiles:
            draw(tile)
        painter.restore()
        if failed:
            x0 = slot.x - self.horizontalScrollBar().value()
            y0 = slot.y - self.verticalScrollBar().value()
            painter.setPen(QColor("#c0392b"))
            painter.drawText(
                QRectF(x0, y0, slot.w, slot.h),
                Qt.AlignmentFlag.AlignCenter,
                T("이 쪽은 표시할 수 없습니다", "This page cannot be displayed"),
            )

    def paint_overlay(self, painter: QPainter) -> None:
        pass
