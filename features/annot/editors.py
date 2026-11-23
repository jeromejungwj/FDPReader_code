"""타자기·메모 입력."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout

from app.i18n import T


class TextEditor(QPlainTextEdit):
    """페이지 위 타자기. Esc 취소 · Ctrl+Enter 또는 바깥 클릭 확정 · Enter 줄바꿈."""

    done = Signal(bool)  # True = 확정

    def __init__(self, parent, text: str = ""):
        super().__init__(parent)
        self.setAccessibleName(T("텍스트 상자", "Text box"))
        self.setPlainText(text)
        self.setTabChangesFocus(True)
        self.document().setDocumentMargin(2)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QPlainTextEdit{background:#fffde8;color:#000;border:1px dashed #2f6fde}")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.done.emit(False)
        elif (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.done.emit(True)
        else:
            super().keyPressEvent(event)


def ask_note(parent, text: str = "", read_only: bool = False) -> str | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(T("메모", "Note"))
    edit = QPlainTextEdit(text)
    edit.setAccessibleName(T("메모 내용", "Note text"))
    edit.setReadOnly(read_only)
    edit.setTabChangesFocus(True)
    standard = QDialogButtonBox.StandardButton
    wanted = standard.Close if read_only else standard.Ok | standard.Cancel
    buttons = QDialogButtonBox(wanted)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout = QVBoxLayout(dialog)
    layout.addWidget(edit)
    layout.addWidget(buttons)
    dialog.resize(380, 240)
    edit.setFocus()
    if dialog.exec() != QDialog.DialogCode.Accepted or read_only:
        return None
    return edit.toPlainText()
