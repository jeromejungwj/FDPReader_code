"""두 번째 실행은 파일 경로만 첫 프로세스에 넘김 (새 탭으로 열림)."""

from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from storage import files
from storage.state import key_of

log = logging.getLogger(__name__)

MAX_MESSAGE = 64 * 1024


def channel_name() -> str:
    identity = f"{os.environ.get('USERNAME', '')}|{key_of(files.data_dir())}"
    return "FDPReader-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


class SingleInstance(QObject):
    received = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._name = channel_name()
        self._server: QLocalServer | None = None

    def hand_over(self, paths: list[str]) -> bool:
        """이미 실행 중이면 넘기고 True."""
        socket = QLocalSocket()
        socket.connectToServer(self._name)
        if not socket.waitForConnected(150):
            return False
        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # 첫 프로세스가 앞으로 나올 수 있게
        socket.write(json.dumps(paths).encode("utf-8") + b"\n")
        socket.flush()
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()
        return True

    def listen(self) -> None:
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._accept)
        if not self._server.listen(self._name):
            log.warning("단일 실행 채널을 열지 못함: %s", self._server.errorString())

    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            buffer = bytearray()

            def read(socket=socket, buffer=buffer) -> None:
                buffer.extend(bytes(socket.readAll().data()))
                if len(buffer) > MAX_MESSAGE:
                    socket.abort()
                    return
                if b"\n" not in buffer:
                    return
                line = bytes(buffer).split(b"\n", 1)[0]
                buffer.clear()
                try:
                    paths = json.loads(line)
                except ValueError:
                    return
                if isinstance(paths, list) and all(isinstance(p, str) for p in paths):
                    self.received.emit(paths)

            socket.readyRead.connect(read)
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                read()
