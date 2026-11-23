"""페이지 배치 계산 (단일·연속·두 쪽·책). Qt 에 의존하지 않음."""

from __future__ import annotations

from bisect import bisect_right
from typing import NamedTuple

GAP = 12
MARGIN = 12
MODES = ("single", "continuous", "two", "book")


class Slot(NamedTuple):
    pno: int
    x: float
    y: float
    w: float
    h: float


def spreads(count: int, mode: str, current: int = 0) -> list[list[int]]:
    if mode == "single":
        return [[current]]
    if mode == "two":
        return [list(range(i, min(i + 2, count))) for i in range(0, count, 2)]
    if mode == "book":
        return [[0]] + [list(range(i, min(i + 2, count))) for i in range(1, count, 2)]
    return [[i] for i in range(count)]


def spread_of(pno: int, mode: str) -> list[int]:
    if mode == "two":
        first = pno - pno % 2
        return [first, first + 1]
    if mode == "book" and pno:
        first = pno if pno % 2 else pno - 1
        return [first, first + 1]
    return [pno]


def fit_zoom(sizes, mode: str, pno: int, width: float, height: float, whole_page: bool) -> float:
    """1pt 가 몇 화면 픽셀이 되어야 맞는지."""
    pages = [p for p in spread_of(pno, mode) if p < len(sizes)]
    columns = 2 if mode in ("two", "book") else 1
    wide = sum(sizes[p][0] for p in pages) * (columns / len(pages))
    zoom = max(width - 2 * MARGIN - GAP * (columns - 1), 32) / wide
    if whole_page:
        zoom = min(zoom, max(height - 2 * MARGIN, 32) / max(sizes[p][1] for p in pages))
    return zoom


class Layout:
    def __init__(self, sizes, mode: str, zoom: float, width: float, height: float, current=0):
        rows = spreads(len(sizes), mode, current)
        paired = mode in ("two", "book")

        def row_width(row) -> float:
            total = sum(sizes[p][0] for p in row) * zoom
            if paired:
                total = total * 2 / len(row) + GAP
            return total

        self.width = max(width, max(row_width(r) for r in rows) + 2 * MARGIN)
        self.slots: list[Slot] = []
        self._by_page: dict[int, Slot] = {}
        self._tops: list[float] = []
        self._rows: list[list[Slot]] = []
        y = float(MARGIN)
        if mode == "single":
            y = max(y, (height - sizes[current][1] * zoom) / 2)
        for row in rows:
            x = (self.width - row_width(row)) / 2
            if mode == "book" and row == [0]:  # 표지는 오른쪽에 단독
                x += sizes[0][0] * zoom + GAP
            tall = max(sizes[p][1] for p in row) * zoom
            placed = []
            for pno in row:
                w, h = sizes[pno][0] * zoom, sizes[pno][1] * zoom
                slot = Slot(pno, x, y + (tall - h) / 2, w, h)
                self._by_page[pno] = slot
                placed.append(slot)
                x += w + GAP
            self._tops.append(y)
            self._rows.append(placed)
            self.slots += placed
            y += tall + GAP
        self.height = max(height, y - GAP + MARGIN)

    def slot(self, pno: int) -> Slot | None:
        return self._by_page.get(pno)

    def visible(self, top: float, bottom: float) -> list[Slot]:
        first = max(bisect_right(self._tops, top) - 1, 0)
        out = []
        for index in range(first, len(self._rows)):
            if self._tops[index] >= bottom:
                break
            out += [s for s in self._rows[index] if s.y < bottom and s.y + s.h > top]
        return out

    def nearest(self, x: float, y: float) -> Slot:
        index = max(bisect_right(self._tops, y) - 1, 0)
        candidates = [s for row in self._rows[index : index + 2] for s in row]

        def distance(s: Slot) -> float:
            dx, dy = max(s.x - x, 0, x - s.x - s.w), max(s.y - y, 0, y - s.y - s.h)
            return dx * dx + dy * dy

        return min(candidates, key=distance)
