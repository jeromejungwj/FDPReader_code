"""문서 한 개의 타일·미리보기 캐시."""

from __future__ import annotations

from collections import OrderedDict
from typing import NamedTuple

from PySide6.QtGui import QPixmap


class Tile(NamedTuple):
    gen: int
    x: int
    y: int
    scale: float
    pixmap: QPixmap | None  # None = 렌더 실패


class TileCache:
    def __init__(self, limit_bytes: int):
        self.limit = limit_bytes
        self.used = 0
        self._items: OrderedDict[tuple, Tile] = OrderedDict()

    @staticmethod
    def _cost(tile: Tile) -> int:
        return tile.pixmap.width() * tile.pixmap.height() * 4 if tile.pixmap else 64

    def get(self, key: tuple) -> Tile | None:
        tile = self._items.get(key)
        if tile is not None:
            self._items.move_to_end(key)
        return tile

    def put(self, key: tuple, tile: Tile) -> None:
        old = self._items.pop(key, None)
        if old is not None:
            self.used -= self._cost(old)
        self._items[key] = tile
        self.used += self._cost(tile)
        while self.used > self.limit and len(self._items) > 1:
            self.used -= self._cost(self._items.popitem(last=False)[1])

    def clear(self) -> None:
        self._items.clear()
        self.used = 0
