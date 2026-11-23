"""메인 창: 메뉴, 툴바, 탭."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QPoint, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QIntValidator, QKeySequence
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QFileDialog, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu,
    QSizePolicy, QStackedWidget, QTabBar, QTabWidget, QToolBar, QToolButton, QWidget,
)

from core.document.models import DocumentError, Link
from features.sign.signature_store import SignatureStore
from features.sign.stroke_processor import to_graphic
from storage import files

from . import file_assoc, signing, ui
from .doc_tab import DocTab
from .i18n import T, is_korean
from .start_page import StartPage

log = logging.getLogger(__name__)

Button = ui.Button
PDF_FILTER = "PDF (*.pdf)"
PALETTE = ("#ffe14d", "#9be564", "#7cc8ff", "#ff9ecb", "#ffb35c", "#e53935")
ZOOMS = (50, 75, 100, 125, 150, 200, 300, 400)
SAFE_SCHEMES = ("http", "https", "mailto")


def is_network_path(path: str) -> bool:
    return path.replace("\\", "/").startswith("//")


class _TabBar(QTabBar):
    torn_off = Signal(int, QPoint)

    def mouseReleaseEvent(self, event) -> None:
        index = self.currentIndex()
        inside = self.rect().adjusted(-40, -40, 40, 40).contains(event.position().toPoint())
        super().mouseReleaseEvent(event)
        if not inside and index >= 0 and event.button() == Qt.MouseButton.LeftButton:
            self.torn_off.emit(index, event.globalPosition().toPoint())


class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.state = controller.state
        self.setWindowTitle("FDP Reader")
        self.setAcceptDrops(True)
        self.resize(1180, 820)

        self.start = StartPage(self.state)
        self.start.open_file.connect(lambda path: self.open_paths([path]))
        self.start.browse.connect(self.browse)
        self.tabs = QTabWidget()
        bar = _TabBar()
        self.tabs.setTabBar(bar)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabs.tabCloseRequested.connect(lambda index: self.close_tab(self.tabs.widget(index)))
        self.tabs.currentChanged.connect(self._tab_switched)
        bar.torn_off.connect(self._tear_off)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.start)
        self.stack.addWidget(self.tabs)
        self.setCentralWidget(self.stack)
        self._shown_tab: DocTab | None = None

        self.actions_: dict[str, QAction] = {}
        self._needs_document: list[QAction] = []
        self._icons: dict[QAction, int] = {}
        self._make_actions()
        self._make_menus()
        self._make_toolbar()
        self.security_label = QLabel()
        self.statusBar().addPermanentWidget(self.security_label)
        self._restore_geometry()
        self.sync()

    # 동작 정의

    def _action(self, name, text, slot, keys="", glyph=0, doc=True, checkable=False) -> QAction:
        action = QAction(text, self)
        if keys:
            shortcuts = [keys] if isinstance(keys, (str, QKeySequence.StandardKey)) else keys
            action.setShortcuts([QKeySequence(k) for k in shortcuts])
            shown = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            action.setToolTip(f"{text.replace('&', '')} ({shown})")
        action.setCheckable(checkable)
        action.triggered.connect(lambda checked=False: slot())
        if glyph:
            self._icons[action] = glyph
            action.setIcon(ui.icon(glyph))
        if doc:
            self._needs_document.append(action)
        self.actions_[name] = action
        self.addAction(action)
        return action

    def _make_actions(self) -> None:
        a = self._action
        view = lambda: self.current().view

        a("open", T("열기…", "Open…"), self.browse, "Ctrl+O", 0xE8E5, doc=False)
        a("save", T("저장", "Save"), self.save, "Ctrl+S", 0xE74E)
        a("save_as", T("다른 이름으로 저장…", "Save as…"), self.save_as, "Ctrl+Shift+S")
        a("flatten", T("서명본 내보내기 (평탄화)…", "Export flattened copy…"),
          self.export_flattened, "Ctrl+Shift+E")
        a("print", T("인쇄…", "Print…"), self.print_document, "Ctrl+P", 0xE749)
        a("security", T("문서 보안 정보", "Document security"), self.show_security)
        a("close_tab", T("탭 닫기", "Close tab"), lambda: self.close_tab(self.current()),
          ["Ctrl+W", "Ctrl+F4"])
        a("detach", T("탭을 새 창으로", "Move tab to new window"),
          lambda: self._tear_off(self.tabs.currentIndex(), None), "Ctrl+Shift+N")
        a("quit", T("끝내기", "Exit"), self.controller.quit, "Ctrl+Q", doc=False)

        a("undo", T("실행 취소", "Undo"), lambda: self.current().history_step(False),
          "Ctrl+Z", 0xE7A7)
        a("redo", T("다시 실행", "Redo"), lambda: self.current().history_step(True),
          ["Ctrl+Y", "Ctrl+Shift+Z"], 0xE7A6)
        a("copy", T("복사", "Copy"), lambda: view().copy(), "Ctrl+C")
        a("select_all", T("이 쪽 글자 모두 선택", "Select all text on page"),
          lambda: view().select_page(), "Ctrl+A")
        a("find", T("찾기", "Find"), lambda: self.current().find(), "Ctrl+F", 0xE721)
        a("find_next", T("다음 찾기", "Find next"), lambda: self.current().search.step(1), "F3")
        a("find_prev", T("이전 찾기", "Find previous"),
          lambda: self.current().search.step(-1), "Shift+F3")

        for name, text, keys, glyph, tool in (
            ("highlight", T("형광펜", "Highlight"), "Ctrl+H", 0xE7E6, "Highlight"),
            ("underline", T("밑줄", "Underline"), "Ctrl+U", 0xE8DC, "Underline"),
            ("strike", T("취소선", "Strikeout"), "Ctrl+Shift+X", 0xEDE0, "StrikeOut"),
            ("note", T("메모", "Note"), "Ctrl+M", 0xE70B, "note"),
            ("text", T("텍스트 상자", "Text box"), "Ctrl+T", 0xE8D2, "text"),
        ):
            a(name, text, lambda t=tool: self.toggle_tool(t), keys, glyph, checkable=True)
        a("mark_note", T("형광펜 + 메모", "Highlight + note"),
          lambda: view().markup_with_note(), "Ctrl+Shift+M")
        a("color", T("마크업 색…", "Markup colour…"), self.choose_color, doc=False)
        a("text_size", T("텍스트 상자 글자 크기…", "Text box font size…"),
          self.choose_text_size, doc=False)

        a("sign", T("서명", "Sign"), lambda: self.toggle_tool("sign"),
          "Ctrl+E", 0xE70F, checkable=True)
        a("sign_image", T("이미지로 서명…", "Sign with an image…"),
          lambda: self._with_tab(signing.from_image_file))
        a("sign_type", T("타이핑 서명…", "Typed signature…"),
          lambda: self._with_tab(signing.from_typing))
        a("sign_manage", T("저장된 서명 관리…", "Manage saved signatures…"),
          lambda: signing.ManageDialog(self).exec(), doc=False)
        as_ink = a("sign_ink", T("서명을 Ink 주석으로 넣기", "Place signatures as Ink annotations"),
                   self._toggle_ink, doc=False, checkable=True)
        as_ink.setChecked(self.state["sign_as_ink"])

        a("panel", T("옆 패널", "Side panel"), lambda: self.current().toggle_panel(), "F4", 0xE700)
        a("focus_document", T("문서로 이동", "Focus document"), lambda: view().setFocus(), "F6")
        a("zoom_in", T("확대", "Zoom in"), lambda: view().set_zoom(view().zoom * 1.2),
          ["Ctrl++", "Ctrl+="], 0xE8A3)
        a("zoom_out", T("축소", "Zoom out"), lambda: view().set_zoom(view().zoom / 1.2),
          "Ctrl+-", 0xE71F)
        a("actual", T("실제 크기", "Actual size"), lambda: view().set_zoom(1.0), "Ctrl+1")
        a("fit_width", T("폭 맞춤", "Fit width"), lambda: view().set_fit("width"),
          ["Ctrl+2", "Ctrl+0"])
        a("fit_page", T("쪽 맞춤", "Fit page"), lambda: view().set_fit("page"), "Ctrl+3")

        modes = QActionGroup(self)
        for name, text, keys in (
            ("single", T("단일 쪽", "Single page"), "Ctrl+Alt+1"),
            ("continuous", T("연속 스크롤", "Continuous"), "Ctrl+Alt+2"),
            ("two", T("두 쪽 보기", "Two pages"), "Ctrl+Alt+3"),
            ("book", T("책 보기 (표지 단독)", "Book (cover alone)"), "Ctrl+Alt+4"),
        ):
            modes.addAction(
                a(f"mode_{name}", text, lambda m=name: view().set_mode(m), keys, checkable=True)
            )
        a("rotate_right", T("보기 오른쪽 회전", "Rotate view right"),
          lambda: self.rotate_view(90), "Ctrl+R", 0xE7AD)
        a("rotate_left", T("보기 왼쪽 회전", "Rotate view left"),
          lambda: self.rotate_view(-90), "Ctrl+Shift+R")
        a("apply_rotation", T("보기 회전을 문서에 적용", "Apply view rotation to document"),
          self.apply_rotation)

        themes = QActionGroup(self)
        for name, text in (
            ("light", T("기본", "Normal")),
            ("dark", T("다크 (그림은 원색)", "Dark (pictures unchanged)")),
            ("sepia", T("세피아", "Sepia")),
            ("gray", T("회색", "Gray")),
        ):
            themes.addAction(
                a(f"theme_{name}", text, lambda t=name: self.controller.set_theme(t),
                  doc=False, checkable=True)
            )
        a("dark", T("다크 모드", "Dark mode"), self.toggle_dark, "Ctrl+D", 0xE708,
          doc=False, checkable=True)

        a("back", T("뒤로", "Back"), lambda: view().go_back(), "Alt+Left", 0xE72B)
        a("forward", T("앞으로", "Forward"), lambda: view().go_forward(), "Alt+Right", 0xE72A)
        a("go_page", T("쪽 번호로 이동", "Go to page"), self.focus_page_box, "Ctrl+G")
        a("next_tab", T("다음 탭", "Next tab"), lambda: self.step_tab(1), ["Ctrl+Tab", "Ctrl+PgDown"])
        a("prev_tab", T("이전 탭", "Previous tab"), lambda: self.step_tab(-1),
          ["Ctrl+Shift+Tab", "Ctrl+Shift+Backtab", "Ctrl+PgUp"])

        languages = QActionGroup(self)
        for code, text in (("ko", "한국어"), ("en", "English")):
            action = a(f"lang_{code}", text, lambda c=code: self.set_language(c),
                       doc=False, checkable=True)
            action.setChecked((code == "ko") == is_korean())
            languages.addAction(action)
        a("register", T("PDF 연결 프로그램으로 등록…", "Register as a PDF app…"),
          self.register_app, doc=False)
        a("unregister", T("연결 프로그램 등록 해제", "Remove PDF app registration"),
          self.unregister_app, doc=False)
        a("about", T("정보", "About"), self.show_about, doc=False)

    def _make_menus(self) -> None:
        act = self.actions_
        bar = self.menuBar()

        def fill(menu, *names) -> None:
            for name in names:
                if name is None:
                    menu.addSeparator()
                else:
                    menu.addAction(act[name])

        file_menu = bar.addMenu(T("파일(&F)", "&File"))
        fill(file_menu, "open")
        self.recent_menu = file_menu.addMenu(T("최근 문서", "Recent documents"))
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        fill(file_menu, None, "save", "save_as", "flatten", "print", None, "security",
             None, "detach", "close_tab", "quit")

        edit = bar.addMenu(T("편집(&E)", "&Edit"))
        fill(edit, "undo", "redo", None, "copy", "select_all", None, "find", "find_next", "find_prev")

        notes = bar.addMenu(T("주석(&A)", "&Annotate"))
        fill(notes, "highlight", "underline", "strike", "mark_note", None, "note", "text",
             None, "color", "text_size")

        sign = bar.addMenu(T("서명(&S)", "&Sign"))
        fill(sign, "sign")
        self.saved_menu = sign.addMenu(T("저장된 서명", "Saved signatures"))
        self.saved_menu.aboutToShow.connect(lambda: self._fill_saved(self.saved_menu))
        fill(sign, "sign_image", "sign_type", None, "sign_manage", "sign_ink")

        view = bar.addMenu(T("보기(&V)", "&View"))
        fill(view, "panel", "focus_document", None,
             "mode_single", "mode_continuous", "mode_two", "mode_book", None,
             "zoom_in", "zoom_out", "actual", "fit_width", "fit_page", None,
             "rotate_right", "rotate_left", "apply_rotation", None, "dark")
        themes = view.addMenu(T("페이지 색", "Page colours"))
        fill(themes, "theme_light", "theme_dark", "theme_sepia", "theme_gray")

        go = bar.addMenu(T("이동(&G)", "&Go"))
        fill(go, "back", "forward", "go_page", None, "next_tab", "prev_tab")

        more = bar.addMenu(T("설정(&T)", "Se&ttings"))
        language = more.addMenu(T("언어", "Language"))
        fill(language, "lang_ko", "lang_en")
        if not files.is_portable():  # 포터블은 레지스트리를 쓰지 않음
            fill(more, None, "register", "unregister")
        fill(more, None, "about")

    def _make_toolbar(self) -> None:
        act = self.actions_
        bar = QToolBar(T("도구", "Tools"), self)
        bar.setObjectName("tools")
        bar.setMovable(False)
        bar.setIconSize(QSize(18, 18))
        self.addToolBar(bar)
        for name in ("panel", "open", "save", "print", None, "back", "forward"):
            bar.addAction(act[name]) if name else bar.addSeparator()

        self.page_box = QLineEdit()
        self.page_box.setAccessibleName(T("쪽 번호", "Page number"))
        self.page_box.setFixedWidth(48)
        self.page_box.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.page_box.setValidator(QIntValidator(1, 999999, self))
        self.page_box.returnPressed.connect(self._page_typed)
        self.page_total = QLabel(" / 0 ")
        bar.addWidget(self.page_box)
        bar.addWidget(self.page_total)

        bar.addAction(act["zoom_out"])
        self.zoom_box = QComboBox()
        self.zoom_box.setAccessibleName(T("배율", "Zoom"))
        self.zoom_box.setEditable(True)
        self.zoom_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.zoom_box.setCompleter(None)
        self.zoom_box.addItems(
            [T("폭 맞춤", "Fit width"), T("쪽 맞춤", "Fit page"), *(f"{z}%" for z in ZOOMS)]
        )
        self.zoom_box.setFixedWidth(104)
        self.zoom_box.activated.connect(self._zoom_picked)
        self.zoom_box.lineEdit().returnPressed.connect(self._zoom_typed)
        bar.addWidget(self.zoom_box)
        for name in ("zoom_in", "rotate_right", "dark", "find", None, "undo", "redo", None,
                     "highlight", "underline", "strike"):
            bar.addAction(act[name]) if name else bar.addSeparator()

        self.color_button = QToolButton()
        self.color_button.setAccessibleName(T("마크업 색", "Markup colour"))
        self.color_button.setToolTip(T("마크업 색", "Markup colour"))
        self.color_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        colors = QMenu(self.color_button)
        for color, name in zip(
            PALETTE,
            (T("노랑", "Yellow"), T("초록", "Green"), T("파랑", "Blue"),
             T("분홍", "Pink"), T("주황", "Orange"), T("빨강", "Red")),
        ):
            colors.addAction(ui.swatch(color), name, lambda c=color: self.set_color(c))
        colors.addAction(act["color"])
        self.color_button.setMenu(colors)
        self.color_button.setIcon(ui.swatch(self.state["color"]))
        bar.addWidget(self.color_button)
        bar.addAction(act["note"])
        bar.addAction(act["text"])

        gap = QWidget()
        gap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(gap)
        self.sign_button = QToolButton()
        self.sign_button.setDefaultAction(act["sign"])
        self.sign_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.sign_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        quick = QMenu(self.sign_button)
        quick.aboutToShow.connect(lambda: self._fill_saved(quick, with_tools=True))
        self.sign_button.setMenu(quick)
        bar.addWidget(self.sign_button)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "_icons"):
            for action, glyph in self._icons.items():
                action.setIcon(ui.icon(glyph))  # OS 다크·고대비 전환

    def _restore_geometry(self) -> None:
        saved = self.state["geometry"]
        if saved:
            self.restoreGeometry(QByteArray.fromBase64(saved.encode("ascii")))

    # 상태 동기화

    def current(self) -> DocTab | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, DocTab) else None

    def all_tabs(self) -> list[DocTab]:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def _with_tab(self, action) -> None:
        tab = self.current()
        if tab and tab.view.allowed("annotate"):
            action(self, tab, self.state)

    def _tab_switched(self, _index: int) -> None:
        previous, self._shown_tab = self._shown_tab, self.current()
        if previous is not None and previous is not self._shown_tab and previous.host is self:
            previous.view.commit()
        self.sync()
        if self._shown_tab is not None:
            self._shown_tab.view.setFocus()

    def sync(self) -> None:
        has_document = self.current() is not None
        self.stack.setCurrentWidget(self.tabs if has_document else self.start)
        if not has_document:
            self.start.refresh()
        self.sync_title()
        self.sync_position()
        self.sync_actions()
        self.sync_security()

    def sync_title(self) -> None:
        for index, tab in enumerate(self.all_tabs()):
            star = "* " if tab.doc.dirty else ""
            self.tabs.setTabText(index, star + tab.doc.path.name.replace("&", "&&"))
            self.tabs.setTabToolTip(index, ui.plain_tooltip(str(tab.doc.path)))
        tab = self.current()
        if tab:
            mark = "* " if tab.doc.dirty else ""
            self.setWindowTitle(f"{mark}{tab.doc.path.name} - FDP Reader")
        else:
            self.setWindowTitle("FDP Reader")

    def sync_position(self) -> None:
        tab = self.current()
        self.page_box.setEnabled(tab is not None)
        self.zoom_box.setEnabled(tab is not None)
        if tab is None:
            self.page_box.clear()
            self.page_total.setText(" / 0 ")
            return
        if not self.page_box.hasFocus():
            self.page_box.setText(str(tab.view.page + 1))
        self.page_total.setText(f" / {tab.doc.page_count} ")
        if not self.zoom_box.lineEdit().hasFocus():
            self.zoom_box.setEditText(f"{round(tab.view.zoom * 100)}%")

    def sync_actions(self) -> None:
        act = self.actions_
        tab = self.current()
        for action in self._needs_document:
            action.setEnabled(tab is not None)
        self.color_button.setEnabled(tab is not None)
        theme = self.state["theme"]
        act["dark"].setChecked(theme == "dark")
        if f"theme_{theme}" in act:
            act[f"theme_{theme}"].setChecked(True)
        self.saved_menu.setEnabled(tab is not None)
        if tab is None:
            return
        doc, view = tab.doc, tab.view
        editable = doc.allows("annotate")
        for name, tool in (
            ("highlight", "Highlight"), ("underline", "Underline"), ("strike", "StrikeOut"),
            ("note", "note"), ("text", "text"), ("sign", "sign"),
        ):
            act[name].setEnabled(editable)
            act[name].setChecked(view.tool == tool)
        for name in ("sign_image", "sign_type"):
            act[name].setEnabled(editable)
        act["mark_note"].setEnabled(editable and view.has_selection)
        act["undo"].setEnabled(doc.can_undo)
        act["redo"].setEnabled(doc.can_redo)
        act["copy"].setEnabled(view.has_selection and doc.allows("copy"))
        act["print"].setEnabled(doc.allows("print"))
        act["flatten"].setEnabled(doc.allows("flatten"))
        act["apply_rotation"].setEnabled(view.rotation != 0 and doc.allows("rotate"))
        act["back"].setEnabled(view.can_go_back)
        act["forward"].setEnabled(view.can_go_forward)
        act[f"mode_{view.mode}"].setChecked(True)

    def sync_security(self) -> None:
        tab = self.current()
        parts = []
        if tab:
            doc = tab.doc
            blocked = [
                label
                for what, label in (
                    ("print", T("인쇄", "print")),
                    ("copy", T("복사", "copy")),
                    ("annotate", T("주석", "annotate")),
                )
                if not doc.allows(what)
            ]
            if blocked:
                parts.append(T("제한됨: ", "Restricted: ") + ", ".join(blocked))
            elif doc.encrypted:
                parts.append(T("암호로 보호됨", "Password protected"))
            if doc.rebuilt:
                parts.append(T("손상 복구본", "Repaired copy"))
        self.security_label.setText("  ·  ".join(parts))

    def document_changed(self, tab: DocTab) -> None:
        self.sync_title()
        if tab is self.current():
            self.sync_actions()

    def show_message(self, text: str) -> None:
        if text:
            self.statusBar().showMessage(text, 6000)
        else:
            self.statusBar().clearMessage()

    # 열기·탭

    def browse(self) -> None:
        tab = self.current()
        recent = self.state.recent()
        folder = ""
        if tab:
            folder = str(tab.doc.path.parent)
        elif recent:
            folder = str(Path(recent[0]["path"]).parent)
        paths, _ = QFileDialog.getOpenFileNames(self, T("PDF 열기", "Open PDF"), folder, PDF_FILTER)
        self.open_paths(paths)

    def open_paths(self, paths) -> None:
        for path in paths:
            self.controller.open(self, path)

    def add_tab(self, tab: DocTab) -> None:
        tab.host = self
        # 탭을 보여 주기 전에 작업 영역을 띄워야 첫 배치가 제 크기로 계산됨
        self.stack.setCurrentWidget(self.tabs)
        index = self.tabs.addTab(tab, tab.doc.path.name)
        self.tabs.setCurrentIndex(index)
        tab.show()
        self.sync()

    def release_tab(self, tab: DocTab) -> None:
        if self._shown_tab is tab:
            self._shown_tab = None
        tab.host = None
        self.tabs.removeTab(self.tabs.indexOf(tab))
        self.sync()

    def step_tab(self, by: int) -> None:
        if self.tabs.count():
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + by) % self.tabs.count())

    def _tear_off(self, index: int, position: QPoint | None) -> None:
        tab = self.tabs.widget(index)
        if tab is None or (self.tabs.count() < 2 and position is None):
            return
        tab.view.commit()
        self.controller.move_tab(tab, self, position)

    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if any(u.isLocalFile() and u.toLocalFile().lower().endswith(".pdf") for u in urls):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [
            u.toLocalFile()
            for u in event.mimeData().urls()
            if u.isLocalFile() and u.toLocalFile().lower().endswith(".pdf")
        ]
        event.acceptProposedAction()
        self.open_paths(paths)

    def _fill_recent(self) -> None:
        menu = self.recent_menu
        menu.clear()
        for entry in self.state.recent():
            path = entry["path"]
            mark = T("[고정] ", "[Pinned] ") if entry.get("pinned") else ""
            action = menu.addAction(mark + Path(path).name.replace("&", "&&"))
            action.triggered.connect(lambda _=False, p=path: self.open_paths([p]))
        if menu.isEmpty():
            menu.addAction(T("없음", "None")).setEnabled(False)
            return
        tab = self.current()
        if tab:
            menu.addSeparator()
            menu.addAction(T("현재 문서 고정 / 해제", "Pin / unpin current document"), self._pin_current)

    def _pin_current(self) -> None:
        self.state.toggle_pin(str(self.current().doc.path))
        self.state.save()

    def _fill_saved(self, menu: QMenu, with_tools: bool = False) -> None:
        menu.clear()
        tab = self.current()
        for number, (_, signature) in enumerate(SignatureStore().all(), 1):
            try:
                graphic_icon = signing.icon_of(to_graphic(signature))
            except (KeyError, ValueError):
                log.warning("저장된 서명의 형식이 잘못됨")
                continue
            action = menu.addAction(graphic_icon, T(f"서명 {number}", f"Signature {number}"))
            action.setEnabled(tab is not None and tab.doc.allows("annotate"))
            action.triggered.connect(
                lambda _=False, s=signature: signing.use_saved(self, self.current(), s, self.state)
            )
        if menu.isEmpty():
            menu.addAction(T("저장된 서명 없음", "No saved signatures")).setEnabled(False)
        if with_tools:
            menu.addSeparator()
            for name in ("sign_image", "sign_type", "sign_manage"):
                menu.addAction(self.actions_[name])

    # 보기 명령

    def toggle_tool(self, tool: str) -> None:
        view = self.current().view
        if tool in ("Highlight", "Underline", "StrikeOut") and view.has_selection:
            view.commit()
            view.markup(tool)  # 이미 고른 글자가 있으면 바로 칠하고 끝
            self.sync_actions()
            return
        view.set_tool("select" if view.tool == tool else tool)
        self.sync_actions()

    def _toggle_ink(self) -> None:
        self.state["sign_as_ink"] = self.actions_["sign_ink"].isChecked()
        self.state.save()

    def toggle_dark(self) -> None:
        self.controller.set_theme("light" if self.state["theme"] == "dark" else "dark")

    def rotate_view(self, degrees: int) -> None:
        tab = self.current()
        tab.view.commit()
        tab.view.rotate_view(degrees)
        self.sync_actions()

    def apply_rotation(self) -> bool:
        tab = self.current()
        view = tab.view
        view.commit()
        ok, _ = view.run_edit(lambda: tab.doc.rotate_pages(view.rotation))
        if ok:
            view.rotation = 0
            view.page_geometry_changed()
            tab.search.start()
            self.sync_actions()
        return ok

    def focus_page_box(self) -> None:
        self.page_box.setFocus()
        self.page_box.selectAll()

    def _page_typed(self) -> None:
        tab = self.current()
        if tab and self.page_box.text():
            page = int(self.page_box.text()) - 1
            tab.view.setFocus()
            tab.view.go_to(page, remember=True)
            self.sync_position()

    def _zoom_picked(self, index: int) -> None:
        tab = self.current()
        if not tab:
            return
        tab.view.setFocus()
        if index < 2:
            tab.view.set_fit(("width", "page")[index])
        else:
            tab.view.set_zoom(ZOOMS[index - 2] / 100)
        self.sync_position()

    def _zoom_typed(self) -> None:
        tab = self.current()
        if not tab:
            return
        try:
            value = float(self.zoom_box.currentText().strip().rstrip("%"))
        except ValueError:
            value = 0
        tab.view.setFocus()
        if 0 < value < 100000:  # nan·inf 제외
            tab.view.set_zoom(value / 100)
        self.sync_position()

    def choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.state["color"]), self)
        if color.isValid():
            self.set_color(color.name())

    def set_color(self, color: str) -> None:
        self.state["color"] = color
        self.state.save()
        for window in self.controller.windows:
            window.color_button.setIcon(ui.swatch(color))

    def choose_text_size(self) -> None:
        value, ok = QInputDialog.getInt(
            self, T("글자 크기", "Font size"), "pt", int(self.state["text_size"]), 6, 72
        )
        if ok:
            self.state["text_size"] = value
            self.state.save()

    def set_language(self, code: str) -> None:
        self.state["language"] = code
        self.state.save()
        ui.inform(
            self,
            T("다음에 실행할 때 적용됩니다.", "The change applies the next time you start FDP Reader."),
        )

    # 링크: PDF 는 신뢰하지 않는 입력

    def open_link(self, tab: DocTab, link: Link) -> None:
        target = link.target.strip()
        if link.kind == "uri":
            url = QUrl(target)
            if url.scheme().lower() not in SAFE_SCHEMES:
                self._blocked(target)
                return
            shown = url.toString(QUrl.ComponentFormattingOption.FullyEncoded)
            question = T("다음 주소를 브라우저로 열까요?", "Open this address in your browser?")
            if ui.confirm(self, f"{question}\n\n{shown}"):
                QDesktopServices.openUrl(url)
            return
        # 다른 PDF 만 이 앱으로 엶. 실행 파일·네트워크 경로(자격 증명 유출)는 열지 않음
        if not target.lower().endswith(".pdf") or is_network_path(target) or "://" in target:
            self._blocked(target)
            return
        path = os.path.normpath(os.path.join(tab.doc.path.parent, target))
        if is_network_path(path) and not is_network_path(str(tab.doc.path)):
            self._blocked(target)
            return
        question = T("연결된 문서를 열까요?", "Open the linked document?")
        if ui.confirm(self, f"{question}\n\n{path}"):
            opened = self.controller.open(self, path)
            if opened and link.page:
                opened.view.go_to(link.page)

    def _blocked(self, target: str) -> None:
        ui.warn(
            self,
            T("안전을 위해 이 링크는 열지 않습니다.", "This link is blocked for safety.")
            + f"\n\n{target}",
        )

    # 서명

    def begin_signature(self, tab: DocTab, pno: int, rect) -> None:
        signing.draw_signature(self, tab, pno, rect, self.state)

    # 저장·인쇄

    def save(self) -> bool:
        tab = self.current()
        return bool(tab) and self.save_tab(tab)

    def save_as(self) -> bool:
        tab = self.current()
        return bool(tab) and self.save_tab(tab, choose_path=True)

    def save_tab(self, tab: DocTab, choose_path: bool = False) -> bool:
        if not tab.view.commit():
            return False
        self.tabs.setCurrentWidget(tab)
        doc = tab.doc
        if tab.view.rotation and doc.allows("rotate"):
            answer = ui.choose(
                self,
                T("보기 회전을 저장 파일에 반영할까요?", "Apply the view rotation to the saved file?"),
                Button.Yes | Button.No | Button.Cancel,
                Button.No,
            )
            if answer not in (Button.Yes, Button.No):
                return False
            if answer == Button.Yes and not self.apply_rotation():
                return False

        target = None
        if not choose_path:
            if not doc.dirty:
                self.show_message(T("바뀐 내용이 없습니다.", "Nothing to save."))
                return True
            if doc.changed_on_disk():
                answer = ui.choose(
                    self,
                    T(
                        "이 파일이 다른 프로그램에서 바뀌었습니다.\n"
                        "'아니요'를 누르면 다른 이름으로 저장합니다. 덮어쓸까요?",
                        "This file was changed by another program.\n"
                        "Choose No to save under another name. Overwrite it?",
                    ),
                    Button.Yes | Button.No | Button.Cancel,
                    Button.No,
                )
                if answer not in (Button.Yes, Button.No):
                    return False
                choose_path = answer == Button.No
            elif doc.rebuilt:
                answer = ui.choose(
                    self,
                    T(
                        "손상된 문서를 복구한 사본이라, 저장하면 파일 구조가 새로 써집니다.\n"
                        "'아니요'를 누르면 다른 이름으로 저장합니다. 덮어쓸까요?",
                        "This is a repaired copy, so saving rewrites the file structure.\n"
                        "Choose No to save under another name. Overwrite it?",
                    ),
                    Button.Yes | Button.No | Button.Cancel,
                    Button.No,
                )
                if answer not in (Button.Yes, Button.No):
                    return False
                choose_path = answer == Button.No
        if choose_path:
            chosen, _ = QFileDialog.getSaveFileName(
                self, T("다른 이름으로 저장", "Save as"), str(doc.path), PDF_FILTER
            )
            if not chosen:
                return False
            target = chosen
            other = self.controller.find_tab(target)
            if other is not None and other is not tab:
                ui.warn(self, T("그 파일은 다른 탭에 열려 있습니다.", "That file is open in another tab."))
                return False
        try:
            doc.save(target)
        except DocumentError as error:
            hint = T(
                "다른 프로그램이 파일을 쓰고 있으면 닫거나 '다른 이름으로 저장'을 쓰세요.",
                "If another program is using the file, close it or use Save as.",
            )
            ui.warn(self, f"{ui.error_text(error)}\n\n{hint}")
            return False
        if target:
            self.state.add_recent(doc.path)
            self.state.save()
        self.sync_title()
        self.sync_actions()
        self.show_message(T("저장했습니다.", "Saved."))
        return True

    def export_flattened(self) -> None:
        tab = self.current()
        if not tab.view.commit():
            return
        doc = tab.doc
        if doc.has_digital_signature and not ui.confirm(
            self,
            T("평탄화하면 기존 디지털 서명은 무효가 됩니다. 계속할까요?",
              "Flattening invalidates existing digital signatures. Continue?"),
        ):
            return
        suffix = T("_서명본", "_signed")
        suggested = doc.path.with_name(f"{doc.path.stem}{suffix}.pdf")
        chosen, _ = QFileDialog.getSaveFileName(
            self, T("서명본 내보내기", "Export flattened copy"), str(suggested), PDF_FILTER
        )
        if not chosen:
            return
        if self.controller.find_tab(chosen) is not None:
            ui.warn(
                self,
                T("열려 있는 문서 위에는 내보낼 수 없습니다.", "Cannot export over an open document."),
            )
            return
        try:
            doc.export_flattened(chosen)
        except DocumentError as error:
            ui.warn(self, ui.error_text(error))
            return
        self.show_message(T("서명본을 내보냈습니다: ", "Exported: ") + chosen)

    def print_document(self) -> None:
        tab = self.current()
        if tab.view.commit():
            from . import printing  # 시작 시간을 줄이려고 여기서 불러옴

            printing.run_dialog(self, tab.doc, tab.view.page)

    def show_security(self) -> None:
        doc = self.current().doc
        yes, no = T("허용", "Allowed"), T("제한", "Not allowed")
        rows = [
            (T("암호 보호", "Encrypted"), T("예", "Yes") if doc.encrypted else T("아니요", "No")),
            (T("인쇄", "Printing"), yes if doc.allows("print") else no),
            (T("고화질 인쇄", "High-quality printing"), yes if doc.allows("print_hq") else no),
            (T("내용 복사", "Copying"), yes if doc.allows("copy") else no),
            (T("주석", "Annotations"), yes if doc.allows("annotate") else no),
            (T("양식 입력", "Form filling"), yes if doc.allows("form") else no),
            (T("디지털 서명", "Digital signature"),
             T("있음 (유효성은 검증하지 않음)", "Present (not verified)")
             if doc.has_digital_signature else T("없음", "None")),
        ]
        ui.inform(self, "\n".join(f"{name}: {value}" for name, value in rows))

    def register_app(self) -> None:
        question = T(
            "현재 사용자 계정에 FDP Reader를 PDF 연결 프로그램으로 등록합니다.\n"
            "기본 앱 선택은 이어서 열리는 Windows 설정에서 직접 하면 됩니다. 계속할까요?",
            "This registers FDP Reader as a PDF app for the current user.\n"
            "You choose the default app in Windows Settings, which opens next. Continue?",
        )
        if not ui.confirm(self, question):
            return
        try:
            file_assoc.register()
        except OSError as error:
            ui.warn(self, str(error))
            return
        QDesktopServices.openUrl(QUrl("ms-settings:defaultapps"))

    def unregister_app(self) -> None:
        if ui.confirm(self, T("등록을 해제할까요?", "Remove the registration?")):
            try:
                file_assoc.unregister()
            except OSError as error:
                ui.warn(self, str(error))

    def show_about(self) -> None:
        ui.inform(
            self,
            "FDP Reader (For Document Player)\n\n"
            + T(
                "완전 오프라인: 문서와 서명을 외부로 보내지 않습니다.\n"
                "PDF 엔진: PyMuPDF (AGPL-3.0)",
                "Fully offline: documents and signatures never leave this PC.\n"
                "PDF engine: PyMuPDF (AGPL-3.0)",
            )
            + f"\n\n{T('데이터 폴더', 'Data folder')}: {files.data_dir()}",
        )

    # 닫기

    def ask_to_save(self, tab: DocTab) -> bool:
        """닫아도 되면 True."""
        if not tab.view.commit():
            return False
        if not tab.doc.dirty:
            return True
        self.tabs.setCurrentWidget(tab)
        answer = ui.choose(
            self,
            T(f"'{tab.doc.path.name}'의 변경 내용을 저장할까요?",
              f"Save changes to '{tab.doc.path.name}'?"),
            Button.Save | Button.Discard | Button.Cancel,
            Button.Save,
        )
        if answer == Button.Save:
            return self.save_tab(tab)
        return answer == Button.Discard

    def close_tab(self, tab: DocTab | None) -> None:
        if tab and self.ask_to_save(tab):
            self.controller.forget(tab)
            self.release_tab(tab)
            tab.dispose()

    def closeEvent(self, event) -> None:
        if not all(self.ask_to_save(tab) for tab in self.all_tabs()):
            event.ignore()
            self.controller.quit_cancelled()
            return
        self.state["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.controller.window_closing(self)
        for tab in self.all_tabs():
            self.release_tab(tab)
            tab.dispose()
        event.accept()
        self.deleteLater()
