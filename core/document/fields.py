"""AcroForm 양식 읽기·입력. 스크립트는 실행하지 않고 날짜 서식 문자열만 읽음."""

from __future__ import annotations

import re
from dataclasses import replace

import pymupdf as mu

from . import appearance, pdfobj
from .engine import page_matrix
from .models import DocumentError, Field

READ_ONLY = 1
MULTILINE = 1 << 12
PASSWORD = 1 << 13
EDITABLE = 1 << 18
MULTI_SELECT = 1 << 21
COMB = 1 << 24
RADIOS_IN_UNISON = 1 << 25
_HIDDEN, _NO_VIEW = 2, 32

_KINDS = {
    mu.PDF_WIDGET_TYPE_TEXT: "text",
    mu.PDF_WIDGET_TYPE_CHECKBOX: "check",
    mu.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",
    mu.PDF_WIDGET_TYPE_COMBOBOX: "combo",
    mu.PDF_WIDGET_TYPE_LISTBOX: "list",
    mu.PDF_WIDGET_TYPE_SIGNATURE: "signature",
}
_DATE = re.compile(r"AFDate_(?:Format|Keystroke)(?:Ex)?\s*\(\s*[\"']?([^\"')]*)")
_SIZE = re.compile(r"[\d.]+(\s+Tf)")
AUTO_SIZE = "FDPAutoSize"  # 원래 자동 크기였다는 표시 (다음 입력 때 다시 맞춤)
_STATE = re.compile(r"/([^\s/<>\[\]()]+)\s*(?=\d+\s+\d+\s+R|<<)")


def _int(doc, xref: int, key: str) -> int:
    kind, value = pdfobj.inherited(doc, xref, key)
    if kind == "xref":
        value = pdfobj.body(doc, (kind, value))
    try:
        return int(value)
    except ValueError:
        return 0


def _owner(doc, xref: int) -> int:
    """위젯이 속한 필드 (이름 /T 를 가진 객체)."""
    current = xref
    for _ in range(32):
        if pdfobj.get(doc, current, "T")[0] != "null":
            return current
        parent = pdfobj.get(doc, current, "Parent")
        if parent[0] != "xref":
            break
        current = int(parent[1].split()[0])
    return xref


def _widgets(doc, owner: int) -> list[int]:
    kids = pdfobj.refs(doc, pdfobj.get(doc, owner, "Kids"))
    return [k for k in kids if pdfobj.get(doc, k, "T")[0] == "null"] or [owner]


def widget_count(doc, xref: int) -> int:
    return len(_widgets(doc, _owner(doc, xref)))


def _options(widget: mu.Widget) -> tuple[tuple[str, str], ...]:
    out = []
    for item in widget.choice_values or ():
        pair = (item, item) if isinstance(item, str) else (str(item[0]), str(item[1]))
        out.append(pair)
    return tuple(out)


def _date_format(widget: mu.Widget) -> str:
    for script in (widget.script_format, widget.script_stroke):
        match = _DATE.search(script or "")
        if match:
            fmt = match.group(1).strip()
            return fmt if re.search("[ymd]", fmt) else "yyyy-mm-dd"
    return ""


def read(doc: mu.Document, pno: int) -> list[Field]:
    page = doc[pno]
    matrix = page_matrix(page)
    found = []
    for widget in page.widgets():
        kind = _KINDS.get(widget.field_type)
        box = pdfobj.rect(doc, widget.xref)
        if not kind or box is None:
            continue
        if _int(doc, widget.xref, "F") & (_HIDDEN | _NO_VIEW):
            continue
        flags = _int(doc, widget.xref, "Ff")
        options = _options(widget) if kind in ("combo", "list") else ()
        if kind in ("check", "radio"):
            value = pdfobj.get(doc, widget.xref, "AS")[1] not in ("/Off", "null")
        elif kind == "signature":
            value = pdfobj.inherited(doc, widget.xref, "V")[0] != "null"
        elif kind == "list":
            raw = pdfobj.inherited(doc, widget.xref, "V")
            if raw[0] in ("array", "xref"):
                value = _string_array(doc, _owner(doc, widget.xref))
            else:
                value = [raw[1]] if raw[0] == "string" else []
        else:
            value = str(widget.field_value or "")
        found.append(
            Field(
                xref=widget.xref,
                pno=pno,
                kind=kind,
                rect=tuple((box * matrix).normalize()),
                name=widget.field_label or widget.field_name or "",
                value=value,
                read_only=bool(flags & READ_ONLY),
                multiline=kind == "text" and bool(flags & MULTILINE),
                password=kind == "text" and bool(flags & PASSWORD),
                editable=kind == "combo" and bool(flags & EDITABLE),
                multi=kind == "list" and bool(flags & MULTI_SELECT),
                max_len=_int(doc, widget.xref, "MaxLen") if kind == "text" else 0,
                options=options,
                date_format=_date_format(widget) if kind == "text" else "",
                font_size=_font_size(doc, widget),
            )
        )
    return found


def _font_size(doc, widget: mu.Widget) -> float:
    if pdfobj.get(doc, widget.xref, AUTO_SIZE)[1] == "true":
        return 0.0
    return float(widget.text_fontsize or 0)


def _pin_size(doc, xref: int, size: float, color) -> None:
    """크기가 자동(0)이면 Edge(Adobe 엔진)가 표시 스트림을 버리고 제 글꼴로 다시 그림."""
    kind, da = pdfobj.inherited(doc, xref, "DA")
    amount = pdfobj.numbers(size)
    if kind == "string" and _SIZE.search(da) and not set("()\\") & set(da):
        da = _SIZE.sub(lambda m: amount + m.group(1), da)
    else:
        da = f"{pdfobj.numbers(*color)} rg /Helv {amount} Tf"
    doc.xref_set_key(xref, "DA", f"({da})")
    doc.xref_set_key(xref, AUTO_SIZE, "true")


def _string_array(doc, owner: int) -> list[str]:
    value = mu.mupdf.pdf_dict_gets(
        mu.mupdf.pdf_load_object(mu._as_pdf_document(doc), owner), "V"
    )
    return [
        mu.mupdf.pdf_to_text_string(mu.mupdf.pdf_array_get(value, i))
        for i in range(mu.mupdf.pdf_array_len(value))
    ]


def _rgb(values) -> tuple[float, float, float] | None:
    v = list(values or ())
    if len(v) == 1:
        return v[0], v[0], v[0]
    if len(v) == 3:
        return v[0], v[1], v[2]
    if len(v) == 4:
        c, m, y, k = v
        return (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
    return None


def _look(doc, xref: int):
    """(폭, 높이, 위젯 회전, (배경색, 테두리색))."""
    box = pdfobj.rect(doc, xref)
    if box is None or box.is_empty:
        return None
    kind, value = pdfobj.get(doc, xref, "MK/R")
    rotation = int(value) % 360 if kind == "int" else 0
    if rotation % 90:
        rotation = 0
    decor = tuple(
        _rgb(pdfobj.number_list(doc, pdfobj.get(doc, xref, key))) for key in ("MK/BG", "MK/BC")
    )
    return (*appearance.upright_size(box, rotation), rotation, decor)


def _text_color(doc, pno: int, xref: int):
    for widget in doc[pno].widgets():
        if widget.xref == xref:
            return _rgb(widget.text_color) or (0, 0, 0)
    return (0, 0, 0)


def needs_appearances(doc) -> bool:
    key = "AcroForm/NeedAppearances"
    return pdfobj.get(doc, doc.pdf_catalog(), key)[1] == "true"


def settle_appearances(doc) -> None:
    """NeedAppearances 가 켜져 있으면 리더마다 제멋대로 다시 그림 → 우리가 그려 넣고 끔.

    쪽을 읽기 전에 플래그부터 꺼야 엔진이 만든 그림이 섞이지 않음.
    """
    if not needs_appearances(doc):
        return
    root = doc.pdf_catalog()
    kind, value = pdfobj.get(doc, root, "AcroForm")
    if kind == "xref":
        doc.xref_set_key(int(value.split()[0]), "NeedAppearances", "false")
    else:
        doc.xref_set_key(root, "AcroForm/NeedAppearances", "false")
    drawn = set()
    for pno in range(doc.page_count):
        for field in read(doc, pno):
            owner = _owner(doc, field.xref)
            if field.kind in ("text", "combo", "list") and field.value and owner not in drawn:
                drawn.add(owner)
                set_value(doc, replace(field, read_only=False), field.value)


def set_value(doc, field: Field, value) -> None:
    if field.read_only or field.kind == "signature":
        raise DocumentError("read_only")
    owner = _owner(doc, field.xref)
    if field.kind in ("check", "radio"):
        _set_button(doc, field, owner, bool(value))
        return

    color = _text_color(doc, field.pno, field.xref)
    if field.kind == "list":
        chosen = list(value)
        stored = [pdfobj.text_string(v) for v in chosen]
        raw = f"[{' '.join(stored)}]" if len(stored) > 1 else "".join(stored) or "null"
    else:
        value = str(value)
        if field.max_len:
            value = value[: field.max_len]
        raw = pdfobj.text_string(value)
    doc.xref_set_key(owner, "V", raw)
    for stale in ("RV", "I"):  # 남아 있으면 옛 값을 보여 주는 리더가 있음
        if pdfobj.get(doc, owner, stale)[0] != "null":
            doc.xref_set_key(owner, stale, "null")

    align = _int(doc, owner, "Q")
    comb = field.max_len if _int(doc, owner, "Ff") & COMB and not field.multiline else 0
    labels = dict(field.options)
    for xref in _widgets(doc, owner):
        look = _look(doc, xref)
        if look is None:
            continue
        w, h, rotation, decor = look
        if field.kind == "list":
            selected = {i for i, (key, _) in enumerate(field.options) if key in chosen}
            names = [label for _, label in field.options]
            ap, size = appearance.list_field(
                doc, w, h, names, selected, field.font_size, color, rotation, decor
            )
        else:
            shown = "*" * len(value) if field.password else labels.get(value, value)
            ap, size = appearance.text_field(
                doc, w, h, shown, field.font_size, color, rotation,
                align=align, multiline=field.multiline, comb=comb,
                background=decor[0], border=decor[1],
            )
        doc.xref_set_key(xref, "AP", f"<</N {ap} 0 R>>")
        if not field.font_size:
            _pin_size(doc, xref, size, color)


def _on_state(doc, xref: int) -> str | None:
    value = pdfobj.get(doc, xref, "AP/N")
    if value[0] == "xref" and doc.xref_is_stream(int(value[1].split()[0])):
        return None  # 상태별 그림이 없는 단추
    return next((s for s in _STATE.findall(pdfobj.body(doc, value)) if s != "Off"), None)


def _glyph_breaks(doc, xref: int, state: str) -> bool:
    """MuPDF 계열이 만든 체크 글리프(ZapfDingbats + Encoding)는 Adobe 엔진에서 네모로 깨짐."""
    kind, value = pdfobj.get(doc, xref, f"AP/N/{state}")
    if kind != "xref":
        return False
    fonts = pdfobj.get(doc, int(value.split()[0]), "Resources/Font")
    described = [pdfobj.body(doc, fonts)]
    described += [doc.xref_object(x, compressed=True) for x in pdfobj.refs(doc, fonts)]
    return any("/ZapfDingbats" in s and "/Encoding" in s for s in described)


def _set_caption(doc, xref: int, radio: bool) -> None:
    """Adobe 엔진은 단추 그림을 캡션 글자(MK/CA)로 다시 만듦."""
    doc.xref_set_key(xref, "DA", "(0 g /ZaDb 0 Tf)")
    caption = "(l)" if radio else "(4)"
    kind, value = pdfobj.get(doc, xref, "MK")
    if kind == "xref":
        doc.xref_set_key(int(value.split()[0]), "CA", caption)
    else:
        doc.xref_set_key(xref, "MK/CA", caption)


def _set_button(doc, field: Field, owner: int, on: bool) -> None:
    radio = field.kind == "radio"
    states = {}
    for index, xref in enumerate(_widgets(doc, owner)):
        state = _on_state(doc, xref)
        if state is None or _glyph_breaks(doc, xref, state):
            look = _look(doc, xref)
            if look is None:
                continue
            w, h, rotation, decor = look
            state = state or (f"Choice{index + 1}" if radio else "Yes")
            yes = appearance.check(doc, w, h, True, radio, rotation, *decor)
            no = appearance.check(doc, w, h, False, radio, rotation, *decor)
            doc.xref_set_key(xref, "AP", f"<</N<</{state} {yes} 0 R/Off {no} 0 R>>>>")
            _set_caption(doc, xref, radio)
        states[xref] = state
    wanted = states.get(field.xref)
    if on and wanted is None:
        raise DocumentError("write", "button without appearance")

    same_goes_on = not radio or bool(_int(doc, owner, "Ff") & RADIOS_IN_UNISON)
    doc.xref_set_key(owner, "V", f"/{wanted}" if on else "/Off")
    for xref, state in states.items():
        lit = on and state == wanted and (same_goes_on or xref == field.xref)
        doc.xref_set_key(xref, "AS", f"/{state}" if lit else "/Off")
