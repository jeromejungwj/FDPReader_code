"""실행 진입점: python -m app [파일.pdf ...]"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def _setup_logging() -> None:
    from storage import files

    handler = RotatingFileHandler(
        files.data_dir() / "fdpreader.log", maxBytes=512_000, backupCount=1, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr is not None:  # pythonw 로 띄우면 stderr 가 없음
        root.addHandler(logging.StreamHandler())
    logging.getLogger("pymupdf").setLevel(logging.ERROR)

    def on_exception(kind, error, trace) -> None:
        logging.getLogger("fdpreader").error("처리되지 않은 예외", exc_info=(kind, error, trace))

    sys.excepthook = on_exception


def main() -> int:
    _setup_logging()
    log = logging.getLogger("fdpreader")

    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    from PySide6.QtWidgets import QApplication

    from storage.state import State

    from . import i18n
    from .single_instance import SingleInstance

    app = QApplication(sys.argv)
    app.setApplicationName("FDP Reader")
    app.setStyle("Fusion")  # OS 다크 모드·고대비 팔레트를 따름

    paths = [os.path.abspath(arg) for arg in app.arguments()[1:] if not arg.startswith("-") and arg]
    instance = SingleInstance()
    if instance.hand_over(paths):
        return 0

    state = State()
    language = state["language"]
    if language not in ("ko", "en"):
        language = "ko" if QLocale.system().language() == QLocale.Language.Korean else "en"
    i18n.use(language)
    if language == "ko":  # 표준 단추(예·아니요·취소) 한국어
        translator = QTranslator(app)
        if translator.load("qtbase_ko", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(translator)

    from core.render.service import RenderService

    service = RenderService()
    try:
        from .controller import Controller

        controller = Controller(state, service)
        instance.received.connect(controller.open_from_elsewhere)
        instance.listen()
        controller.start(paths)
        log.info("시작")
        if os.environ.get("FDPREADER_SELF_TEST"):
            from . import self_test

            self_test.run(app, controller, os.environ["FDPREADER_SELF_TEST"])
        code = app.exec()
        log.info("종료 (%s)", code)
    finally:
        service.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
