"""인쇄: 범위·배율·양면·주석 포함 여부."""

from __future__ import annotations

import logging

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPageLayout, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QProgressDialog,
    QSpinBox,
)

from core.document.models import DocumentError

from . import ui
from .i18n import T

log = logging.getLogger(__name__)

MAX_DPI = 300
LOW_DPI = 150  # 고화질 인쇄가 금지된 문서


def parse_pages(text: str, count: int) -> list[int]:
    """'1-3, 5, 8-' → [0, 1, 2, 4, 7 …]. 잘못되면 ValueError."""
    if not text.strip():
        return list(range(count))
    pages = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        first, dash, last = part.partition("-")
        a = int(first) if first.strip() else 1
        b = (int(last) if last.strip() else count) if dash else a
        if not 1 <= a <= b <= count:
            raise ValueError(part)
        pages += range(a - 1, b)
    if not pages:
        raise ValueError(text)
    return pages


class PrintDialog(QDialog):
    def __init__(self, parent, doc, page: int):
        super().__init__(parent)
        self.setWindowTitle(T("인쇄", "Print"))
        self._count, self._page = doc.page_count, page
        self.pages: list[int] = []

        self.printer = QComboBox()
        self.printer.addItems(QPrinterInfo.availablePrinterNames())
        default = QPrinterInfo.defaultPrinter().printerName()
        if default:
            self.printer.setCurrentText(default)
        self.which = QComboBox()
        self.which.addItems(
            [T("전체", "All"), T("현재 쪽", "Current page"), T("범위 지정", "Pages")]
        )
        self.range = QLineEdit()
        self.range.setPlaceholderText("1-3, 5, 8-")
        self.range.setEnabled(False)
        self.which.currentIndexChanged.connect(lambda i: self.range.setEnabled(i == 2))
        self.sizing = QComboBox()
        self.sizing.addItems(
            [T("용지에 맞춤", "Fit to paper"), T("실제 크기", "Actual size"), T("배율 지정", "Custom")]
        )
        self.percent = QSpinBox()
        self.percent.setRange(10, 400)
        self.percent.setValue(100)
        self.percent.setSuffix(" %")
        self.percent.setEnabled(False)
        self.sizing.currentIndexChanged.connect(lambda i: self.percent.setEnabled(i == 2))
        self.sides = QComboBox()
        self.sides.addItem(T("프린터 설정 따름", "Printer default"), QPrinter.DuplexMode.DuplexAuto)
        self.sides.addItem(T("단면", "One-sided"), QPrinter.DuplexMode.DuplexNone)
        self.sides.addItem(
            T("양면 (긴 변)", "Two-sided, long edge"), QPrinter.DuplexMode.DuplexLongSide
        )
        self.sides.addItem(
            T("양면 (짧은 변)", "Two-sided, short edge"), QPrinter.DuplexMode.DuplexShortSide
        )
        self.copies = QSpinBox()
        self.copies.setRange(1, 99)
        self.annots = QCheckBox(T("주석·서명 포함", "Include annotations and signatures"))
        self.annots.setChecked(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText(T("인쇄", "Print"))
        ok.setEnabled(self.printer.count() > 0)
        buttons.accepted.connect(self._check)
        buttons.rejected.connect(self.reject)

        form = QFormLayout(self)
        form.addRow(T("프린터", "Printer"), self.printer)
        form.addRow(T("쪽", "Pages"), self.which)
        form.addRow(T("범위", "Range"), self.range)
        form.addRow(T("크기", "Size"), self.sizing)
        form.addRow(T("배율", "Scale"), self.percent)
        form.addRow(T("면", "Sides"), self.sides)
        form.addRow(T("매수", "Copies"), self.copies)
        form.addRow(self.annots)
        form.addRow(buttons)

    def _check(self) -> None:
        choice = self.which.currentIndex()
        try:
            if choice == 1:
                self.pages = [self._page]
            elif choice == 2:
                if not self.range.text().strip():
                    raise ValueError
                self.pages = parse_pages(self.range.text(), self._count)
            else:
                self.pages = list(range(self._count))
        except ValueError:
            ui.warn(self, T("쪽 범위가 올바르지 않습니다.", "The page range is not valid."))
            return
        self.accept()

    @property
    def factor(self) -> float | None:
        """None = 용지에 맞춤."""
        index = self.sizing.currentIndex()
        return (None, 1.0, self.percent.value() / 100)[index]


def print_pages(
    printer: QPrinter, doc, pages: list[int], factor: float | None, annots: bool, progress=None
) -> bool:
    """취소되면 False."""
    source = doc.printer(annots)
    painter = QPainter()
    try:
        printer.setFullPage(True)
        limit = MAX_DPI if doc.allows("print_hq") else LOW_DPI
        for number, pno in enumerate(pages):
            if progress is not None:
                progress.setValue(number)
                if progress.wasCanceled():
                    printer.abort()
                    return False
            w, h = doc.sizes[pno]
            printer.setPageOrientation(
                QPageLayout.Orientation.Landscape if w > h else QPageLayout.Orientation.Portrait
            )
            if number == 0:
                if not painter.begin(printer):
                    raise DocumentError("write", "printer did not start")
            elif not printer.newPage():
                raise DocumentError("write", "printer refused a new page")

            unit = printer.resolution() / 72  # 1pt = 프린터 점 몇 개
            paper = printer.paperRect(QPrinter.Unit.DevicePixel)
            paper_w, paper_h = paper.width(), paper.height()
            if factor is None:
                margins = printer.pageLayout().marginsPoints()
                side = max(margins.left(), margins.right())
                edge = max(margins.top(), margins.bottom())
                scale = min((paper_w - 2 * side * unit) / w, (paper_h - 2 * edge * unit) / h)
            else:
                scale = factor * unit
            target = QRectF(
                (paper_w - w * scale) / 2, (paper_h - h * scale) / 2, w * scale, h * scale
            )
            render_at = min(scale, limit / 72, 9000 / max(w, h))
            _, _, pw, ph, stride, samples = source.render(pno, render_at)
            image = QImage(samples, pw, ph, stride, QImage.Format.Format_RGB888).copy()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(target, image)
        return True
    finally:
        if painter.isActive():
            painter.end()
        source.close()


def run_dialog(parent, doc, page: int) -> None:
    if not doc.allows("print"):
        ui.warn(parent, ui.error_text(DocumentError("permission")))
        return
    dialog = PrintDialog(parent, doc, page)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    info = QPrinterInfo.printerInfo(dialog.printer.currentText())
    printer = QPrinter(info, QPrinter.PrinterMode.HighResolution)
    printer.setDocName(doc.path.name)
    printer.setCopyCount(dialog.copies.value())
    printer.setDuplex(dialog.sides.currentData())
    progress = QProgressDialog(
        T("인쇄 중…", "Printing…"), T("취소", "Cancel"), 0, len(dialog.pages), parent
    )
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(400)
    try:
        print_pages(printer, doc, dialog.pages, dialog.factor, dialog.annots.isChecked(), progress)
    except Exception as error:
        log.exception("인쇄 실패")
        ui.warn(parent, T("인쇄하지 못했습니다.", "Printing failed.") + f"\n\n{error}")
    finally:
        progress.close()
