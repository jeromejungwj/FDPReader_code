"""GUI 흐름. 화면·커서·레지스트리·사용자 데이터는 건드리지 않음."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import unittest
from unittest import mock

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import pymupdf as mu

from app import file_assoc, layout, main_window, printing, ui
from app.controller import Controller
from core.document.models import Link
from core.render.service import RenderService
from features.forms.editors import qt_date_format
from features.sign import sign_canvas
from features.sign.contacts import Contact
from storage.state import State
from tests import helpers
from tests.test_document import l_shape

qt =QApplication.instance() or QApplication([])


def wait(condition, seconds=8.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qt.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return False


def whole(widget) -> QRectF:
    return QRectF(widget.rect())


class AppCase(helpers.TempCase):
    @classmethod
    def setUpClass(cls):
        cls.service = RenderService()

    @classmethod
    def tearDownClass(cls):
        cls.service.shutdown()

    def setUp(self):
        super().setUp()
        self.warnings = []
        for name in ("warn", "inform"):
            patcher = mock.patch.object(ui, name, lambda _p, text: self.warnings.append(text))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.controller = Controller(State(), self.service)
        self.window = self.controller.new_window()
        self.window.resize(1100, 800)
        self.window.show()

    def tearDown(self):
        for window in list(self.controller.windows):
            for tab in window.all_tabs():
                window.release_tab(tab)
                tab.dispose()
            self.controller.windows.remove(window)
            window.hide()
            window.deleteLater()
        qt.processEvents()
        super().tearDown()

    def open_tab(self, path):
        tab = self.controller.open(self.window, str(path))
        self.assertTrue(wait(lambda: tab.view._layout is not None))
        tab.view.setFocus()
        return tab

    def screen_point(self, view, pno, x, y) -> QPoint:
        return view.to_view(pno, (x, y, x, y)).topLeft().toPoint()

    def drag(self, view, start: QPoint, end: QPoint):
        left = Qt.MouseButton.LeftButton
        QTest.mousePress(view.viewport(), left, pos=start)
        for step in range(1, 6):
            QTest.mouseMove(view.viewport(), start + (end - start) * step / 5)
        QTest.mouseRelease(view.viewport(), left, pos=end)


class Viewing(AppCase):
    def test_tiles_arrive_and_follow_edits(self):
        tab = self.open_tab(helpers.plain(self.tmp / "a.pdf"))
        view = tab.view

        def sharp():
            key = view._scale_key()
            slot = view.visible_slots()[0]
            tiles = [view._tiles.get(("tile", 0, key, view.theme, *at))
                     for at in view._tile_range(slot, key)]
            return tiles and all(t and t.gen == view.doc.page_gen[0] and t.pixmap for t in tiles)

        self.assertTrue(wait(sharp))
        view.run_edit(lambda: view.doc.add_note(0, 20, 20, "n", (1, 0, 0)))
        self.assertTrue(wait(sharp))

    def test_arriving_tiles_repaint_only_their_area_and_cover_the_page(self):
        tab = self.open_tab(helpers.plain(self.tmp / "a.pdf"))
        view = tab.view
        for _ in range(4):
            view.rotate_view(90)
            areas = []
            with mock.patch.object(view, "_update_area", wraps=view._update_area) as update:
                view._tiles.clear()
                view.schedule_render()
                key = view._scale_key()
                slot = next(s for s in view.visible_slots() if s.pno == view.page)
                wanted = [("tile", slot.pno, key, view.theme, *at)
                          for at in view._tile_range(slot, key)]
                self.assertTrue(wait(lambda: all(view._tiles.get(k) for k in wanted)))
                for call in update.call_args_list:
                    pno, clip = call.args
                    if pno == slot.pno and clip:
                        areas.append(view.to_view(pno, clip))
            self.assertTrue(areas)
            seen = view.to_view(slot.pno, (0, 0, *tab.doc.sizes[slot.pno])).intersected(
                view.to_view(slot.pno, view.to_page_rect(
                    slot.pno, whole(view.viewport())))
            )
            covered = areas[0]
            for area in areas[1:]:
                covered = covered.united(area)
            self.assertTrue(covered.adjusted(-2, -2, 2, 2).contains(seen))

    def test_renderer_crash_recovers(self):
        tab = self.open_tab(helpers.plain(self.tmp / "a.pdf"))
        old = self.service._process
        with self.assertLogs("core.render.service"):
            old.terminate()
            self.assertTrue(wait(lambda: self.service._process is not old))
        tab.view.set_zoom(1.3)
        key = tab.view._scale_key()
        self.assertTrue(wait(lambda: tab.view._tiles.get(("tile", 0, key, "light", 0, 0))))

    def test_modes_zoom_navigation_and_history(self):
        tab = self.open_tab(helpers.plain(self.tmp / "a.pdf", pages=9))
        view = tab.view
        for mode in layout.MODES:
            view.set_mode(mode)
            view.go_to(5)
            self.assertIn(view.page, (4, 5), mode)
            self.assertIn(5, [slot.pno for slot in view.visible_slots()], mode)
        view.set_mode("continuous")
        view.go_to(0)
        view.setFocus()
        QTest.keyClick(view, Qt.Key.Key_PageDown)
        self.assertEqual(view.page, 1)
        QTest.keyClick(view, Qt.Key.Key_End)
        self.assertEqual(view.page, 8)
        view.go_back()
        self.assertEqual(view.page, 1)
        view.go_forward()
        self.assertEqual(view.page, 8)
        view.set_zoom(2.0)
        self.assertEqual(view.page, 8)
        self.assertEqual(view.zoom, 2.0)

    def test_hit_is_inverse_of_to_view_in_every_rotation(self):
        view = self.open_tab(helpers.plain(self.tmp / "a.pdf")).view
        for _ in range(4):
            view.rotate_view(90)
            point = view.to_view(view.page, (70, 90, 70, 90)).topLeft()
            pno, x, y, inside = view.hit(point)
            self.assertEqual(pno, view.page)
            self.assertAlmostEqual(x, 70, delta=0.01)
            self.assertAlmostEqual(y, 90, delta=0.01)

    def test_position_and_session_come_back(self):
        first = helpers.plain(self.tmp / "a.pdf", pages=8)
        second = helpers.plain(self.tmp / "b.pdf")
        tab = self.open_tab(first)
        self.open_tab(second)
        self.window.tabs.setCurrentWidget(tab)
        qt.processEvents()
        tab.view.set_mode("two")
        tab.view.go_to(4)
        self.assertTrue(self.window.close())
        qt.processEvents()

        self.controller = Controller(State(), self.service)
        self.window = self.controller.start([])
        self.assertTrue(wait(lambda: self.window.tabs.count() == 2))
        self.assertEqual([t.doc.path.name for t in self.window.all_tabs()], ["a.pdf", "b.pdf"])
        current = self.window.current()
        self.assertEqual(current.doc.path.name, "a.pdf")
        self.assertTrue(wait(lambda: current.view._layout is not None))
        self.assertEqual((current.view.page, current.view.mode), (4, "two"))

    def test_search_panel(self):
        tab = self.open_tab(helpers.plain(self.tmp / "a.pdf", pages=5))
        tab.find()
        tab.search.query.setText("hello")
        tab.search.start()
        self.assertTrue(wait(lambda: not tab.search._worker.isActive()))
        self.assertEqual(tab.search.results.count(), 5)
        tab.search.step(1)
        self.assertEqual(tab.view.hit_now[0], 1)

    def test_tab_moves_to_new_window(self):
        tab = self.open_tab(helpers.plain(self.tmp / "a.pdf"))
        self.open_tab(helpers.plain(self.tmp / "b.pdf"))
        self.controller.move_tab(tab, self.window, None)
        self.assertEqual(len(self.controller.windows), 2)
        self.assertIs(tab.host, self.controller.windows[1])
        self.assertEqual(self.window.tabs.count(), 1)

    def test_dark_mode_applies_to_tiles(self):
        tab = self.open_tab(helpers.plain(self.tmp / "a.pdf"))
        self.controller.set_theme("dark")
        key = tab.view._scale_key()
        tile_key = ("tile", 0, key, "dark", 0, 0)
        self.assertTrue(wait(lambda: tab.view._tiles.get(tile_key)))
        image = tab.view._tiles.get(tile_key).pixmap.toImage()
        self.assertLess(image.pixelColor(3, 3).red(), 60)


class Editing(AppCase):
    def test_drag_select_and_highlight(self):
        tab = self.open_tab(helpers.plain(self.tmp / "a.pdf"))
        view = tab.view
        self.drag(view, self.screen_point(view, 0, 50, 76), self.screen_point(view, 0, 200, 76))
        self.assertTrue(view.has_selection)
        view.copy()
        self.assertIn("Page 1", qt.clipboard().text())
        self.window.toggle_tool("Highlight")
        self.assertEqual([a.kind for a in tab.doc.annots(0)], ["Highlight"])
        tab.history_step(False)
        self.assertEqual(tab.doc.annots(0), [])

    def test_double_then_triple_click(self):
        tab = self.open_tab(helpers.plain(self.tmp / "a.pdf"))
        view = tab.view
        page = tab.doc.text(0)
        at = page.text.index("hello") + 1
        box = page.boxes[at]
        point = self.screen_point(view, 0, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        left = Qt.MouseButton.LeftButton
        QTest.mouseClick(view.viewport(), left, pos=point)
        QTest.mouseDClick(view.viewport(), left, pos=point)
        self.assertEqual([page.text[a:b] for _, a, b in view.spans()], ["hello"])
        QTest.mouseClick(view.viewport(), left, pos=point)
        self.assertEqual([page.text[a:b] for _, a, b in view.spans()], ["Page 1 hello world"])

    def test_type_korean_text_box_and_save_commits_it(self):
        path = helpers.plain(self.tmp / "a.pdf")
        tab = self.open_tab(path)
        tab.view.begin_text(0, 50, 150)
        tab.view._editor.setPlainText("안녕하세요 2026")
        self.assertTrue(self.window.save())
        with mu.open(path) as saved:
            self.assertEqual([a.info["content"] for a in saved[0].annots()], ["안녕하세요 2026"])
        self.assertEqual(self.warnings, [])

    def test_text_typed_before_page_flip_is_not_lost(self):
        tab = self.open_tab(helpers.plain(self.tmp / "a.pdf"))
        view = tab.view
        view.set_mode("single")
        view.begin_text(0, 50, 150)
        view._editor.setPlainText("keep me")
        view.go_to(2)  # 단일 쪽 보기에서 휠로 넘긴 상황: 편집 중인 쪽이 배치에서 빠짐
        self.assertTrue(view.commit())
        self.assertEqual([a.text for a in tab.doc.annots(0)], ["keep me"])

    def test_enter_opens_recent_document_from_start_page(self):
        path = helpers.plain(self.tmp / "recent.pdf")
        self.controller.state.add_recent(path)
        self.window.sync()
        self.window.activateWindow()
        recent = self.window.start.recent
        recent.setFocus()
        recent.setCurrentRow(0)
        QTest.keyClick(recent, Qt.Key.Key_Return)
        self.assertEqual(self.window.tabs.count(), 1)

    def test_form_fill_with_tab_key(self):
        tab = self.open_tab(helpers.form(self.tmp / "f.pdf"))
        view = tab.view
        name = next(f for f in tab.doc.fields(0) if f.name == "name")
        view.activate(name)
        view._editor.input.setText("홍길동")
        QTest.keyClick(view._editor.input, Qt.Key.Key_Tab)
        value = next(f for f in tab.doc.fields(0) if f.name == "name").value
        self.assertEqual(value, "홍길동")
        self.assertEqual(view._focused.name, "memo")

    def test_signature_field_click_goes_straight_to_signing(self):
        tab = self.open_tab(helpers.form(self.tmp / "f.pdf"))
        field = next(f for f in tab.doc.fields(0) if f.kind == "signature")
        asked = []
        with mock.patch.object(self.window, "begin_signature", lambda *args: asked.append(args)):
            tab.view.set_tool("sign")
            x0, y0, x1, y1 = field.rect
            middle = self.screen_point(tab.view, 0, (x0 + x1) / 2, (y0 + y1) / 2)
            QTest.mouseClick(tab.view.viewport(), Qt.MouseButton.LeftButton, pos=middle)
        self.assertEqual(asked[0][1:], (0, field.rect))

    def test_signature_end_to_end(self):
        path = helpers.plain(self.tmp / "a.pdf")
        tab = self.open_tab(path)
        view = tab.view

        def write_and_confirm(dialog):
            canvas = dialog.canvas
            canvas.begin(0.1, 0.5, 0.0)
            for i in range(1, 20):
                canvas.extend(0.1 + i * 0.04, 0.5 + (i % 4) * 0.03, i * 0.01)
            dialog.confirm()  # '이 서명 저장'은 기본으로 켜져 있어야 함
            return dialog.result()

        with (
            mock.patch.object(sign_canvas.touchpad_input, "find_touchpads", lambda: []),
            mock.patch.object(sign_canvas.SignDialog, "exec", write_and_confirm),
        ):
            view.set_tool("sign")
            self.drag(view, self.screen_point(view, 0, 100, 200), self.screen_point(view, 0, 300, 280))

        annot = tab.doc.annots(0)[0]
        self.assertEqual(annot.kind, "Stamp")
        x0, y0, x1, y1 = annot.rect
        self.assertTrue(98 <= x0 and x1 <= 302 and 198 <= y0 and y1 <= 282, annot.rect)
        self.assertEqual(view._picked.xref, annot.xref)
        self.assertEqual(len(list((self.tmp / "data" / "signatures").glob("*.sig"))), 1)

        self.drag(
            view,
            self.screen_point(view, 0, (x0 + x1) / 2, (y0 + y1) / 2),
            self.screen_point(view, 0, (x0 + x1) / 2 + 20, (y0 + y1) / 2 + 30),
        )
        self.assertAlmostEqual(tab.doc.annots(0)[0].rect[0], x0 + 20, delta=2)

        x0, y0, x1, y1 = tab.doc.annots(0)[0].rect
        self.drag(view, self.screen_point(view, 0, x1, y1), self.screen_point(view, 0, x1 + 40, y1 + 40))
        a0, b0, a1, b1 = tab.doc.annots(0)[0].rect
        self.assertAlmostEqual((a0, b0), (x0, y0), delta=1)  # 맞은편 모서리는 그대로
        self.assertGreater(a1 - a0, x1 - x0 + 20)
        self.assertAlmostEqual((a1 - a0) / (b1 - b0), (x1 - x0) / (y1 - y0), delta=0.05)
        self.assertTrue(self.window.save())
        with mu.open(path) as saved:
            self.assertEqual([a.type[1] for a in saved[0].annots()], ["Stamp"])

    def test_copy_and_paste_signature(self):
        tab = self.open_tab(helpers.plain(self.tmp / "a.pdf"))
        view = tab.view
        said = []
        view.message.connect(said.append)
        self.assertTrue(view.place_signature(0, (100, 200, 200, 250), l_shape()))
        source = tab.doc.annots(0)[0]
        copy = self.window.actions_["copy"]
        self.assertTrue(copy.isEnabled())
        copy.trigger()

        view.go_to(1)
        self.assertTrue(wait(lambda: view.page == 1))
        view.paste(QPointF(self.screen_point(view, 1, 300, 150)))  # 가리킨 자리 가운데
        pasted = tab.doc.annots(1)
        self.assertEqual([a.kind for a in pasted], ["Stamp"])
        for got, want in zip(pasted[0].rect, (250, 125, 350, 175)):
            self.assertAlmostEqual(got, want, delta=1)
        self.assertEqual(view._picked.xref, pasted[0].xref)

        view.paste(QPointF(-5, -5))  # 마우스가 문서 밖이면 지금 쪽의 원본과 같은 자리
        self.assertEqual(len(tab.doc.annots(1)), 2)
        self.assertIn(source.rect, [a.rect for a in tab.doc.annots(1)])
        self.assertEqual(tab.doc.annots(0), [source])

        tab.history_step(False)
        self.assertEqual(len(tab.doc.annots(1)), 1)

        other = self.open_tab(helpers.plain(self.tmp / "b.pdf"))
        other.view.paste(QPointF(self.screen_point(other.view, 0, 300, 400)))
        self.assertEqual(other.doc.annots(0), [])  # 다른 문서에는 안 붙음

    def test_ctrl_v_in_text_box_still_pastes_text(self):
        view = self.open_tab(helpers.plain(self.tmp / "a.pdf")).view
        self.window.activateWindow()
        view.begin_text(0, 50, 150)
        qt.clipboard().setText("붙인 글")
        view._editor.setFocus()
        QTest.keyClick(view._editor, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(view._editor.toPlainText(), "붙인 글")  # 창의 Ctrl+V 가 가로채지 않음

    def test_no_attribute_hides_a_method(self):
        view = self.open_tab(helpers.plain(self.tmp / "a.pdf")).view
        from PySide6.QtCore import Signal

        hidden = [
            name for name in vars(view)
            if callable(found := getattr(type(view), name, None)) and not isinstance(found, Signal)
        ]
        self.assertEqual(hidden, [])  # 예: 화면의 _resized 플래그가 크기 조절 메서드를 가렸음

    def test_keyboard_only_move_and_delete(self):
        tab = self.open_tab(helpers.plain(self.tmp / "a.pdf"))
        view = tab.view
        view.run_edit(lambda: tab.doc.add_note(0, 50, 150, "n", (1, 0, 0)))
        QTest.keyClick(view, Qt.Key.Key_Tab)
        self.assertIsNotNone(view._picked)
        QTest.keyClick(view, Qt.Key.Key_Right)
        QTest.keyClick(view, Qt.Key.Key_Right)
        self.assertTrue(view.commit())
        self.assertAlmostEqual(tab.doc.annots(0)[0].rect[0], 54, delta=0.01)
        QTest.keyClick(view, Qt.Key.Key_Delete)
        self.assertEqual(tab.doc.annots(0), [])

    def test_closing_dirty_tab_can_be_cancelled(self):
        tab = self.open_tab(helpers.plain(self.tmp / "a.pdf"))
        tab.view.run_edit(lambda: tab.doc.add_note(0, 5, 5, "n", (1, 0, 0)))
        with mock.patch.object(ui, "choose", lambda *a: ui.Button.Cancel):
            self.window.close_tab(tab)
            self.assertEqual(self.window.tabs.count(), 1)
            self.assertFalse(self.window.close())
        self.assertIn(self.window, self.controller.windows)


class SigningMode(unittest.TestCase):
    """커서 잠금·해제 경로. 실제 커서는 잠그지 않음."""

    def setUp(self):
        self.guard = mock.MagicMock()
        self.guard.lock.return_value = True
        self.guard.beat.return_value = True
        pad = mock.MagicMock(aspect=1.4, handle=1)
        for target, value in (
            ((sign_canvas.cursor_guard, "CursorGuard"), lambda: self.guard),
            ((sign_canvas.cursor_guard, "window_center"), lambda hwnd: (1, 1, 2, 2)),
            ((sign_canvas.touchpad_input, "find_touchpads"), lambda: [pad]),
            ((sign_canvas.touchpad_input, "TouchpadInput"), mock.MagicMock()),
        ):
            patcher = mock.patch.object(*target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        from PySide6.QtGui import QImage

        self.state = {"sign_width": 1, "sign_color": 0, "sign_keep": True}
        self.dialog = sign_canvas.SignDialog(None, QImage(), 3.0, self.state)
        self.dialog.show()
        self.dialog._start_touch()
        self.addCleanup(lambda: self.dialog.done(0))

    def cursor_is_free(self):
        return self.guard.unlock.called and QApplication.overrideCursor() is None

    def test_every_exit_frees_the_cursor(self):
        self.assertIsNotNone(QApplication.overrideCursor())
        QTest.keyClick(self.dialog, Qt.Key.Key_Escape)
        self.assertTrue(self.cursor_is_free())
        self.assertTrue(self.guard.close.called)

    def test_idle_for_30_seconds_releases(self):
        self.dialog._active_at -= 31
        self.dialog._tick()
        self.assertEqual(self.dialog._mode, "paused")
        self.assertTrue(self.cursor_is_free())

    def test_lost_lock_releases(self):
        self.guard.beat.return_value = False
        self.dialog._tick()
        self.assertTrue(self.cursor_is_free())

    def test_confirm_releases_and_returns_signature(self):
        dialog = self.dialog
        start = dialog._since + 1
        for i in range(10):
            dialog.handle_frame([Contact(0, 0.2 + i * 0.05, 0.4, True, True)], start + i * 0.01)
        dialog.handle_frame([], start + 0.2)
        QTest.keyClick(dialog, Qt.Key.Key_Return)
        self.assertTrue(self.cursor_is_free())
        self.assertEqual(len(dialog.signature["strokes"][0]), 10)

    def test_save_choice_starts_on_and_is_remembered(self):
        dialog = self.dialog
        self.assertTrue(dialog.keep.isChecked())
        dialog.canvas.begin(0.1, 0.5, 0.0)
        dialog.canvas.extend(0.5, 0.5, 0.1)
        dialog.keep.setChecked(False)
        dialog.confirm()
        self.assertFalse(self.state["sign_keep"])

    def test_finger_already_down_when_window_opens_is_ignored(self):
        dialog = self.dialog
        for i in range(60):
            dialog.handle_frame([Contact(0, 0.5, 0.5, True, True)], dialog._since + i * 0.01)
        dialog.handle_frame([], dialog._since + 1)
        self.assertEqual(dialog.canvas.strokes, [])


class Printing(helpers.TempCase):
    def test_page_ranges(self):
        self.assertEqual(printing.parse_pages("1-3, 5, 8-", 9), [0, 1, 2, 4, 7, 8])
        self.assertEqual(printing.parse_pages("", 2), [0, 1])
        for bad in ("0", "4-2", "10", "a", ","):
            with self.assertRaises(ValueError, msg=bad):
                printing.parse_pages(bad, 9)

    def test_print_to_pdf_file(self):
        doc = self.open(helpers.plain(self.tmp / "a.pdf"))
        printer = QPrinter()
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setResolution(150)
        printer.setOutputFileName(str(self.tmp / "out.pdf"))
        self.assertTrue(printing.print_pages(printer, doc, [0, 2], None, True))
        with mu.open(self.tmp / "out.pdf") as out:
            self.assertEqual(out.page_count, 2)
            pix = out[1].get_pixmap()
            self.assertIsNotNone(helpers.ink_box(pix.samples, pix.width, pix.height, pix.stride))


class Safety(unittest.TestCase):
    def links(self, kind, target, document="C:/docs/a.pdf"):
        window = mock.MagicMock()
        window._blocked = mock.MagicMock()
        tab = mock.MagicMock()
        tab.doc.path.parent = os.path.dirname(document)
        tab.doc.path.__str__.return_value = document
        with (
            mock.patch.object(main_window.ui, "confirm", lambda *a, **k: False),
            mock.patch.object(main_window.QDesktopServices, "openUrl") as opened,
        ):
            main_window.MainWindow.open_link(window, tab, Link((0, 0, 1, 1), kind, target=target))
        self.assertFalse(opened.called)
        return window._blocked.called

    def test_dangerous_links_are_blocked(self):
        for kind, target in (
            ("uri", "file:///C:/Windows/System32/calc.exe"),
            ("uri", "javascript:alert(1)"),
            ("uri", "ms-settings:privacy"),
            ("launch", "calc.exe"),
            ("file", "//server/share/x.pdf"),
            ("file", "\\\\server\\share\\x.pdf"),
        ):
            self.assertTrue(self.links(kind, target), target)

    def test_ordinary_links_ask_first(self):
        self.assertFalse(self.links("uri", "https://example.com/"))
        self.assertFalse(self.links("file", "other.pdf"))

    def test_registration_never_claims_the_default(self):
        entries = file_assoc.entries()
        self.assertNotIn((r"Software\Classes\.pdf", ""), [(k, n) for k, n, _ in entries])
        command = file_assoc.open_command()
        self.assertTrue(command.endswith('"%1"'))
        self.assertIn('FDPReader.pyw"', command)

    def test_tooltips_do_not_render_html(self):
        self.assertNotIn("<img", ui.plain_tooltip('<img src="//host/x">'))

    def test_acrobat_date_format(self):
        self.assertEqual(qt_date_format("yyyy-mm-dd"), "yyyy-MM-dd")


if __name__ == "__main__":
    unittest.main()
