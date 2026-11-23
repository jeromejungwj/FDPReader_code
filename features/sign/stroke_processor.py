"""획 다듬기: 속도 기반 가변 굵기 Bézier 보간. 화면과 PDF 가 같은 선분을 그림.

길이 단위는 트랙패드 높이 = 1.
"""

from __future__ import annotations

import base64
import math

from core.document.models import Graphic

WIDTHS = (0.012, 0.020, 0.030)
COLORS = ((0.0, 0.0, 0.0), (0.05, 0.2, 0.65))  # 검정, 파랑

SMOOTHING = 0.6  # 새 점을 따라가는 비율
FULL_THIN_SPEED = 4.0  # 초당 높이의 4배로 그으면 가장 가늘어짐
STEP = 0.012  # 곡선을 나누는 간격

Segment = tuple[float, float, float, float, float]


class StrokeBuilder:
    def __init__(self, thickness: float):
        self.thickness = thickness
        self._raw: tuple[float, float, float] | None = None
        self._point = self._mid = (0.0, 0.0)
        self._width = thickness
        self._speed = 0.0
        self._drawn = False

    def add(self, x: float, y: float, t: float, pressure: float | None = None) -> list[Segment]:
        if self._raw is None:
            self._raw = (x, y, t)
            self._point = self._mid = (x, y)
            if pressure is not None:
                self._width = self.thickness * (0.4 + 1.2 * pressure)
            return []
        rx, ry, rt = self._raw
        moved = math.hypot(x - rx, y - ry)
        if moved < 1e-4:
            return []
        self._raw = (x, y, t)
        self._speed += 0.3 * (moved / max(t - rt, 0.004) - self._speed)
        if pressure is None:
            target = self.thickness * (1.25 - 0.8 * min(self._speed / FULL_THIN_SPEED, 1.0))
        else:
            target = self.thickness * (0.4 + 1.2 * pressure)
        width = self._width + 0.35 * (target - self._width)

        px, py = self._point
        point = (px + SMOOTHING * (x - px), py + SMOOTHING * (y - py))
        mid = ((px + point[0]) / 2, (py + point[1]) / 2)
        segments = self._curve(self._mid, self._point, mid, self._width, width)
        self._point, self._mid, self._width = point, mid, width
        return segments

    def _curve(self, a, control, b, w0: float, w1: float) -> list[Segment]:
        length = math.dist(a, control) + math.dist(control, b)
        if length < 1e-6:
            return []
        count = min(max(math.ceil(length / STEP), 1), 16)
        out, last = [], a
        for i in range(1, count + 1):
            s = i / count
            here = (
                (1 - s) ** 2 * a[0] + 2 * (1 - s) * s * control[0] + s * s * b[0],
                (1 - s) ** 2 * a[1] + 2 * (1 - s) * s * control[1] + s * s * b[1],
            )
            out.append((*last, *here, w0 + (w1 - w0) * s))
            last = here
        self._drawn = True
        return out

    def finish(self) -> list[Segment]:
        if self._raw is None:
            return []
        x, y, _ = self._raw
        if not self._drawn:
            if math.dist(self._mid, (x, y)) < 1e-4:
                return [(x, y, x, y, self.thickness * 1.4)]  # 점
            return [(*self._mid, x, y, self._width)]
        return self._curve(self._mid, self._point, (x, y), self._width, self._width * 0.7)


def stroke_segments(stroke, aspect: float, thickness: float) -> list[Segment]:
    builder = StrokeBuilder(thickness)
    out = []
    for x, y, t, *pressure in stroke:
        out += builder.add(x * aspect, y, t, pressure[0] if pressure else None)
    return out + builder.finish()


def to_graphic(signature: dict) -> Graphic:
    """저장 형식(dict) → 문서·화면에 그릴 그림. 여백은 여기서 잘림."""
    kind = signature["kind"]
    color = tuple(signature.get("color", (0, 0, 0)))
    if kind == "ink":
        aspect, thickness = signature["aspect"], signature["width"]
        segments = [
            s for stroke in signature["strokes"] for s in stroke_segments(stroke, aspect, thickness)
        ]
        if not segments:
            raise ValueError("empty signature")
        bounds = (
            min(min(s[0], s[2]) - s[4] / 2 for s in segments),
            min(min(s[1], s[3]) - s[4] / 2 for s in segments),
            max(max(s[0], s[2]) + s[4] / 2 for s in segments),
            max(max(s[1], s[3]) + s[4] / 2 for s in segments),
        )
        return Graphic("lines", bounds, color, segments=tuple(segments))
    if kind == "outline":
        contours = tuple(tuple(tuple(p) for p in c) for c in signature["contours"])
        points = [p for c in contours for p in c]
        if not points:
            raise ValueError("empty signature")
        xs, ys = zip(*points)
        return Graphic("fill", (min(xs), min(ys), max(xs), max(ys)), color, contours=contours)
    if kind == "image":
        bounds = (0, 0, signature["size"][0], signature["size"][1])
        return Graphic("image", bounds, image=base64.b64decode(signature["png"]))
    raise ValueError(f"unknown signature kind: {kind}")
