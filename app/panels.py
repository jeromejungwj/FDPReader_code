"""옆 패널: 썸네일, 목차, 검색."""

from __future__ import annotations

import time

from PySide6.QtCore import QAbstractListModel, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.document.text import compile_query

from .i18n import T
from .interaction import EditView

THUMB = QSize(150, 180)


class _Pages(QAbstractListModel):
    def __init__(self, view: EditView, parent=None):
        super().__init__(parent)
        self.view = view
        self._blank = QPixmap(THUMB)
        self._blank.fill(QColor(128, 128, 128, 40))
        view.preview_ready.connect(self._ready)

    def rowCount(self, parent=None) -> int:
        return 0 if parent and parent.isValid() else self.view.doc.page_count

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        pno = index.row()
        if role == Qt.ItemDataRole.DisplayRole:
            return str(pno + 1)
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return T(f"{pno + 1}쪽", f"Page {pno + 1}")
        if role == Qt.ItemDataRole.DecorationRole:
            pixmap = self.view.thumbnail(pno)
            if pixmap is None:
                return self._blank
            return pixmap.scaled(
                THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        return None

    def _ready(self, pno: int) -> None:
        index = self.index(pno)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])

    def changed(self) -> None:
        last = self.index(self.view.doc.page_count - 1)
        self.dataChanged.emit(self.index(0), last, [Qt.ItemDataRole.DecorationRole])


class Thumbnails(QListView):
    def __init__(self, view: EditView):
        super().__init__()
        self.setAccessibleName(T("쪽 썸네일", "Page thumbnails"))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setIconSize(THUMB)
        self.setGridSize(QSize(THUMB.width() + 20, THUMB.height() + 34))
        self.pages = _Pages(view, self)
        self.setModel(self.pages)
        self._view = view
        self.clicked.connect(self._go)
        self.activated.connect(self._go)
        view.page_changed.connect(self._follow)

    def _go(self, index) -> None:
        if index.row() != self._view.page:
            self._view.go_to(index.row(), remember=True)

    def _follow(self, pno: int) -> None:
        index = self.pages.index(pno)
        self.setCurrentIndex(index)
        if self.isVisible():
            self.scrollTo(index)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.scrollTo(self.pages.index(self._view.page))


class Outline(QTreeWidget):
    def __init__(self, view: EditView):
        super().__init__()
        self.setAccessibleName(T("목차", "Outline"))
        self.setHeaderHidden(True)
        self._view = view
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for entry in view.doc.toc():
            while stack and stack[-1][0] >= entry.level:
                stack.pop()
            item = QTreeWidgetItem(stack[-1][1] if stack else self, [entry.title])
            item.setData(0, Qt.ItemDataRole.UserRole, (entry.page, entry.y))
            stack.append((entry.level, item))
        self.empty = self.topLevelItemCount() == 0
        if self.empty:
            item = QTreeWidgetItem(self, [T("이 문서에는 목차가 없습니다", "No outline")])
            item.setDisabled(True)
        elif self.topLevelItemCount() < 4:
            self.expandToDepth(0)
        self.itemClicked.connect(self._go)
        self.itemActivated.connect(self._go)

    def _go(self, item, _column) -> None:
        target = item.data(0, Qt.ItemDataRole.UserRole)
        if not target:
            return
        pno, y = target
        if 0 <= pno < self._view.doc.page_count:
            at = self._view.state()
            self._view.go_to(pno, y, remember=at.get("page") != pno or y is not None)


class Search(QWidget):
    LIMIT = 2000
    SLICE = 0.012  # 한 번에 이만큼만 일하고 화면에 양보 (초)

    def __init__(self, view: EditView):
        super().__init__()
        self._view = view
        self._found: list[tuple[int, int, int]] = []
        self._pattern = None
        self._next_page = self._origin = 0
        self._current = -1

        self.query = QLineEdit()
        self.query.setPlaceholderText(T("문서에서 찾기", "Find in document"))
        self.query.setAccessibleName(T("검색어", "Search text"))
        self.query.setClearButtonEnabled(True)
        self.case = QCheckBox(T("대소문자 구분", "Match case"))
        self.word = QCheckBox(T("단어 단위", "Whole words"))
        self.count = QLabel()
        previous = QPushButton(T("이전", "Previous"))
        following = QPushButton(T("다음", "Next"))
        previous.clicked.connect(lambda: self.step(-1))
        following.clicked.connect(lambda: self.step(1))
        self.results = QListWidget()
        self.results.setAccessibleName(T("검색 결과", "Search results"))
        self.results.setWordWrap(True)
        self.results.itemClicked.connect(lambda item: self._show(self.results.row(item)))
        self.results.itemActivated.connect(lambda item: self._show(self.results.row(item)))

        options = QHBoxLayout()
        options.addWidget(self.case)
        options.addWidget(self.word)
        options.addStretch()
        moves = QHBoxLayout()
        moves.addWidget(self.count, 1)
        moves.addWidget(previous)
        moves.addWidget(following)
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 6, 6, 6)
        box.addWidget(self.query)
        box.addLayout(options)
        box.addLayout(moves)
        box.addWidget(self.results, 1)

        self._debounce = QTimer(self, singleShot=True, interval=250)
        self._debounce.timeout.connect(self.start)
        self._worker = QTimer(self, interval=0)
        self._worker.timeout.connect(self._work)
        self.query.textChanged.connect(lambda _: self._debounce.start())
        self.case.toggled.connect(lambda _: self.start())
        self.word.toggled.connect(lambda _: self.start())
        self.query.returnPressed.connect(self._enter)

    def _enter(self) -> None:
        if self._debounce.isActive():
            self._debounce.stop()
            self.start()
        else:
            self.step(1)

    def start(self) -> None:
        self._worker.stop()
        self._found = []
        self.results.clear()
        self._current = -1
        self._view.hits, self._view.hit_now = {}, None
        self._view.viewport().update()
        self.count.setText("")
        self._pattern = compile_query(
            self.query.text(), self.case.isChecked(), self.word.isChecked()
        )
        if self._pattern:
            self._next_page, self._origin = 0, self._view.page
            self._worker.start()

    def stop(self) -> None:
        self._debounce.stop()
        self._worker.stop()

    def _work(self) -> None:
        doc = self._view.doc
        until = time.perf_counter() + self.SLICE
        while self._next_page < doc.page_count and len(self._found) < self.LIMIT:
            pno = self._next_page
            self._next_page += 1
            page = doc.text(pno)
            for a, b in page.find(self._pattern):
                self._found.append((pno, a, b))
                self._view.hits.setdefault(pno, []).append((a, b))
                label = T(f"{pno + 1}쪽", f"p. {pno + 1}")
                self.results.addItem(QListWidgetItem(f"{label}  {page.snippet(a, b)}"))
                if self._current < 0 and pno >= self._origin:
                    self._show(len(self._found) - 1)
                if len(self._found) >= self.LIMIT:
                    break
            if time.perf_counter() > until:
                self._set_count(searching=True)
                self._view.viewport().update()
                return
        self._worker.stop()
        if self._current < 0 and self._found:
            self._show(0)
        self._set_count()
        self._view.viewport().update()

    def _set_count(self, searching: bool = False) -> None:
        total = len(self._found)
        if searching:
            self.count.setText(T(f"찾는 중… {total}건", f"Searching… {total}"))
        elif total:
            more = "+" if total >= self.LIMIT else ""
            self.count.setText(f"{max(self._current, 0) + 1} / {total}{more}")
        elif self._pattern:
            self.count.setText(T("결과 없음", "No results"))

    def step(self, by: int) -> None:
        if self._found:
            self._show((self._current + by) % len(self._found))

    def _show(self, index: int) -> None:
        if not 0 <= index < len(self._found):
            return
        self._current = index
        pno, a, b = self._found[index]
        rects = self._view.doc.text(pno).rects(a, b)
        self._view.hit_now = (pno, a, b)
        if rects:
            self._view.reveal(pno, rects[0])
        self._view.viewport().update()
        self.results.setCurrentRow(index)
        self._set_count(self._worker.isActive())
