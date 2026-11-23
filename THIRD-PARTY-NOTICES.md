# 제3자 구성요소 / Third-party notices

FDP Reader 자체는 [GNU AGPL-3.0](LICENSE)으로 배포됨. 설치판(exe)에는 아래 구성요소가 들어 있음.

| 구성요소 | 라이선스 | 소스 |
|---|---|---|
| PyMuPDF 1.28.2 / MuPDF (Artifex) | AGPL-3.0 (`LICENSE`) | https://github.com/pymupdf/PyMuPDF , https://mupdf.com |
| PySide6 6.12.0 / Shiboken6 / Qt 6 (The Qt Company) | LGPL-3.0 (`licenses/LGPL-3.0.txt`, `licenses/GPL-3.0.txt`) | https://code.qt.io , https://download.qt.io/official_releases/qt/ |
| Python 3.14 (Python Software Foundation) | PSF License (`licenses/Python-PSF.txt`) | https://www.python.org |
| PyInstaller 부트로더 | GPL-2.0 + 부트로더 예외 | https://github.com/pyinstaller/pyinstaller |

- Qt·PySide6 는 exe 와 분리된 DLL 로 들어 있어 같은 버전대의 다른 빌드로 바꿔 넣을 수 있음 (LGPL-3.0 §4)
- FDP Reader 의 전체 소스: https://github.com/jeromejungwj/FDPReader_code
- 맑은 고딕 등 글꼴은 포함하지 않음 — Windows 에 있는 글꼴을 사용함
