"""게이트 1 (Acrobat·Edge·Chrome 표시 일치)용 시험 PDF 20종.  python -m tests.make_corpus [출력 폴더]

현재 코드의 Document 로 서명·주석·양식을 넣어 저장하고, 비교 기준인 FDP Reader 렌더 이미지(PNG)와
평탄화본·검사표를 함께 만듦. 기본 출력은 build/corpus (git 제외). 사용자 데이터는 건드리지 않음.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCALE = 2.0  # 144dpi 기준 이미지
FLATTEN = ("rot0", "form0", "korean")

FEATURES = {
    "rot0": "기본 쪽",
    "rot0c": "잘라낸 쪽 (CropBox)",
    "rot90": "쪽 90° 회전", "rot90c": "쪽 90° 회전 + 잘라냄",
    "rot180": "쪽 180° 회전", "rot180c": "쪽 180° 회전 + 잘라냄",
    "rot270": "쪽 270° 회전", "rot270c": "쪽 270° 회전 + 잘라냄",
    "objstm": "객체 스트림 압축",
    "linear0": "압축 저장",
    "aes256": "AES-256 암호 (암호 u)",
    "aes128": "AES-128 암호 (암호 u)",
    "rc4": "RC4 암호 (암호 u)",
    "v_objstm_rot": "객체 스트림 + 쪽 90° 회전",
    "form0": "양식 (값: 홍길동 2026, 체크, 부산, 셋)",
    "form1": "양식 (값: 홍길동 2026, 체크, 부산, 셋)",
    "view90": "FDP 화면을 90° 돌린 채 편집 → 다른 리더에선 서명이 옆으로 누운 게 정상",
    "view180": "FDP 화면을 180° 돌린 채 편집 → 서명이 뒤집힌 게 정상",
    "view270": "FDP 화면을 270° 돌린 채 편집 → 서명이 옆으로 누운 게 정상",
    "korean": "한글 본문",
}
SIGNATURE = {"ink": "손글씨", "typed": "타이핑", "image": "이미지"}
MARKUP = {"Highlight": "형광펜", "Underline": "밑줄", "StrikeOut": "취소선"}


def cases() -> list[dict]:
    import pymupdf as mu

    found = [
        dict(name=f"rot{rot}{'c' if crop else ''}", rotation=rot, crop=crop)
        for rot in (0, 90, 180, 270)
        for crop in (False, True)
    ]
    found += [
        dict(name="objstm", use_objstms=1, garbage=3, deflate=True),
        dict(name="linear0", deflate=True),
        dict(name="aes256", encryption=mu.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o"),
        dict(name="aes128", encryption=mu.PDF_ENCRYPT_AES_128, user_pw="u", owner_pw="o"),
        dict(name="rc4", encryption=mu.PDF_ENCRYPT_RC4_128, user_pw="u", owner_pw="o"),
        dict(name="v_objstm_rot", use_objstms=1, rotation=90),
        dict(name="form0", form=True),
        dict(name="form1", form=True),
    ]
    found += [dict(name=f"view{v}", view=v) for v in (90, 180, 270)] + [dict(name="korean", korean=True)]
    assert len(found) == 20
    return found


def main(out: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # offscreen Qt 는 Windows 글꼴을 못 찾아 타이핑 서명이 네모(□)로 그려짐
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
    os.environ["FDPREADER_DATA"] = tempfile.mkdtemp(prefix="fdp-corpus-")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from core.document.document import Document
    from features.sign import alt_input
    from features.sign.stroke_processor import to_graphic
    from tests import helpers

    paper = QImage(300, 120, QImage.Format.Format_RGB32)
    paper.fill(QColor(236, 234, 228))  # 종이 사진처럼 밝은 바탕 → 배경 제거 대상
    p = QPainter(paper)
    pen = p.pen()
    pen.setWidth(7)
    pen.setColor(QColor(20, 30, 120))
    p.setPen(pen)
    p.drawLine(30, 90, 90, 30)
    p.drawLine(90, 30, 130, 90)
    p.drawLine(130, 90, 260, 50)
    p.end()
    signatures = {
        "ink": {"kind": "ink", "aspect": 1.4, "width": 0.02, "color": [0, 0, 0],
                "strokes": [[(0.1 + i * 0.02, 0.5 + (i % 5) * 0.03, i * 0.01) for i in range(40)]]},
        "typed": alt_input.from_text("Hong 홍길동", "Segoe Script", (0, 0, 0.6)),
        "image": alt_input.from_image(paper),
    }
    kinds = list(signatures)
    out.mkdir(parents=True, exist_ok=True)
    rows, thumbs = [], []
    for i, case in enumerate(cases()):
        case = dict(case)
        name, view = case.pop("name"), case.pop("view", 0)
        src = out / f"{name}.pdf"
        if case.pop("form", False):
            helpers.form(src)
        elif case.pop("korean", False):
            helpers.korean(src)
        else:
            helpers.plain(src, 1, **case)
        doc = Document(src, "u")
        w, h = doc.sizes[0]
        kind, as_ink = kinds[i % 3], i % 4 == 0
        graphic = to_graphic(signatures[kind])
        aspect = graphic.aspect if view % 180 == 0 else 1 / graphic.aspect
        sw = min(150, 120 * aspect)
        xref = doc.add_signature(0, (40, 200, 40 + sw, 200 + sw / aspect), graphic, view, as_ink=as_ink)
        stored = next(a.kind for a in doc.annots(0) if a.xref == xref)  # Ink 는 손글씨에만 적용됨
        box = (40, 150, 250, 180) if view % 180 == 0 else (250, 150, 280, 330)
        doc.add_text(0, box, "타자기 홍길동 12", 12, view)
        page = doc.text(0)
        markup = ""
        if page.lines:
            markup = ("Highlight", "Underline", "StrikeOut")[i % 3]
            doc.add_markup(markup, [(0, page.quads(0, page.lines[0].end))], (1, 0.7, 0.1))
        doc.add_note(0, w - 40, 20, "메모", (1, 0.85, 0.25), view)
        for field in list(doc.fields(0)):
            value = {"text": "홍길동 2026", "check": True, "combo": "부산", "list": ["셋"]}.get(field.kind)
            if value is not None:
                doc.set_field(field, value)
        doc.save()
        x, y, pw, ph, stride, data = doc.render(0, SCALE)
        image = QImage(data, pw, ph, stride, QImage.Format.Format_RGB888).copy()
        image.save(str(out / f"{name}.png"))
        thumbs.append((name, image))
        if name in FLATTEN:
            doc.export_flattened(out / f"{name}_평탄화.pdf")
        doc.close()
        contents = [f"서명 {SIGNATURE[kind]} ({stored})", "타자기 한글", "메모"]
        if markup:
            contents.insert(1, MARKUP[markup])
        rows.append((name, FEATURES[name], ", ".join(contents)))

    # 한눈에 보기: 기준 이미지 20장을 5×4 로
    cell_w, cell_h = 300, 380
    sheet = QImage(cell_w * 5, cell_h * 4, QImage.Format.Format_RGB32)
    sheet.fill(QColor("white"))
    painter = QPainter(sheet)
    for n, (name, image) in enumerate(thumbs):
        cx, cy = n % 5 * cell_w, n // 5 * cell_h
        small = image.scaled(cell_w - 12, cell_h - 30, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        painter.drawText(cx + 6, cy + 16, name)
        painter.drawImage(cx + 6, cy + 24, small)
        painter.drawRect(cx + 6, cy + 24, small.width() - 1, small.height() - 1)
    painter.end()
    sheet.save(str(out / "_한눈에.png"))

    lines = [
        "# 게이트 1 검사표 — Acrobat·Edge·Chrome 표시 일치",
        "",
        "각 PDF를 세 리더로 열어 같은 이름의 PNG(FDP Reader 기준 화면)와 비교. "
        "같으면 O, 다르면 무엇이 다른지 적기. 암호 파일의 암호는 `u`.",
        "",
        "확인할 것: 서명(보임·위치·크기·방향), 형광펜·밑줄·취소선(색·위치), 타자기 한글 깨짐, "
        "메모 아이콘 위치, 양식 값. 이미 알려진 차이: Edge가 메모 옆에 작은 말풍선을 더 그림.",
        "",
        "| 파일 | 특징 | 들어 있는 것 | Edge | Chrome | Acrobat |",
        "|---|---|---|---|---|---|",
    ]
    lines += [f"| `{n}.pdf` | {f} | {c} |  |  |  |" for n, f, c in rows]
    lines += [
        "",
        "## 평탄화본 (서명·주석이 쪽 내용으로 굳은 사본 — 같은 PNG와 비교)",
        "",
        "| 파일 | Edge | Chrome | Acrobat |",
        "|---|---|---|---|",
    ]
    lines += [f"| `{n}_평탄화.pdf` |  |  |  |" for n in FLATTEN]
    (out / "검사표.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    del app
    print(f"{len(rows)}종 + 평탄화 {len(FLATTEN)}종 → {out}")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "corpus")
