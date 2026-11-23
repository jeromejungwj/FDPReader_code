"""터치 접촉 → 프레임 → 획 이벤트. Windows·Qt 에 의존하지 않음 (입력 기록 재생으로 테스트)."""

from __future__ import annotations

from typing import NamedTuple

GESTURE_WINDOW = 0.12  # 이 시간 안에 두 번째 손가락이 닿으면 서명이 아니라 스크롤·핀치로 봄


class Contact(NamedTuple):
    id: int
    x: float  # 0~1
    y: float  # 0~1
    tip: bool
    confident: bool


class FrameAssembler:
    """Hybrid 모드(손가락 여러 개를 보고서 여러 개에 나눠 보냄)를 한 프레임으로 합침."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self._parts: list[Contact] = []
        self._left = 0

    def feed(self, count: int, slots: list[Contact]) -> list[Contact] | None:
        if count:
            self._parts, self._left = [], count
        elif not self._left:
            return []
        take = slots[: self._left]
        self._parts += take
        self._left -= len(take)
        if self._left > 0 and take:
            return None
        frame = self._parts
        self.reset()
        return frame


class FingerTracker:
    """첫 손가락만 획으로 바꾸고 손바닥과 멀티터치 제스처는 버림."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self._active: int | None = None
        self._since = 0.0
        self._wait_lift = False  # 남은 손가락이 다 떨어질 때까지 새 획을 시작하지 않음
        self._palms: set[int] = set()

    def feed(self, contacts: list[Contact], now: float) -> list[tuple]:
        """("down"|"move", x, y, t) · ("up",) · ("cancel",) 목록을 돌려줌."""
        down = [c for c in contacts if c.tip]
        self._palms &= {c.id for c in down}
        self._palms |= {c.id for c in down if not c.confident}
        fingers = [c for c in down if c.id not in self._palms]

        if self._active is not None:
            mine = next((c for c in fingers if c.id == self._active), None)
            if mine is None:
                event = ("cancel",) if self._active in self._palms else ("up",)
                self._active, self._wait_lift = None, bool(fingers)
                return [event]
            if len(fingers) > 1 and now - self._since < GESTURE_WINDOW:
                self._active, self._wait_lift = None, True
                return [("cancel",)]
            return [("move", mine.x, mine.y, now)]

        if not fingers:
            self._wait_lift = False
        elif len(fingers) > 1:
            self._wait_lift = True
        elif not self._wait_lift:
            self._active, self._since = fingers[0].id, now
            return [("down", fingers[0].x, fingers[0].y, now)]
        return []
