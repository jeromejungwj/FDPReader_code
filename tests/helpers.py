"""테스트용 PDF 생성. 실제 사용자 문서·설정은 건드리지 않음."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import pymupdf as mu

MALGUN = r"C:\Windows\Fonts\malgun.ttf"


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fdp-test-"))
        self._old = os.environ.get("FDPREADER_DATA")
        os.environ["FDPREADER_DATA"] = str(self.tmp / "data")
        self._docs = []

    def tearDown(self):
        for doc in self._docs:
            if doc._doc is not None:
                doc.close()
        if self._old is None:
            os.environ.pop("FDPREADER_DATA", None)
        else:
            os.environ["FDPREADER_DATA"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def open(self, path, password=""):
        from core.document.document import Document

        doc = Document(path, password)
        self._docs.append(doc)
        return doc


def plain(path, pages=3, rotation=0, crop=False, **save):
    with mu.open() as doc:
        for i in range(pages):
            page = doc.new_page(width=400, height=500)
            page.insert_text((50, 80), f"Page {i + 1} hello world", fontsize=14)
            page.insert_text((50, 100), "second line of text", fontsize=14)
            if crop:
                page.set_cropbox(mu.Rect(20, 10, 390, 470))
            page.set_rotation(rotation)
        doc.save(path, **save)
    return path


def korean(path):
    with mu.open() as doc:
        page = doc.new_page(width=400, height=500)
        writer = mu.TextWriter(page.rect)
        font = mu.Font(fontfile=MALGUN)
        writer.append((50, 80), "개인정보 수집 동", font=font, fontsize=14)
        writer.append((50, 100), "의서에 서명합니다", font=font, fontsize=14)
        writer.write_text(page)
        doc.subset_fonts(fallback=False)
        doc.save(path)
    return path


def form(path):
    """글자·여러 줄·날짜·체크·라디오·드롭다운·목록·서명 필드."""
    with mu.open() as doc:
        page = doc.new_page(width=400, height=600)
        date = 'AFDate_FormatEx("yyyy-mm-dd");'
        specs = [
            ("name", mu.PDF_WIDGET_TYPE_TEXT, (40, 40, 300, 68), {}),
            ("memo", mu.PDF_WIDGET_TYPE_TEXT, (40, 80, 300, 150),
             {"field_flags": mu.PDF_TX_FIELD_IS_MULTILINE}),
            ("date", mu.PDF_WIDGET_TYPE_TEXT, (40, 160, 300, 188), {"script_format": date}),
            ("agree", mu.PDF_WIDGET_TYPE_CHECKBOX, (40, 200, 60, 220), {}),
            ("city", mu.PDF_WIDGET_TYPE_COMBOBOX, (40, 230, 300, 258),
             {"choice_values": ["서울", "부산", "Daegu"]}),
            ("items", mu.PDF_WIDGET_TYPE_LISTBOX, (40, 270, 300, 330),
             {"choice_values": ["one", "two", "셋"]}),
        ]
        for name, kind, rect, extra in specs:
            widget = mu.Widget()
            widget.field_name, widget.field_type, widget.rect = name, kind, mu.Rect(rect)
            for key, value in extra.items():
                setattr(widget, key, value)
            page.add_widget(widget)

        root = doc.get_new_xref()
        kids = []
        for i, state in enumerate(("A", "B", "C")):
            x = 40 + i * 50
            xref = doc.get_new_xref()
            on, off = doc.get_new_xref(), doc.get_new_xref()
            for ap, content in ((on, b"0 g 5 5 10 10 re f"), (off, b"0 G 1 1 18 18 re S")):
                doc.update_object(ap, "<</Type/XObject/Subtype/Form/BBox[0 0 20 20]>>")
                doc.update_stream(ap, content, new=True)
            doc.update_object(
                xref,
                f"<</Type/Annot/Subtype/Widget/Rect[{x} 240 {x + 20} 260]/Parent {root} 0 R"
                f"/F 4/AS/Off/AP<</N<</{state} {on} 0 R/Off {off} 0 R>>>>>>",
            )
            kids.append(xref)
        doc.update_object(
            root,
            f"<</FT/Btn/Ff {1 << 15}/T(choice)/V/Off"
            f"/Kids[{' '.join(f'{k} 0 R' for k in kids)}]>>",
        )
        sig = doc.get_new_xref()
        doc.update_object(
            sig, "<</Type/Annot/Subtype/Widget/FT/Sig/T(sign)/Rect[40 40 300 110]/F 4>>"
        )
        _, annots = doc.xref_get_key(page.xref, "Annots")
        extra = " ".join(f"{x} 0 R" for x in (*kids, sig))
        doc.xref_set_key(page.xref, "Annots", f"[{annots[1:-1]} {extra}]")
        catalog = doc.pdf_catalog()
        kind, value = doc.xref_get_key(catalog, "AcroForm/Fields")
        items = value[1:-1] if kind == "array" else ""
        if kind == "xref":
            items = doc.xref_object(int(value.split()[0]), compressed=True).strip()[1:-1]
        doc.xref_set_key(catalog, "AcroForm/Fields", f"[{items} {root} 0 R {sig} 0 R]")
        doc.save(path)
    return path


def ink_box(samples, width, height, stride, near=(0, 0, 0), tolerance=90):
    xs, ys = [], []
    for y in range(height):
        row = samples[y * stride : y * stride + width * 3]
        for x in range(width):
            if all(abs(row[3 * x + i] - near[i]) <= tolerance for i in range(3)):
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1) if xs else None
