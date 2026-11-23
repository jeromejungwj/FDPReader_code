import os
import random
import unittest

import pymupdf as mu

from core.document.document import sweep_stale_copies
from core.document.models import DocumentError, Graphic, PasswordRequired
from core.document.text import compile_query
from tests import helpers

RED = (1.0, 0.0, 0.0)
BLUE = (0.0, 0.0, 1.0)


def l_shape(color=BLUE):
    # 왼쪽 위 모서리에 꺾인 부분이 있는 ㄱ 모양: 방향이 틀리면 빈 모서리가 달라짐
    return Graphic(
        "lines", (0, 0, 2, 1), color,
        segments=((0.05, 0.05, 1.95, 0.05, 0.1), (0.05, 0.05, 0.05, 0.95, 0.1)),
    )


class EditHistory(helpers.TempCase):
    def test_random_edit_undo_redo_save_never_corrupts(self):
        kinds = {
            "plain": {},
            "objstm": {"use_objstms": 1, "garbage": 3, "deflate": True},
            "encrypted": {
                "encryption": mu.PDF_ENCRYPT_AES_256, "user_pw": "u", "owner_pw": "o",
            },
        }
        for name, save in kinds.items():
            with self.subTest(name):
                path = helpers.plain(self.tmp / f"{name}.pdf", **save)
                original = path.read_bytes()
                doc = self.open(path, "u" if name == "encrypted" else "")
                self.assertFalse(doc.rebuilt)
                rng = random.Random(3)
                count, past, future = 0, [], []
                for _ in range(90):
                    roll = rng.random()
                    if roll < 0.55 or not past:
                        doc.add_note(rng.randrange(3), 20, 20, "메모", RED)
                        past.append(count)
                        count, future = count + 1, []
                    elif roll < 0.75:
                        self.assertTrue(doc.undo())
                        future.append(count)
                        count = past.pop()
                    elif roll < 0.88 and future:
                        self.assertTrue(doc.redo())
                        past.append(count)
                        count = future.pop()
                    else:
                        doc.save()
                        self.assertFalse(doc.dirty)
                    self.assertEqual(sum(len(doc.annots(p)) for p in range(3)), count)
                doc.save()
                saved = path.read_bytes()
                self.assertTrue(saved.startswith(original), "원본 바이트가 보존돼야 함")
                check = mu.open(path)
                if name == "encrypted":
                    self.assertTrue(check.needs_pass)
                    self.assertTrue(check.authenticate("u"))
                self.assertFalse(check.is_repaired)
                self.assertEqual(check.page_count, 3)
                self.assertEqual(sum(len(list(p.annots())) for p in check), count)
                check.close()

    def test_failed_edit_leaves_document_unchanged(self):
        doc = self.open(helpers.plain(self.tmp / "a.pdf"))
        before = doc._work.read_bytes()

        def explode(pdf):
            pdf[0].add_text_annot((5, 5), "half done")
            raise RuntimeError("boom")

        with self.assertLogs("core.document.document"), self.assertRaises(DocumentError):
            doc._edit("annotate", [0], explode)
        self.assertEqual(doc._work.read_bytes(), before)
        self.assertEqual(doc.annots(0), [])
        self.assertFalse(doc.dirty)

    def test_undo_back_to_saved_state_is_clean(self):
        doc = self.open(helpers.plain(self.tmp / "a.pdf"))
        doc.add_note(0, 5, 5, "a", RED)
        doc.save()
        doc.add_note(0, 5, 5, "b", RED)
        doc.undo()
        self.assertFalse(doc.dirty)
        doc.undo()
        self.assertTrue(doc.dirty)

    def test_original_is_untouched_until_save_and_external_change_is_seen(self):
        path = helpers.plain(self.tmp / "a.pdf")
        original = path.read_bytes()
        doc = self.open(path)
        doc.add_note(0, 5, 5, "a", RED)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(doc.changed_on_disk())
        path.write_bytes(original + b"\n% changed elsewhere\n")
        self.assertTrue(doc.changed_on_disk())

    def test_save_as_switches_path(self):
        path = helpers.plain(self.tmp / "a.pdf")
        original = path.read_bytes()
        doc = self.open(path)
        doc.add_note(0, 5, 5, "a", RED)
        doc.save(self.tmp / "새 이름.pdf")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(doc.path.name, "새 이름.pdf")
        self.assertEqual(list(self.tmp.glob(".fdp-*")), [])


class Opening(helpers.TempCase):
    def test_password(self):
        path = helpers.plain(
            self.tmp / "p.pdf", encryption=mu.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o"
        )
        with self.assertRaises(PasswordRequired) as first:
            self.open(path)
        self.assertFalse(first.exception.wrong)
        with self.assertRaises(PasswordRequired) as second:
            self.open(path, "x")
        self.assertTrue(second.exception.wrong)
        self.assertEqual(self.open(path, "u").page_count, 3)

    def test_restrictions_are_enforced(self):
        path = helpers.plain(
            self.tmp / "r.pdf", encryption=mu.PDF_ENCRYPT_AES_256, owner_pw="o",
            permissions=mu.PDF_PERM_ACCESSIBILITY,
        )
        doc = self.open(path)
        for what in ("copy", "print", "annotate", "form"):
            self.assertFalse(doc.allows(what), what)
        with self.assertRaises(DocumentError):
            doc.add_note(0, 5, 5, "a", RED)
        with self.assertRaises(DocumentError):
            doc.printer(True)

    def test_garbage_is_reported_and_leaves_no_copy(self):
        path = self.tmp / "bad.pdf"
        for data in (b"", b"not a pdf at all", b"%PDF-1.7\n1 0 obj <<"):
            path.write_bytes(data)
            with self.assertRaises(DocumentError):
                self.open(path)
        self.assertEqual(list((self.tmp / "data" / "work").iterdir()), [])

    def test_damaged_file_is_rebuilt_in_the_copy_only(self):
        path = helpers.plain(self.tmp / "d.pdf")
        broken = path.read_bytes().replace(b"startxref", b"startxxxx")
        path.write_bytes(broken)
        doc = self.open(path)
        self.assertEqual(doc.page_count, 3)
        self.assertTrue(doc.rebuilt)
        doc.add_note(0, 5, 5, "a", RED)
        self.assertEqual(path.read_bytes(), broken)

    def test_read_only_original_can_still_be_edited(self):
        path = helpers.plain(self.tmp / "ro.pdf")
        os.chmod(path, 0o400)
        try:
            doc = self.open(path)
            doc.add_note(0, 5, 5, "a", RED)
            doc.save(self.tmp / "copy.pdf")
        finally:
            os.chmod(path, 0o600)

    def test_sweep_keeps_open_documents_and_removes_dead_ones(self):
        doc = self.open(helpers.plain(self.tmp / "a.pdf"))
        dead = self.tmp / "data" / "work" / "doc-dead"
        dead.mkdir()
        (dead / "alive").touch()
        (dead / "work.pdf").write_bytes(b"x")
        sweep_stale_copies()
        self.assertFalse(dead.exists())
        self.assertTrue(doc._work.exists())


class Geometry(helpers.TempCase):
    def test_annots_land_where_asked_on_rotated_cropped_pages(self):
        for rotation in (0, 90, 180, 270):
            for view in (0, 90, 180, 270):
                with self.subTest(rotation=rotation, view=view):
                    path = helpers.plain(
                        self.tmp / f"g{rotation}{view}.pdf", 1, rotation, crop=True
                    )
                    doc = self.open(path)
                    rect = (150, 200, 250, 250) if view % 180 == 0 else (150, 200, 200, 300)
                    xref = doc.add_signature(0, rect, l_shape(), view)
                    found = next(a for a in doc.annots(0) if a.xref == xref)
                    for got, want in zip(found.rect, rect):
                        self.assertAlmostEqual(got, want, delta=0.05)

                    _, _, w, h, stride, data = doc.render(0, 1.0)
                    box = helpers.ink_box(data, w, h, stride, near=(0, 0, 255))
                    for got, want in zip(box, rect):
                        self.assertAlmostEqual(got, want, delta=3)

                    def blue(x, y):
                        at = y * stride + x * 3
                        return data[at + 2] > 180 and data[at] < 90

                    x0, y0, x1, y1 = rect
                    corners = [(x0, y0), (x1 - 8, y0), (x1 - 8, y1 - 8), (x0, y1 - 8)]
                    hits = [
                        any(blue(x, y) for x in range(cx, cx + 8) for y in range(cy, cy + 8))
                        for cx, cy in corners
                    ]
                    # 보기 회전만큼 반대로 돌린 화면 모서리에서 "오른쪽 아래"만 비어 있어야 함
                    empty = (2 - view // 90) % 4
                    self.assertEqual(hits, [i != empty for i in range(4)])
                    doc.close()

    def test_text_boxes_match_rendered_ink_on_rotated_pages(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation):
                doc = self.open(helpers.plain(self.tmp / f"t{rotation}.pdf", 1, rotation, True))
                page = doc.text(0)
                boxes = [b for b in page.boxes if b]
                _, _, w, h, stride, data = doc.render(0, 1.0)
                ink = helpers.ink_box(data, w, h, stride)
                self.assertLessEqual(min(b[0] for b in boxes), ink[0] + 1.5)
                self.assertLessEqual(min(b[1] for b in boxes), ink[1] + 1.5)
                self.assertGreaterEqual(max(b[2] for b in boxes), ink[2] - 1.5)
                self.assertGreaterEqual(max(b[3] for b in boxes), ink[3] - 1.5)

    def test_ink_signature_follows_move(self):
        doc = self.open(helpers.plain(self.tmp / "ink.pdf", 1, 90, True))
        doc.add_signature(0, (50, 50, 150, 100), l_shape(), as_ink=True)
        annot = doc.annots(0)[0]
        self.assertEqual(annot.kind, "Ink")
        doc.move_annot(annot, (100, 120, 300, 220))
        page = doc._doc[0]
        values = page.load_annot(annot.xref).vertices
        rect = doc._doc.xref_get_key(annot.xref, "Rect")[1].strip("[]").split()
        x0, y0, x1, y1 = map(float, rect)
        raw = doc._doc.xref_get_key(annot.xref, "InkList")[1].replace("[", " ").replace("]", " ")
        points = list(map(float, raw.split()))
        self.assertTrue(values)
        self.assertTrue(all(x0 - 0.1 <= x <= x1 + 0.1 for x in points[::2]))
        self.assertTrue(all(y0 - 0.1 <= y <= y1 + 0.1 for y in points[1::2]))

    def test_duplicate_lands_on_other_page_and_moves_alone(self):
        path = helpers.plain(self.tmp / "dup.pdf", 2)
        doc = self.open(path)
        doc.add_signature(0, (50, 50, 150, 100), l_shape(), as_ink=True)
        doc.add_signature(0, (50, 200, 150, 250), l_shape())
        originals = [a.rect for a in doc.annots(0)]
        target = (200, 300, 300, 350)
        for source in doc.annots(0):
            doc.duplicate_annot(source, 1, target)
        copies = doc.annots(1)
        self.assertEqual([a.kind for a in copies], ["Ink", "Stamp"])
        for copy in copies:
            for got, want in zip(copy.rect, target):
                self.assertAlmostEqual(got, want, delta=0.05)
        _, _, w, h, stride, data = doc.render(1, 1.0)
        for got, want in zip(helpers.ink_box(data, w, h, stride, near=(0, 0, 255)), target):
            self.assertAlmostEqual(got, want, delta=3)

        doc.move_annot(copies[0], (10, 10, 110, 60))
        self.assertEqual([a.rect for a in doc.annots(0)], originals)  # 원본은 그대로
        doc.save()
        with mu.open(path) as saved:
            names = [a.info["id"] for page in saved for a in page.annots()]
        self.assertEqual(len(names), 4)
        self.assertEqual(len(set(names)), 4)
        self.assertTrue(all(name.startswith("fdp-") for name in names))

    def test_markup_covers_selected_text(self):
        for rotation in (0, 90):
            doc = self.open(helpers.plain(self.tmp / f"m{rotation}.pdf", 1, rotation, True))
            page = doc.text(0)
            rects = page.rects(0, 8)
            doc.add_markup("Highlight", [(0, page.quads(0, 8))], (1, 1, 0))
            _, _, w, h, stride, data = doc.render(0, 1.0)
            box = helpers.ink_box(data, w, h, stride, near=(255, 255, 0))
            for got, want in zip(box, rects[0]):
                self.assertAlmostEqual(got, want, delta=2)


class CrossReaderRegressions(helpers.TempCase):
    """PDFium(Chrome·Edge) 교차 비교에서 나온 버그들."""

    def test_note_is_drawn_where_it_is_clickable_on_rotated_pages(self):
        for rotation in (0, 90, 180, 270):
            for view in (0, 90):
                with self.subTest(rotation=rotation, view=view):
                    path = helpers.plain(self.tmp / f"n{rotation}{view}.pdf", 1, rotation, True)
                    doc = self.open(path)
                    doc.add_note(0, 200, 250, "메모", RED, view)
                    note = doc.annots(0)[0]
                    self.assertEqual(note.kind, "Text")
                    _, _, w, h, stride, data = doc.render(0, 1.0)
                    box = helpers.ink_box(data, w, h, stride, near=(255, 0, 0))
                    x0, y0, x1, y1 = note.rect
                    self.assertTrue(x0 - 1 <= box[0] and box[2] <= x1 + 1, (box, note.rect))
                    self.assertTrue(y0 - 1 <= box[1] and box[3] <= y1 + 1, (box, note.rect))
                    self.assertAlmostEqual(x0, 200, delta=0.1)
                    self.assertAlmostEqual(y0, 250, delta=0.1)
                    doc.close()

    def test_third_party_note_moves_to_where_dropped_on_rotated_page(self):
        path = self.tmp / "foreign.pdf"
        with mu.open() as pdf:
            page = pdf.new_page(width=400, height=500)
            page.add_text_annot((100, 100), "other app")
            page.set_rotation(90)
            pdf.save(path)
        doc = self.open(path)
        doc.move_annot(doc.annots(0)[0], (150, 200, 170, 220))
        x0, y0, _, _ = doc.annots(0)[0].rect
        self.assertAlmostEqual(x0, 150, delta=0.1)
        self.assertAlmostEqual(y0, 200, delta=0.1)

    def test_underline_follows_text_direction(self):
        # 쪽을 돌리면 밑줄은 글자의 "아래" = 화면의 왼·위·오른쪽으로 감
        for rotation, side in ((0, "bottom"), (90, "left"), (180, "top"), (270, "right")):
            with self.subTest(rotation):
                doc = self.open(helpers.plain(self.tmp / f"u{rotation}.pdf", 1, rotation))
                page = doc.text(0)
                x0, y0, x1, y1 = page.rects(0, 8)[0]
                doc.add_markup("Underline", [(0, page.quads(0, 8))], RED)
                _, _, w, h, stride, data = doc.render(0, 1.0)
                ax, ay, bx, by = helpers.ink_box(data, w, h, stride, near=(255, 0, 0), tolerance=120)
                cx, cy = (ax + bx) / 2, (ay + by) / 2
                gap = {"bottom": y1 - cy, "top": cy - y0, "left": cx - x0, "right": x1 - cx}
                self.assertLess(abs(gap[side]), 4)
                length = bx - ax if rotation % 180 == 0 else by - ay
                across = x1 - x0 if rotation % 180 == 0 else y1 - y0
                self.assertGreater(length, across * 0.8)

    def test_engine_sign_tag_never_reaches_screen_print_or_export(self):
        doc = self.open(helpers.form(self.tmp / "form.pdf"))
        tag = (235, 80, 50)

        def tagged(result):
            _, _, w, h, stride, data = result
            return helpers.ink_box(data, w, h, stride, near=tag, tolerance=50) is not None

        self.assertFalse(tagged(doc.render(0, 1.0)))
        printer = doc.printer(True)
        self.assertFalse(tagged(printer.render(0, 1.0)))
        printer.close()
        doc.export_flattened(self.tmp / "flat.pdf")
        with mu.open(self.tmp / "flat.pdf") as flat:
            pix = flat[0].get_pixmap()
            self.assertFalse(tagged((0, 0, pix.width, pix.height, pix.stride, pix.samples)))
        # 사본에서만 바꾸므로 문서에는 서명 필드가 그대로 있어야 함
        doc.add_note(0, 5, 5, "edit after render", RED)
        self.assertIn("signature", [f.kind for f in doc.fields(0)])

    def test_destinations_use_top_left_coordinates(self):
        path = self.tmp / "dest.pdf"
        with mu.open() as pdf:
            pdf.new_page(width=400, height=500)
            pdf.new_page(width=400, height=500)
            first, second = pdf[0], pdf[1]
            link = pdf.get_new_xref()
            goal = f"[{second.xref} 0 R/XYZ 0 350 0]"
            pdf.update_object(
                link, f"<</Type/Annot/Subtype/Link/Rect[50 400 150 430]/Dest{goal}>>"
            )
            pdf.xref_set_key(first.xref, "Annots", f"[{link} 0 R]")
            item, root = pdf.get_new_xref(), pdf.get_new_xref()
            pdf.update_object(item, f"<</Title(two)/Parent {root} 0 R/Dest{goal}>>")
            pdf.update_object(root, f"<</Type/Outlines/First {item} 0 R/Last {item} 0 R/Count 1>>")
            pdf.xref_set_key(pdf.pdf_catalog(), "Outlines", f"{root} 0 R")
            pdf.save(path)
        doc = self.open(path)
        self.assertAlmostEqual(doc.links(0)[0].y, 150, delta=1)
        self.assertAlmostEqual(doc.toc()[0].y, 150, delta=1)


class TextBoxes(helpers.TempCase):
    def test_korean_is_embedded_and_small(self):
        path = helpers.plain(self.tmp / "k.pdf")
        doc = self.open(path)
        base = path.stat().st_size
        doc.add_text(0, (50, 150, 350, 190), "홍길동 2026-11-23", 14)
        self.assertEqual(doc.annots(0)[0].text, "홍길동 2026-11-23")
        doc.save()
        self.assertLess(path.stat().st_size - base, 200_000)
        with mu.open(path) as check:
            objects = [check.xref_object(i) for i in range(1, check.xref_length())]
        self.assertTrue(any("FontFile2" in o for o in objects), "글꼴이 포함돼야 함")

    def test_edit_and_resize(self):
        doc = self.open(helpers.plain(self.tmp / "a.pdf"))
        doc.add_text(0, (50, 150, 350, 190), "before", 14)
        doc.set_annot_text(doc.annots(0)[0], "바뀐 글", (50, 150, 350, 200))
        self.assertEqual(doc.annots(0)[0].text, "바뀐 글")
        doc.move_annot(doc.annots(0)[0], (50, 150, 120, 260))
        self.assertAlmostEqual(doc.annots(0)[0].rect[2], 120, delta=0.1)
        doc.delete_annot(doc.annots(0)[0])
        self.assertEqual(doc.annots(0), [])


class Forms(helpers.TempCase):
    def fields(self, doc):
        found = {}
        for field in doc.fields(0):
            found.setdefault(field.name, []).append(field)
        return found

    def test_fill_every_kind_then_reopen_and_flatten(self):
        path = helpers.form(self.tmp / "form.pdf")
        doc = self.open(path)
        f = self.fields(doc)
        self.assertEqual(f["date"][0].date_format, "yyyy-mm-dd")
        self.assertTrue(f["memo"][0].multiline)
        self.assertEqual(f["sign"][0].kind, "signature")
        self.assertFalse(f["sign"][0].value)

        doc.set_field(f["name"][0], "홍길동")
        doc.set_field(f["memo"][0], "첫 줄\n둘째 줄")
        doc.set_field(f["agree"][0], True)
        doc.set_field(f["city"][0], "부산")
        doc.set_field(f["items"][0], ["셋"])
        doc.set_field(self.fields(doc)["choice"][1], True)
        doc.save()

        again = self.open(path)
        f = self.fields(again)
        self.assertEqual(f["name"][0].value, "홍길동")
        self.assertEqual(f["memo"][0].value.replace("\r", ""), "첫 줄\n둘째 줄")
        self.assertTrue(f["agree"][0].value)
        self.assertEqual(f["city"][0].value, "부산")
        self.assertEqual(f["items"][0].value, ["셋"])
        self.assertEqual([r.value for r in f["choice"]], [False, True, False])

        out = self.tmp / "flat.pdf"
        again.export_flattened(out)
        with mu.open(out) as flat:
            self.assertEqual(list(flat[0].widgets()), [])
            self.assertEqual(list(flat[0].annots()), [])
            self.assertIn("홍길동", flat[0].get_text())
            self.assertIn("부산", flat[0].get_text())

    def test_need_appearances_forms_get_our_appearances(self):
        path = helpers.form(self.tmp / "raw.pdf")
        flagged = self.tmp / "flagged.pdf"
        with mu.open(path) as pdf:
            # 다른 프로그램이 값만 넣고 그림은 리더에 맡긴 양식
            for widget in pdf[0].widgets():
                if widget.field_name == "memo":
                    pdf.xref_set_key(widget.xref, "V", "<feffc774bbf8>")
            pdf.xref_set_key(pdf.pdf_catalog(), "AcroForm/NeedAppearances", "true")
            pdf.save(flagged)
        doc = self.open(flagged)
        doc.fields(0)
        doc.render(0, 1.0)
        doc.set_field(self.fields(doc)["name"][0], "홍길동")
        pdf = doc._doc
        self.assertEqual(
            pdf.xref_get_key(pdf.pdf_catalog(), "AcroForm/NeedAppearances")[1], "false"
        )
        for name in ("name", "memo"):
            ap = pdf.xref_get_key(self.fields(doc)[name][0].xref, "AP/N")[1]
            self.assertIn(b"EMC", pdf.xref_stream(int(ap.split()[0])))
        radio = self.fields(doc)["choice"][0].xref
        off = pdf.xref_get_key(radio, "AP/N/Off")[1]
        self.assertIn(b"re S", pdf.xref_stream(int(off.split()[0])), "라디오 원래 모양이 남아야 함")

    def test_adobe_engine_compatibility_keys(self):
        doc = self.open(helpers.form(self.tmp / "form.pdf"))
        doc.set_field(self.fields(doc)["name"][0], "홍")
        field = self.fields(doc)["name"][0]
        self.assertNotIn(" 0 Tf", doc._doc.xref_get_key(field.xref, "DA")[1])
        self.assertEqual(field.font_size, 0.0, "다음 입력 때 다시 자동으로 맞춰야 함")

        doc.set_field(self.fields(doc)["agree"][0], True)
        box = self.fields(doc)["agree"][0]
        self.assertTrue(box.value)
        self.assertEqual(doc._doc.xref_get_key(box.xref, "MK/CA")[1], "4")
        kind, state = doc._doc.xref_get_key(box.xref, "AP/N/Yes")
        stream = doc._doc.xref_stream(int(state.split()[0]))
        self.assertNotIn(b"Tf", stream)

        doc.add_signature(0, (50, 500, 150, 550), l_shape())
        stamp = next(a for a in doc.annots(0) if a.kind == "Stamp")
        self.assertEqual(stamp.text, "")

    def test_checkbox_can_be_cleared_and_undone(self):
        doc = self.open(helpers.form(self.tmp / "form.pdf"))
        doc.set_field(self.fields(doc)["agree"][0], True)
        doc.set_field(self.fields(doc)["agree"][0], False)
        self.assertFalse(self.fields(doc)["agree"][0].value)
        doc.undo()
        self.assertTrue(self.fields(doc)["agree"][0].value)

    def test_flatten_refuses_to_replace_original_and_keeps_password(self):
        path = helpers.plain(
            self.tmp / "p.pdf", encryption=mu.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o"
        )
        doc = self.open(path, "o")
        with self.assertRaises(DocumentError):
            doc.export_flattened(path)
        doc.export_flattened(self.tmp / "flat.pdf")
        with mu.open(self.tmp / "flat.pdf") as flat:
            self.assertTrue(flat.needs_pass)
            self.assertTrue(flat.authenticate("u"))


class Reading(helpers.TempCase):
    def test_search_options(self):
        page = self.open(helpers.plain(self.tmp / "a.pdf")).text(0)
        count = lambda *q: len(list(page.find(compile_query(*q))))
        self.assertEqual(count("HELLO", False, False), 1)
        self.assertEqual(count("HELLO", True, False), 0)
        self.assertEqual(count("hell", False, True), 0)
        self.assertEqual(count("hello", False, True), 1)
        self.assertEqual(count("world second", False, False), 1)

    def test_search_finds_korean_word_broken_across_lines(self):
        page = self.open(helpers.korean(self.tmp / "k.pdf")).text(0)
        self.assertEqual(len(list(page.find(compile_query("동의서", False, False)))), 1)

    def test_copy_joins_wrapped_lines_and_selection(self):
        page = self.open(helpers.plain(self.tmp / "a.pdf")).text(0)
        copied = page.copy_text(0, len(page.text))
        self.assertIn("Page 1 hello world", copied)
        self.assertIn("second line of text", copied)
        at = page.text.index("hello")
        self.assertEqual(page.word(at + 2), (at, at + 5))
        self.assertEqual(page.text[slice(*page.line(at))], "Page 1 hello world")

    def test_links_on_rotated_page(self):
        path = self.tmp / "l.pdf"
        with mu.open() as pdf:
            page = pdf.new_page(width=400, height=500)
            pdf.new_page()
            page = pdf[0]
            page.insert_link({"kind": mu.LINK_URI, "from": mu.Rect(50, 60, 150, 90),
                              "uri": "https://example.com/"})
            page.insert_link({"kind": mu.LINK_GOTO, "from": mu.Rect(50, 100, 150, 130), "page": 1})
            page.set_rotation(90)
            pdf.set_toc([[1, "one", 1], [2, "two", 2]])
            pdf.save(path)
        doc = self.open(path)
        links = {link.kind: link for link in doc.links(0)}
        self.assertEqual(links["page"].page, 1)
        for got, want in zip(links["uri"].rect, (410, 50, 440, 150)):
            self.assertAlmostEqual(got, want, delta=0.5)
        self.assertEqual([(t.level, t.title, t.page) for t in doc.toc()],
                         [(1, "one", 0), (2, "two", 1)])

    def test_dark_mode_inverts_text_and_keeps_pictures(self):
        path = self.tmp / "img.pdf"
        picture = mu.Pixmap(mu.csRGB, mu.IRect(0, 0, 40, 40), False)
        picture.set_rect(picture.irect, (200, 30, 30))
        for rotation in (0, 90):
            with mu.open() as pdf:
                page = pdf.new_page(width=200, height=300)
                page.insert_image(mu.Rect(100, 200, 140, 240), pixmap=picture)
                page.set_rotation(rotation)
                pdf.save(path)
            doc = self.open(path)
            x, y = (120, 220) if rotation == 0 else (300 - 220, 120)
            _, _, _, _, stride, data = doc.render(0, 1.0, theme="dark")
            self.assertLess(data[3 * 5 + 5 * stride], 60)  # 바탕은 어둡게
            at = y * stride + x * 3
            self.assertAlmostEqual(data[at], 200, delta=4)
            self.assertAlmostEqual(data[at + 1], 30, delta=4)
            doc.close()

    def test_print_copy_can_drop_annots_but_keeps_form_values(self):
        doc = self.open(helpers.form(self.tmp / "form.pdf"))
        name = next(f for f in doc.fields(0) if f.name == "name")
        doc.set_field(name, "KEEP ME")
        doc.add_signature(0, (100, 500, 300, 580), l_shape())
        with_annots, without = doc.printer(True), doc.printer(False)
        try:
            _, _, w, h, stride, data = without.render(0, 1.0)
            self.assertIsNone(helpers.ink_box(data, w, h, stride, near=(0, 0, 255)))
            self.assertIsNotNone(helpers.ink_box(data[: 68 * stride], w, 68, stride))
            _, _, w, h, stride, data = with_annots.render(0, 1.0)
            self.assertIsNotNone(helpers.ink_box(data, w, h, stride, near=(0, 0, 255)))
        finally:
            with_annots.close()
            without.close()


if __name__ == "__main__":
    unittest.main()
