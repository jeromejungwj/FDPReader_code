"""서명 흐름: 영역 → 입력 → 배치, 저장 서명, 대체 입력."""

from __future__ import annotations

import logging

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImageReader, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

from core.render.service import to_image
from features.sign import alt_input
from features.sign.sign_canvas import SignDialog
from features.sign.signature_store import SignatureStore
from features.sign.stroke_processor import to_graphic

from . import ui
from .i18n import T

log = logging.getLogger(__name__)

MENU_ICON = QSize(120, 40)


def icon_of(graphic, size: QSize = MENU_ICON) -> QIcon:
    pixmap = QPixmap(size * 2)
    pixmap.fill(Qt.GlobalColor.white)
    room = QRectF(pixmap.rect()).adjusted(6, 6, -6, -6)
    w = min(room.width(), room.height() * graphic.aspect)
    h = w / graphic.aspect
    painter = QPainter(pixmap)
    ui.paint_graphic(
        painter, graphic, QRectF(room.center().x() - w / 2, room.center().y() - h / 2, w, h)
    )
    painter.end()
    return QIcon(pixmap)


def show_notice(parent, state) -> None:
    """법적 효력 고지는 최초 1회."""
    if state["notice_shown"]:
        return
    ui.inform(
        parent,
        T(
            "이 기능은 이미지형 전자 서명이며, 인증서 기반 디지털 서명이 아닙니다.\n"
            "서명의 인정 여부는 문서를 받는 곳의 요건에 따르며, "
            "FDP Reader는 법적 효력을 보증하지 않습니다.",
            "This creates an image-type electronic signature, "
            "not a certificate-based digital signature.\n"
            "Acceptance depends on the recipient's requirements, "
            "and FDP Reader does not guarantee legal effect.",
        ),
    )
    state["notice_shown"] = True
    state.save()


def warn_signed(parent, doc) -> bool:
    if not doc.has_digital_signature:
        return True
    return ui.confirm(
        parent,
        T(
            "이 문서에는 디지털 서명이 있습니다. 내용을 추가하면 다른 리더에서 "
            "'서명 후 변경됨'으로 표시될 수 있습니다. 계속할까요?",
            "This document is digitally signed. Adding to it may show as "
            "'changed after signing' in other readers. Continue?",
        ),
    )


def keep(parent, signature: dict) -> None:
    try:
        SignatureStore().add(signature)
    except OSError as error:
        log.exception("서명 저장 실패")
        ui.warn(
            parent,
            T("서명을 저장하지 못했습니다.", "The signature could not be saved.") + f"\n\n{error}",
        )


def draw_signature(parent, tab, pno: int, rect, state) -> None:
    if not warn_signed(parent, tab.doc):
        return
    show_notice(parent, state)
    x0, y0, x1, y1 = rect
    w, h = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    try:
        image = to_image(tab.doc.render(pno, min(4.0, 700 / max(w, h)), rect))[2]
    except Exception:
        log.exception("서명 배경을 그리지 못함")
        image = QPixmap().toImage()
    turn = tab.view.rotation
    if turn:
        image = image.transformed(QTransform().rotate(turn))
        if turn % 180:
            w, h = h, w
    dialog = SignDialog(parent, image, w / h, state)
    try:
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        signature, wants_keep = dialog.signature, dialog.keep.isChecked()
    finally:
        dialog.done(dialog.result())  # 예외가 나도 커서 고정을 풀고 끝냄
        dialog.deleteLater()
    if not accepted or not signature:
        tab.view.setFocus()
        return
    if tab.view.place_signature(pno, rect, to_graphic(signature)) and wants_keep:
        keep(parent, signature)


def use_saved(parent, tab, signature: dict, state) -> None:
    if not warn_signed(parent, tab.doc):
        return
    show_notice(parent, state)
    tab.view.set_tool("place", to_graphic(signature))


def from_image_file(parent, tab, state) -> None:
    path, _ = QFileDialog.getOpenFileName(
        parent,
        T("서명 이미지", "Signature image"),
        "",
        T("이미지", "Images") + " (*.png *.jpg *.jpeg *.bmp)",
    )
    if not path:
        return
    reader = QImageReader(path)
    reader.setAutoTransform(True)  # 휴대폰 사진의 EXIF 방향
    signature = alt_input.from_image(reader.read())
    if not signature:
        ui.warn(parent, T("이미지에서 서명을 찾지 못했습니다.", "No signature found in that image."))
        return
    if ui.confirm(parent, T("이 서명을 저장할까요?", "Save this signature?")):
        keep(parent, signature)
    use_saved(parent, tab, signature, state)


def from_typing(parent, tab, state) -> None:
    dialog = alt_input.TypedSignatureDialog(parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    signature = dialog.signature()
    if signature:
        if dialog.keep.isChecked():
            keep(parent, signature)
        use_saved(parent, tab, signature, state)


class ManageDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(T("저장된 서명", "Saved signatures"))
        self._store = SignatureStore()
        self.items = QListWidget()
        self.items.setIconSize(MENU_ICON * 1.5)
        self.items.setAccessibleName(T("저장된 서명", "Saved signatures"))
        delete = QPushButton(T("삭제", "Delete"))
        delete.setAutoDefault(False)
        delete.clicked.connect(self._delete)
        close = QPushButton(T("닫기", "Close"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(delete)
        row.addStretch()
        row.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.items)
        layout.addLayout(row)
        self.resize(360, 340)
        self._reload()

    def _reload(self) -> None:
        self.items.clear()
        for number, (name, signature) in enumerate(self._store.all(), 1):
            item = QListWidgetItem(
                icon_of(to_graphic(signature)), T(f"서명 {number}", f"Signature {number}")
            )
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.items.addItem(item)

    def _delete(self) -> None:
        item = self.items.currentItem()
        question = T(
            "이 서명을 삭제할까요? 되돌릴 수 없습니다.",
            "Delete this signature? This cannot be undone.",
        )
        if item and ui.confirm(self, question):
            try:
                self._store.delete(item.data(Qt.ItemDataRole.UserRole))
            except OSError as error:
                ui.warn(self, str(error))
            self._reload()
