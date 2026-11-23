"""페이지 글자: 선택, 검색, 복사용 줄바꿈 정리. 엔진에 의존하지 않음."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Rect


def union(boxes) -> Rect:
    x0, y0, x1, y1 = zip(*boxes)
    return min(x0), min(y0), max(x1), max(y1)


@dataclass(frozen=True)
class Line:
    start: int
    end: int  # 줄바꿈 문자 자리
    box: Rect
    block: int
    direction: tuple[float, float]


def _is_spaceless(ch: str) -> bool:
    """띄어쓰기를 쓰지 않는 한자·가나."""
    return 0x3040 <= ord(ch) <= 0x30FF or 0x4E00 <= ord(ch) <= 0x9FFF


def compile_query(query: str, match_case: bool, whole_word: bool) -> re.Pattern | None:
    parts = query.split()
    if not parts:
        return None
    # 글자 사이의 "\n?" 로 줄 끝에서 잘린 낱말도 찾음
    body = r"\s+".join(r"\n?".join(re.escape(c) for c in part) for part in parts)
    if whole_word:
        body = rf"(?<!\w){body}(?!\w)"
    return re.compile(body, 0 if match_case else re.IGNORECASE)


class PageText:
    def __init__(self, blocks: list[dict] = ()):
        text: list[str] = []
        self.boxes: list[Rect | None] = []
        self.lines: list[Line] = []
        self._line_of: list[int] = []
        self._block_box: dict[int, Rect] = {}

        for number, block in enumerate(blocks):
            lines_in_block = []
            for raw in block.get("lines", ()):
                chars = [c for span in raw["spans"] for c in span.get("chars", ())]
                if not chars:
                    continue
                start = len(text)
                for c in chars:
                    ch = c["c"][:1]
                    text.append(" " if ch in ("", "\n", "\r") else ch)
                    self.boxes.append(tuple(c["bbox"]))
                box = union(self.boxes[start:])
                self.lines.append(
                    Line(start, len(text), box, number, tuple(raw.get("dir", (1.0, 0.0))))
                )
                lines_in_block.append(box)
                text.append("\n")
                self.boxes.append(None)
                self._line_of += [len(self.lines) - 1] * (len(text) - start)
            if lines_in_block:
                self._block_box[number] = union(lines_in_block)
        self.text = "".join(text)

    def char_at(self, x: float, y: float) -> int | None:
        for line in self.lines:
            lx0, ly0, lx1, ly1 = line.box
            if lx0 <= x <= lx1 and ly0 <= y <= ly1:
                for i in range(line.start, line.end):
                    x0, y0, x1, y1 = self.boxes[i]
                    if x0 <= x <= x1 and y0 <= y <= y1:
                        return i
        return None

    def caret(self, x: float, y: float) -> int:
        """점에 가장 가까운 글자 사이 위치."""
        if not self.lines:
            return 0

        def distance(line: Line) -> float:
            x0, y0, x1, y1 = line.box
            dx, dy = max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1)
            horizontal = abs(line.direction[0]) >= abs(line.direction[1])
            return dx + 4 * dy if horizontal else dy + 4 * dx

        line = min(self.lines, key=distance)
        ux, uy = line.direction
        here = x * ux + y * uy
        for i in range(line.start, line.end):
            x0, y0, x1, y1 = self.boxes[i]
            if (x0 + x1) / 2 * ux + (y0 + y1) / 2 * uy > here:
                return i
        return line.end

    def word(self, i: int) -> tuple[int, int]:
        def kind(ch: str) -> str:
            if ch.isalnum() or ch == "_":
                return "word"
            return "space" if ch.isspace() and ch != "\n" else ch

        wanted = kind(self.text[i])
        a, b = i, i + 1
        while a > 0 and kind(self.text[a - 1]) == wanted:
            a -= 1
        while b < len(self.text) and kind(self.text[b]) == wanted:
            b += 1
        return a, b

    def line(self, i: int) -> tuple[int, int]:
        line = self.lines[self._line_of[i]]
        return line.start, line.end

    def rects(self, a: int, b: int) -> list[Rect]:
        out = []
        for line in self.lines:
            start, end = max(a, line.start), min(b, line.end)
            if start < end:
                out.append(union(self.boxes[start:end]))
        return out

    def quads(self, a: int, b: int) -> list[tuple]:
        """글자 방향 기준 (왼위, 오위, 왼아래, 오아래). 밑줄이 글자 아래로 가려면 방향이 필요함."""
        out = []
        for line in self.lines:
            start, end = max(a, line.start), min(b, line.end)
            if start >= end:
                continue
            x0, y0, x1, y1 = union(self.boxes[start:end])
            tl, tr, bl, br = (x0, y0), (x1, y0), (x0, y1), (x1, y1)
            ux, uy = line.direction
            if abs(ux) >= abs(uy):
                out.append((tl, tr, bl, br) if ux >= 0 else (br, bl, tr, tl))
            else:
                out.append((tr, br, tl, bl) if uy > 0 else (bl, tl, br, tr))
        return out

    def copy_text(self, a: int, b: int) -> str:
        """문단 안의 줄바꿈은 잇고, 문단·목록처럼 일찍 끝난 줄은 남김."""
        out = ""
        previous: Line | None = None
        for line in self.lines:
            start, end = max(a, line.start), min(b, line.end)
            if start >= end:
                continue
            part = self.text[start:end]
            if previous is not None:
                out, part = self._join(out, part, previous, line)
            out += part
            previous = line
        return out

    def _join(self, out: str, part: str, before: Line, line: Line) -> tuple[str, str]:
        if before.block != line.block:
            return out.rstrip() + "\n", part
        tail, head = out.rstrip(), part.lstrip()
        if not tail or not head:
            return tail, head
        x0, y0, x1, y1 = before.box
        if before.direction[0] > 0.9:
            if abs((line.box[1] + line.box[3]) - (y0 + y1)) < (y1 - y0) * 0.5:
                return tail + " ", head  # 같은 높이에서 나뉜 조각
            if self._block_box[before.block][2] - x1 > (y1 - y0) * 3:
                return tail + "\n", head
        if tail.endswith("-") and head[0].islower() and len(tail) > 1 and tail[-2].isalpha():
            return tail[:-1], head
        if _is_spaceless(tail[-1]) and _is_spaceless(head[0]):
            return tail, head
        return tail + " ", head

    def find(self, pattern: re.Pattern):
        for match in pattern.finditer(self.text):
            if match.end() > match.start():
                yield match.start(), match.end()

    def snippet(self, a: int, b: int, around: int = 24) -> str:
        return " ".join(self.text[max(0, a - around) : b + around].split())
