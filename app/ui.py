"""작은 UI 도우미: 아이콘, 안내 창, 서명 그리기."""

from __future__ import annotations

import html

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPalette, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import QApplication, QMessageBox

from core.document.models import DocumentError, Graphic

from .i18n import T

Button = QMessageBox.StandardButton


def icon(code: int) -> QIcon:
    """Windows 기본 아이콘 글꼴. 글자색을 따라가 다크·고대비에서도 보임."""
    result = QIcon()
    font = QFont("Segoe MDL2 Assets")  # Windows 10·11 모두에 있음
    # 없으면 첫 글자에서 대체 글꼴을 훑느라 시작이 0.5초 늦어짐
    font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
    font.setPixelSize(32)
    palette = QApplication.palette()
    for mode, group in (
        (QIcon.Mode.Normal, QPalette.ColorGroup.Active),
        (QIcon.Mode.Disabled, QPalette.ColorGroup.Disabled),
    ):
        pixmap = QPixmap(40, 40)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setFont(font)
        painter.setPen(palette.color(group, QPalette.ColorRole.WindowText))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, chr(code))
        painter.end()
        result.addPixmap(pixmap, mode)
    return result


def swatch(color: str) -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


def plain_tooltip(text: str) -> str:
    """PDF 에서 온 글은 HTML 로 해석되지 않게 함 (UNC 그림 경로로 자격 증명이 새는 것 방지)."""
    return f"<qt>{html.escape(text).replace(chr(10), '<br>')}</qt>" if text else ""


def _box(parent, kind, title, text, buttons, default=None) -> Button:
    box = QMessageBox(kind, title, text, buttons, parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    if default is not None:
        box.setDefaultButton(default)
    return Button(box.exec())


def inform(parent, text: str) -> None:
    _box(parent, QMessageBox.Icon.Information, "FDP Reader", text, Button.Ok)


def warn(parent, text: str) -> None:
    _box(parent, QMessageBox.Icon.Warning, "FDP Reader", text, Button.Ok)


def confirm(parent, text: str, default_yes: bool = False) -> bool:
    default = Button.Yes if default_yes else Button.No
    answer = _box(
        parent, QMessageBox.Icon.Question, "FDP Reader", text, Button.Yes | Button.No, default
    )
    return answer == Button.Yes


def choose(parent, text: str, buttons, default) -> Button:
    return _box(parent, QMessageBox.Icon.Question, "FDP Reader", text, buttons, default)


def error_text(error: DocumentError) -> str:
    messages = {
        "not_pdf": T("PDF 파일이 아닙니다.", "This is not a PDF file."),
        "damaged": T(
            "문서가 손상되어 열 수 없습니다.", "The document is damaged and cannot be opened."
        ),
        "permission": T(
            "이 문서의 보안 설정이 해당 작업을 허용하지 않습니다.",
            "This document's security settings do not allow that.",
        ),
        "read_only": T(
            "읽기 전용이라 편집할 수 없습니다.", "This is read-only and cannot be edited."
        ),
        "write": T("작업을 완료하지 못했습니다.", "The operation could not be completed."),
    }
    text = messages.get(error.code, str(error))
    return f"{text}\n\n{error.detail}" if error.detail else text


def paint_graphic(painter: QPainter, g: Graphic, target: QRectF) -> None:
    x0, y0, x1, y1 = g.bounds
    sx, sy = target.width() / max(x1 - x0, 1e-6), target.height() / max(y1 - y0, 1e-6)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if g.kind == "image":
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(target, QImage.fromData(g.image))
    else:
        def at(x, y) -> QPointF:
            return QPointF(target.x() + (x - x0) * sx, target.y() + (y - y0) * sy)

        color = QColor.fromRgbF(*g.color)
        if g.kind == "fill":
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill)
            for contour in g.contours:
                path.addPolygon(QPolygonF([at(*p) for p in contour]))
                path.closeSubpath()
            painter.fillPath(path, color)
        else:
            pen = QPen(color)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            for ax, ay, bx, by, width in g.segments:
                pen.setWidthF(max(width * (sx + sy) / 2, 0.01))
                painter.setPen(pen)
                a, b = at(ax, ay), at(bx, by)
                if a == b:
                    painter.drawPoint(a)
                else:
                    painter.drawLine(a, b)
    painter.restore()
