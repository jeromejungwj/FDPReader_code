"""수동 점검: 앱이 멈춰도 커서 잠금이 풀리는지 실제 커서로 확인.

    python -m tests.cursor_check

단추를 누르면 4초 동안 일부러 멈춤. 커서가 2초 안에 다시 움직여야 정상.
자동 테스트에 넣지 않음: 포커스와 마우스를 실제로 가져가기 때문.
"""

import threading
import time

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from features.sign import cursor_guard

HANG = 4.0


def main() -> None:
    app = QApplication([])
    window = QWidget()
    window.setWindowTitle("FDP Reader 커서 잠금 점검")
    label = QLabel("단추를 누른 뒤 마우스를 계속 움직여 보세요. (4초 동안 일부러 멈춤)")
    button = QPushButton("멈춤 시험 시작")
    layout = QVBoxLayout(window)
    layout.addWidget(label)
    layout.addWidget(button)

    def run() -> None:
        guard = cursor_guard.CursorGuard()
        if not guard.lock(cursor_guard.window_center(int(window.winId()))):
            label.setText("잠그지 못함: 이 창이 앞에 있을 때 다시 눌러 주세요.")
            return
        began, released = time.monotonic(), []
        locked = cursor_guard.current_clip()

        def watch() -> None:
            while time.monotonic() - began < HANG:
                if cursor_guard.current_clip() != locked:
                    released.append(time.monotonic() - began)
                    return
                time.sleep(0.02)

        thread = threading.Thread(target=watch)
        thread.start()
        time.sleep(HANG)  # 멈춘 척
        thread.join()
        guard.close()
        if released:
            label.setText(f"통과: 멈춘 지 {released[0]:.1f}초 만에 커서가 풀림")
        else:
            label.setText("실패: 멈춘 동안 커서가 풀리지 않음")
        print(label.text())

    button.clicked.connect(run)
    window.resize(520, 140)
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
