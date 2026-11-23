"""문서가 없을 때의 첫 화면: 열기 + 최근 문서(고정)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from .i18n import T


class StartPage(QWidget):
    open_file = Signal(str)
    browse = Signal()

    def __init__(self, state):
        super().__init__()
        self._state = state
        title = QLabel("FDP Reader")
        font = title.font()
        font.setPointSize(22)
        title.setFont(font)
        hint = QLabel(
            T("PDF를 이 창에 끌어다 놓거나 열기를 누르세요.", "Drop a PDF here or choose Open.")
        )
        button = QPushButton(T("PDF 열기", "Open PDF"))
        button.clicked.connect(self.browse)
        self.recent = QListWidget()
        self.recent.setAccessibleName(T("최근 문서", "Recent documents"))
        self.recent.itemActivated.connect(self._open)
        self.pin = QPushButton(T("고정 / 해제", "Pin / unpin"))
        self.pin.setEnabled(False)
        self.pin.clicked.connect(self._toggle_pin)
        self.recent.currentRowChanged.connect(lambda row: self.pin.setEnabled(row >= 0))

        top = QHBoxLayout()
        top.addWidget(button)
        top.addWidget(hint, 1)
        bar = QHBoxLayout()
        bar.addWidget(QLabel(T("최근 문서", "Recent documents")))
        bar.addStretch()
        bar.addWidget(self.pin)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addLayout(top)
        layout.addLayout(bar)
        layout.addWidget(self.recent, 1)
        self.refresh()

    def refresh(self) -> None:
        self.recent.clear()
        for entry in self._state.recent():
            path = Path(entry["path"])
            pinned = T("[고정] ", "[Pinned] ") if entry.get("pinned") else ""
            item = QListWidgetItem(f"{pinned}{path.name}\n{path.parent}")
            item.setData(Qt.ItemDataRole.UserRole, entry["path"])
            self.recent.addItem(item)
        self.pin.setEnabled(self.recent.currentRow() >= 0)

    def _open(self, item) -> None:
        self.open_file.emit(item.data(Qt.ItemDataRole.UserRole))

    def _toggle_pin(self) -> None:
        item = self.recent.currentItem()
        if item:
            self._state.toggle_pin(item.data(Qt.ItemDataRole.UserRole))
            self._state.save()
            self.refresh()
