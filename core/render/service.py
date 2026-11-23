"""렌더 프로세스 관리. 보이는 쪽부터, 화면이 바뀌면 밀린 요청은 버림."""

from __future__ import annotations

import logging
import multiprocessing
import threading
import time
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from . import worker

log = logging.getLogger(__name__)

IN_FLIGHT = 2
HANG_SECONDS = 20.0
RESTART_DELAY = 2000  # 뜨자마자 죽으면 무한 재시작하지 않게 (ms)


@dataclass
class Job:
    key: tuple
    source: tuple  # Document.render_source()
    gen: int
    pno: int
    scale: float
    clip: tuple | None
    theme: str
    done: Callable  # done(job, (x, y, QImage) 또는 None)


def to_image(result) -> tuple[int, int, QImage]:
    x, y, w, h, stride, samples = result
    return x, y, QImage(samples, w, h, stride, QImage.Format.Format_RGB888).copy()


class RenderService(QObject):
    _received = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._received.connect(self._on_received)
        self._queues: dict[object, list[Job]] = {}
        self._running: dict[int, tuple[object, Job, float]] = {}
        self._next_id = 0
        self._process = self._conn = None
        self._closing = False
        self._watch = QTimer(self)
        self._watch.timeout.connect(self._check_hang)
        self._watch.start(2000)
        self._start()

    def _start(self) -> None:
        context = multiprocessing.get_context("spawn")
        conn, child = context.Pipe()
        process = context.Process(target=worker.serve, args=(child,), daemon=True)
        process.start()
        child.close()
        self._process, self._conn = process, conn
        self._started = time.monotonic()
        threading.Thread(target=self._listen, args=(conn,), daemon=True).start()

    def _listen(self, conn) -> None:
        try:
            while True:
                self._received.emit(conn, conn.recv())
        except (EOFError, OSError):
            pass
        except RuntimeError:  # 종료 중 QObject 가 먼저 사라짐
            return
        try:
            self._received.emit(conn, None)
        except RuntimeError:
            pass

    def want(self, owner, jobs: list[Job]) -> None:
        """owner 의 대기 요청을 jobs 로 통째로 바꿈."""
        self._queues.pop(owner, None)
        if jobs:
            # 방금 요청한 화면이 먼저
            self._queues = {owner: list(jobs), **self._queues}
        self._pump()

    def running(self, owner) -> set[tuple]:
        return {(job.key, job.gen) for who, job, _ in self._running.values() if who is owner}

    def forget(self, owner, path: str) -> None:
        self._queues.pop(owner, None)
        for key, (who, _, _) in list(self._running.items()):
            if who is owner:
                self._running[key] = (None, *self._running[key][1:])
        self._send(("close", path))

    def _send(self, message) -> bool:
        try:
            self._conn.send(message)
            return True
        except (OSError, ValueError, AttributeError):
            return False

    def _pump(self) -> None:
        while len(self._running) < IN_FLIGHT and self._queues:
            owner = next(iter(self._queues))
            queue = self._queues[owner]
            job = queue.pop(0)
            if not queue:
                del self._queues[owner]
            self._next_id += 1
            message = (
                "render", self._next_id, job.source, job.pno, job.scale, job.clip, job.theme
            )
            if not self._send(message):
                self._queues.setdefault(owner, []).insert(0, job)
                return
            self._running[self._next_id] = (owner, job, time.monotonic())

    def _on_received(self, conn, message) -> None:
        if conn is not self._conn or self._closing:
            return
        if message is None:
            log.warning("렌더 프로세스가 끝나 다시 띄움")
            failed, self._running = list(self._running.values()), {}
            if time.monotonic() - self._started < 1.0:
                self._conn = None
                QTimer.singleShot(RESTART_DELAY, self._restart)
            else:
                self._start()
            # 죽게 만든 첫 요청만 실패로 처리해 같은 쪽에서 반복해 죽지 않게 함
            for index, (owner, job, _) in enumerate(failed):
                if owner is not None:
                    if index == 0:
                        job.done(job, None)
                    else:
                        self._queues.setdefault(owner, []).insert(0, job)
        else:
            job_id, result = message
            owner, job, _ = self._running.pop(job_id, (None, None, 0))
            if owner is not None:
                job.done(job, to_image(result) if result else None)
        self._pump()

    def _restart(self) -> None:
        if not self._closing:
            self._start()
            self._pump()

    def _check_hang(self) -> None:
        if self._running:
            oldest = min(started for _, _, started in self._running.values())
            if time.monotonic() - oldest > HANG_SECONDS:
                log.warning("렌더가 %d초 넘게 걸려 프로세스를 다시 띄움", HANG_SECONDS)
                self._process.terminate()

    def shutdown(self) -> None:
        self._closing = True
        self._watch.stop()
        self._process.terminate()
        self._process.join(2)
        if self._conn is not None:
            self._conn.close()
