"""앱 전체: 창들, 문서 열기, 세션."""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QInputDialog, QLineEdit

from core.document.document import Document, sweep_stale_copies
from core.document.models import DocumentError, PasswordRequired
from storage.state import State, key_of

from . import ui
from .doc_tab import DocTab
from .i18n import T
from .main_window import MainWindow

log = logging.getLogger(__name__)


class Controller(QObject):
    def __init__(self, state: State, service):
        super().__init__()
        self.state, self.service = state, service
        self.windows: list[MainWindow] = []
        self._quitting: list[str] | None = None
        self._active = 0
        self._still_to_restore: list[str] = []

    def start(self, paths: list[str]) -> MainWindow:
        window = self.new_window()
        session = self.state["session"]
        saved = [p for p in session.get("files", []) if isinstance(p, str) and os.path.isfile(p)]
        active = session.get("active", 0)
        if paths:
            first, later = paths, saved
        elif saved:
            index = active if isinstance(active, int) and 0 <= active < len(saved) else 0
            first, later = [saved[index]], saved[:index] + saved[index + 1 :]
        else:
            first, later = [], []
        self._still_to_restore = list(later)
        window.show()
        for path in first:
            self.open(window, path)
        # 앞 탭부터 보여 준 뒤 나머지 세션 탭과 정리 작업을 이어서 함
        QTimer.singleShot(150, lambda: self._restore(window, saved))
        QTimer.singleShot(1500, sweep_stale_copies)
        return window

    def _restore(self, window: MainWindow, order: list[str]) -> None:
        if window not in self.windows:
            return
        showing = window.current()
        while self._still_to_restore:
            self.open(window, self._still_to_restore.pop(0))
        bar = window.tabs.tabBar()
        position = 0
        for path in order:
            for index, tab in enumerate(window.all_tabs()):
                if key_of(tab.doc.path) == key_of(path):
                    bar.moveTab(index, position)
                    position += 1
                    break
        if showing is not None and showing in window.all_tabs():
            window.tabs.setCurrentWidget(showing)

    def new_window(self) -> MainWindow:
        window = MainWindow(self)
        self.windows.append(window)
        return window

    def find_tab(self, path) -> DocTab | None:
        wanted = key_of(path)
        for window in self.windows:
            for tab in window.all_tabs():
                if key_of(tab.doc.path) == wanted:
                    return tab
        return None

    def open(self, window: MainWindow, path: str) -> DocTab | None:
        path = os.path.abspath(path)
        existing = self.find_tab(path)
        if existing is not None:
            existing.host.tabs.setCurrentWidget(existing)
            existing.host.raise_()
            existing.host.activateWindow()
            return existing
        doc = self._load(window, path)
        if doc is None:
            return None
        tab = DocTab(doc, self.service, self.state)
        tab.view.restore_state(self.state.position(path))
        window.add_tab(tab)
        self.state.add_recent(path)
        self.state.save()
        if doc.has_xfa:
            ui.inform(
                window,
                T("XFA 양식(구형 Adobe 전용)은 지원하지 않습니다. 일부 칸이 보이거나 입력되지 않을 수 있습니다.",
                  "XFA forms (legacy Adobe) are not supported. Some fields may not show or work."),
            )
        if doc.rebuilt:
            window.show_message(
                T("손상된 문서를 복구해서 열었습니다. 원본은 저장하기 전까지 그대로입니다.",
                  "Opened a repaired copy. The original is untouched until you save.")
            )
        elif not doc.writable:
            window.show_message(T("보기 전용으로 열었습니다.", "Opened read-only."))
        return tab

    def _load(self, window, path: str) -> Document | None:
        name, password = os.path.basename(path), ""
        while True:
            try:
                return Document(path, password)
            except PasswordRequired as needed:
                again = T("암호가 맞지 않습니다.\n", "Wrong password.\n") if needed.wrong else ""
                prompt = T("문서 암호", "Document password")
                password, ok = QInputDialog.getText(
                    window, name, f"{again}{prompt}:", QLineEdit.EchoMode.Password
                )
                if not ok or not password:
                    return None
            except DocumentError as error:
                ui.warn(window, f"{name}\n\n{ui.error_text(error)}")
                return None
            except OSError as error:
                log.warning("파일을 읽지 못함: %s", error)
                problem = T("파일을 열 수 없습니다.", "The file cannot be opened.")
                ui.warn(window, f"{name}\n\n{problem}\n{error.strerror or error}")
                return None
            except Exception as error:
                log.exception("문서 열기 실패")
                ui.warn(window, f"{name}\n\n{ui.error_text(DocumentError('damaged', str(error)))}")
                return None

    def move_tab(self, tab: DocTab, source: MainWindow, position) -> None:
        """position 이 다른 창 위면 그 창으로, 아니면 새 창으로."""
        target = None
        if position is not None:
            target = next(
                (w for w in self.windows if w is not source and w.frameGeometry().contains(position)),
                None,
            )
            if target is None and source.tabs.count() < 2:
                return
        if target is None:
            target = self.new_window()
            target.showNormal()
            target.resize(source.normalGeometry().size())
            if position is not None:
                target.move(position.x() - 60, position.y() - 20)
            else:
                target.move(source.x() + 40, source.y() + 40)
        place = tab.view.saved_state()
        source.release_tab(tab)
        target.add_tab(tab)
        tab.view.restore_state(place)
        target.raise_()
        target.activateWindow()
        if not source.tabs.count():
            source.close()

    def set_theme(self, theme: str) -> None:
        self.state["theme"] = theme
        for window in self.windows:
            for tab in window.all_tabs():
                tab.view.set_theme(theme)
                tab.thumbs.pages.changed()
            window.sync_actions()
        self.state.save()

    def forget(self, tab: DocTab) -> None:
        self.state.set_position(tab.doc.path, tab.view.saved_state())
        self.state.save()

    def window_closing(self, window: MainWindow) -> None:
        tabs = window.all_tabs()
        for tab in tabs:
            self.state.set_position(tab.doc.path, tab.view.saved_state())
        if self._quitting is not None:
            session, active = self._quitting, self._active
        else:
            session = [str(tab.doc.path) for tab in tabs]
            active = window.tabs.currentIndex()
        if self._quitting is not None or len(self.windows) == 1:
            session = session + [p for p in self._still_to_restore if p not in session]
            self.state["session"] = {"files": session, "active": max(active, 0)}
        if window in self.windows:
            self.windows.remove(window)
        self.state.save()

    def quit(self) -> None:
        self._quitting = [str(t.doc.path) for w in self.windows for t in w.all_tabs()]
        front = next((w for w in self.windows if w.isActiveWindow()), None)
        self._active = 0
        if front is not None and front.current() is not None:
            self._active = self._quitting.index(str(front.current().doc.path))
        for window in list(self.windows):
            if not window.close():
                break
        self._quitting = None

    def quit_cancelled(self) -> None:
        self._quitting = None

    def open_from_elsewhere(self, paths: list[str]) -> None:
        if not self.windows:
            return
        window = next((w for w in self.windows if w.isActiveWindow()), self.windows[-1])
        if window.isMinimized():
            window.showNormal()
        window.raise_()
        window.activateWindow()
        for path in paths:
            self.open(window, path)
