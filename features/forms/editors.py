"""양식 필드 위에 뜨는 입력기."""

from __future__ import annotations

from PySide6.QtCore import QDate, QEvent, QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QCalendarWidget, QComboBox, QHBoxLayout, QLineEdit, QListWidget, QMenu, QPlainTextEdit,
    QToolButton, QWidget, QWidgetAction,
)

from app.i18n import T
from core.document.models import Field


def qt_date_format(acrobat: str) -> str:
    """Acrobat(m=월, M=분) → Qt(M=월, m=분)."""
    return acrobat.translate(str.maketrans("mM", "Mm"))


# 종이는 OS 다크 모드여도 흰색이므로 입력칸도 흰 바탕
PAPER_STYLE = (
    "QLineEdit, QPlainTextEdit, QListWidget, QComboBox, QComboBox QAbstractItemView"
    "{background: #ffffff; color: #000000; border: 1px solid #2f6fde;"
    " selection-background-color: #2f6fde; selection-color: #ffffff}"
)


class FieldEditor(QWidget):
    done = Signal(bool, int)  # (확정 여부, Tab 이동 방향: -1 · 0 · 1)

    def __init__(self, parent, field: Field, pixel_size: int):
        super().__init__(parent)
        self.field = field
        self.setAutoFillBackground(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if field.kind == "combo":
            self.input = QComboBox()
            self.input.setEditable(field.editable)
            for value, label in field.options:
                self.input.addItem(label, value)
            index = next((i for i, o in enumerate(field.options) if o[0] == field.value), -1)
            self.input.setCurrentIndex(index)
            if field.editable and index < 0:
                self.input.setEditText(str(field.value))
            self.input.activated.connect(lambda _: self.done.emit(True, 0))
        elif field.kind == "list":
            self.input = QListWidget()
            if field.multi:
                self.input.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
            for value, label in field.options:
                self.input.addItem(label)
                self.input.item(self.input.count() - 1).setSelected(value in field.value)
        elif field.multiline:
            self.input = QPlainTextEdit(str(field.value).replace("\r\n", "\n").replace("\r", "\n"))
            self.input.setTabChangesFocus(True)
        else:
            self.input = QLineEdit(str(field.value))
            if field.max_len:
                self.input.setMaxLength(field.max_len)
            if field.password:
                self.input.setEchoMode(QLineEdit.EchoMode.Password)
            self.input.selectAll()

        self.input.setAccessibleName(field.name or T("양식 필드", "Form field"))
        font = self.input.font()
        font.setPixelSize(pixel_size)
        self.input.setFont(font)
        self.input.setStyleSheet(PAPER_STYLE)
        self.input.installEventFilter(self)
        layout.addWidget(self.input, 1)
        self.setFocusProxy(self.input)

        if field.date_format:
            button = QToolButton()
            button.setText(T("날짜", "Date"))
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(button)
            calendar = QCalendarWidget(menu)
            action = QWidgetAction(menu)
            action.setDefaultWidget(calendar)
            menu.addAction(action)
            button.setMenu(menu)
            layout.addWidget(button)

            def picked(date: QDate) -> None:
                # 월 이름 서식(mmm)은 다른 리더가 읽을 수 있게 영어로 씀
                text = QLocale.c().toString(date, qt_date_format(field.date_format))
                self.input.setText(text)
                menu.close()
                self.input.setFocus()

            calendar.clicked.connect(picked)
            calendar.activated.connect(picked)

    def value(self):
        field = self.field
        if field.kind == "combo":
            index = self.input.currentIndex()
            if field.editable:
                typed = self.input.currentText()
                return next((v for v, label in field.options if label == typed), typed)
            return field.options[index][0] if index >= 0 else field.value
        if field.kind == "list":
            return [v for i, (v, _) in enumerate(field.options) if self.input.item(i).isSelected()]
        return self.input.toPlainText() if field.multiline else self.input.text()

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            key, modifiers = event.key(), event.modifiers()
            if key == Qt.Key.Key_Escape:
                self.done.emit(False, 0)
                return True
            if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                back = key == Qt.Key.Key_Backtab or modifiers & Qt.KeyboardModifier.ShiftModifier
                self.done.emit(True, -1 if back else 1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if not self.field.multiline or modifiers & Qt.KeyboardModifier.ControlModifier:
                    self.done.emit(True, 0)
                    return True
        return super().eventFilter(watched, event)
