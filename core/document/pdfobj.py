"""PDF 객체를 읽고 쓰는 작은 도우미."""

from __future__ import annotations

import re

import pymupdf as mu

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)")
_REF = re.compile(r"(\d+)\s+\d+\s+R")
NULL = ("null", "null")


def text_string(value: str) -> str:
    return "<feff" + value.encode("utf-16-be", "replace").hex() + ">"


def numbers(*values) -> str:
    return " ".join(f"{v:.3f}".rstrip("0").rstrip(".") for v in values)


def get(doc: mu.Document, xref: int, key: str) -> tuple[str, str]:
    try:
        return doc.xref_get_key(xref, key)
    except Exception:
        return NULL


def body(doc: mu.Document, value: tuple[str, str]) -> str:
    """간접 참조면 그 객체의 내용을 돌려줌."""
    kind, raw = value
    if kind == "xref":
        return doc.xref_object(int(raw.split()[0]), compressed=True).strip()
    return "" if kind == "null" else raw


def refs(doc: mu.Document, value: tuple[str, str]) -> list[int]:
    return [int(n) for n in _REF.findall(body(doc, value))]


def number_list(doc: mu.Document, value: tuple[str, str]) -> list[float]:
    raw = body(doc, value)
    if _REF.search(raw):  # 숫자 자리에 참조가 든 배열
        return []
    return [float(n) for n in _NUMBER.findall(raw)]


def rect(doc: mu.Document, xref: int, key: str = "Rect") -> mu.Rect | None:
    values = number_list(doc, get(doc, xref, key))
    return mu.Rect(values).normalize() if len(values) == 4 else None


def inherited(doc: mu.Document, xref: int, key: str) -> tuple[str, str]:
    """필드는 부모에게서 값을 물려받음."""
    for _ in range(32):  # 순환 참조 방어
        value = get(doc, xref, key)
        if value[0] != "null":
            return value
        parent = get(doc, xref, "Parent")
        if parent[0] != "xref":
            break
        xref = int(parent[1].split()[0])
    return NULL


def new_object(doc: mu.Document, source: str) -> int:
    xref = doc.get_new_xref()
    doc.update_object(xref, source)
    return xref


def append_annot(doc: mu.Document, page: mu.Page, xref: int) -> None:
    kind, raw = get(doc, page.xref, "Annots")
    if kind == "xref":  # 배열이 따로 떨어진 객체인 경우
        holder = int(raw.split()[0])
        items = doc.xref_object(holder, compressed=True).strip()
        items = items[1:-1] if items.startswith("[") else ""
        doc.update_object(holder, f"[{items} {xref} 0 R]")
    else:
        items = raw[1:-1] if kind == "array" else ""
        doc.xref_set_key(page.xref, "Annots", f"[{items} {xref} 0 R]")
