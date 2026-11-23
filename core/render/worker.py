"""렌더 프로세스.

MuPDF 는 스레드에 안전하지 않고 렌더 중 GIL 도 잡으므로 스레드 대신 프로세스로 분리함.
악성·손상 PDF 로 렌더러가 죽어도 본체는 살아 있음.
"""

from __future__ import annotations

from collections import OrderedDict

KEEP_OPEN = 4
SHRINK_EVERY = 64  # PyMuPDF 1.28 의 store_size() 는 미구현(None)이라 횟수로 비움


def serve(conn) -> None:
    import pymupdf as mu

    from core.document import engine

    opened: OrderedDict[str, tuple[int, engine.Renderer]] = OrderedDict()

    rendered = 0

    def drop(path: str) -> None:
        if path in opened:
            opened.pop(path)[1].doc.close()

    while True:
        try:
            op, *args = conn.recv()
        except (EOFError, OSError):
            return  # 본체가 끝남
        if op == "close":
            drop(args[0])
            continue

        job, (path, length, version, password), pno, scale, clip, theme = args
        try:
            if path not in opened or opened[path][0] != version:
                drop(path)
                with open(path, "rb") as f:
                    data = f.read(length)
                opened[path] = (version, engine.Renderer(engine.open_pdf(data, password)))
            opened.move_to_end(path)
            while len(opened) > KEEP_OPEN:
                drop(next(iter(opened)))
            result = opened[path][1].render(pno, scale, clip, theme)
        except Exception:
            result = None
        try:
            conn.send((job, result))
        except (OSError, ValueError):
            return
        rendered += 1
        if rendered % SHRINK_EVERY == 0:
            mu.TOOLS.store_shrink(60)
