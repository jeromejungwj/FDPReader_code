"""대체 입력: 서명 이미지(배경 자동 제거), 타이핑 서명."""

from __future__ import annotations

import base64
from statistics import median

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QFont, QImage, QPainterPath
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
)

from app.i18n import T

from .stroke_processor import COLORS

MAX_SIDE = 900


def from_image(image: QImage) -> dict | None:
    """종이처럼 밝은 바탕을 투명하게 하고 여백을 자름. 남는 게 없으면 None."""
    if image.isNull():
        return None
    if max(image.width(), image.height()) > MAX_SIDE:
        image = image.scaled(
            MAX_SIDE, MAX_SIDE, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h, stride = image.width(), image.height(), image.bytesPerLine()
    px = bytearray(image.constBits())

    def light(x: int, y: int) -> int:
        at = y * stride + x * 4
        return (px[at] * 299 + px[at + 1] * 587 + px[at + 2] * 114) // 1000

    edge = [(x, y) for x in range(w) for y in (0, h - 1)]
    edge += [(x, y) for y in range(h) for x in (0, w - 1)]
    has_alpha = median(px[y * stride + x * 4 + 3] for x, y in edge) < 128
    # shortcut: 바탕 밝기를 한 값으로 봄. 그림자가 심한 사진이 문제되면 구역별 임곗값으로 바꿀 것
    paper = median(light(x, y) for x, y in edge)

    left, top, right, bottom = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            at = y * stride + x * 4 + 3
            if not has_alpha:
                px[at] = min(max((paper - light(x, y) - 25) * 5, 0), 255)
            if px[at] > 40:
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
    if right < 0:
        return None
    cut = QImage(bytes(px), w, h, stride, QImage.Format.Format_RGBA8888).copy(
        left, top, right - left + 1, bottom - top + 1
    )
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    cut.save(buffer, "PNG")
    return {
        "kind": "image",
        "size": [cut.width(), cut.height()],
        "png": base64.b64encode(bytes(buffer.data())).decode("ascii"),
    }


def from_text(text: str, family: str, color) -> dict | None:
    if not text.strip():
        return None
    font = QFont()
    font.setFamilies([family, "Malgun Gothic"])
    font.setPixelSize(200)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    path = QPainterPath()
    path.addText(0, 0, font, text.strip())
    contours = [
        [[round(p.x(), 2), round(p.y(), 2)] for p in polygon.toList()]
        for polygon in path.toSubpathPolygons()
    ]
    contours = [c for c in contours if len(c) > 2]
    if not contours:
        return None
    return {"kind": "outline", "color": list(color), "contours": contours}


class TypedSignatureDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(T("타이핑 서명", "Typed signature"))
        self.text = QLineEdit()
        self.text.setMaxLength(60)
        self.text.setMinimumWidth(320)
        self.family = QComboBox()
        for family, label in (
            ("Segoe Script", T("필기체", "Script")),
            ("Gungsuh", T("궁서", "Gungsuh")),
            ("Malgun Gothic", T("고딕", "Gothic")),
        ):
            self.family.addItem(label, family)
        self.color = QComboBox()
        self.color.addItems([T("검정", "Black"), T("파랑", "Blue")])
        self.keep = QCheckBox(T("이 서명 저장", "Save this signature"))
        self.keep.setChecked(True)  # 손 서명 창과 같은 기본값
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow(T("서명할 글자", "Text"), self.text)
        form.addRow(T("글꼴", "Font"), self.family)
        form.addRow(T("색", "Color"), self.color)
        form.addRow(self.keep)
        form.addRow(buttons)
        self.text.textChanged.connect(self._preview)
        self.family.currentIndexChanged.connect(self._preview)

    def _preview(self) -> None:
        font = QFont()
        font.setFamilies([self.family.currentData(), "Malgun Gothic"])
        font.setPointSize(16)
        self.text.setFont(font)

    def signature(self) -> dict | None:
        color = COLORS[self.color.currentIndex()]
        return from_text(self.text.text(), self.family.currentData(), color)
