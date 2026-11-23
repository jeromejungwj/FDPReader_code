"""탭 하나 = 문서 하나: 옆 패널 + 문서 보기."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QTabWidget

from core.document.document import Document

from .i18n import T
from .interaction import EditView
from .panels import Outline, Search, Thumbnails


class DocTab(QSplitter):
    def __init__(self, document: Document, service, state):
        super().__init__(Qt.Orientation.Horizontal)
        self.doc = document
        self.host = None  # 지금 이 탭을 가진 창. 탭을 다른 창으로 옮기면 바뀜
        self._service = service

        self.view = EditView(document, service, state)
        self.thumbs = Thumbnails(self.view)
        self.outline = Outline(self.view)
        self.search = Search(self.view)
        self.side = QTabWidget()
        self.side.setDocumentMode(True)
        self.side.addTab(self.thumbs, T("썸네일", "Pages"))
        self.side.addTab(self.outline, T("목차", "Outline"))
        self.side.addTab(self.search, T("검색", "Search"))
        self.addWidget(self.side)
        self.addWidget(self.view)
        self.setStretchFactor(1, 1)
        self.setCollapsible(1, False)
        self.setSizes([230, 900])
        self.side.setVisible(not self.outline.empty)
        if not self.outline.empty:
            self.side.setCurrentWidget(self.outline)

        view = self.view
        view.page_changed.connect(lambda _: self._tell("sync_position"))
        view.zoom_changed.connect(lambda: self._tell("sync_position"))
        view.history_changed.connect(lambda: self._tell("sync_actions"))
        view.tool_changed.connect(lambda: self._tell("sync_actions"))
        view.selection_changed.connect(lambda: self._tell("sync_actions"))
        view.edited.connect(self._edited)
        view.message.connect(lambda text: self.host and self.host.show_message(text))
        view.sign_requested.connect(lambda p, r: self.host and self.host.begin_signature(self, p, r))
        view.open_requested.connect(lambda link: self.host and self.host.open_link(self, link))

    def _tell(self, method: str) -> None:
        if self.host is not None and self.host.current() is self:
            getattr(self.host, method)()

    def _edited(self) -> None:
        self.thumbs.pages.changed()
        if self.host is not None:
            self.host.document_changed(self)

    def history_step(self, redo: bool) -> None:
        self.view.commit()
        step = self.view.run_edit(self.doc.redo if redo else self.doc.undo)[1]
        if step and step.relayout:
            self.view.page_geometry_changed()
            self.search.start()

    def find(self) -> None:
        self.side.show()
        self.side.setCurrentWidget(self.search)
        self.search.query.setFocus()
        self.search.query.selectAll()

    def toggle_panel(self) -> None:
        if self.side.isVisible():
            self.side.hide()
            self.view.setFocus()
        else:
            self.side.show()
            self.side.currentWidget().setFocus()

    def dispose(self) -> None:
        self.search.stop()
        self.host = None
        self.hide()
        self._service.forget(self.view, self.doc.render_source()[0])
        self.view._request_timer.stop()
        self.setParent(None)
        self.doc.close()
        self.deleteLater()
