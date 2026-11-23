# FDP Reader (For Document Player)

트랙패드로 지정 영역에 서명하는 개인용 Windows PDF 리더기임. 요구사항은 [docs/PRD.md](docs/PRD.md) 기준이며, 현재 **MVP(P0) 구현 · 손가락 서명 확인 · 게이트 1 검증 전** 상태임 (0.1.1 미리보기).

## 0. 설치 (Windows 10/11 x64)

1. [Releases](https://github.com/jeromejungwj/FDPReader_code/releases)에서 `FDPReader-Setup-<버전>.exe` 받기
2. 실행 → 관리자 권한 없이 현재 사용자에게 설치됨 (`%LOCALAPPDATA%\Programs\FDP Reader`)
   - 코드 서명이 없어 "Windows의 PC 보호" 창이 뜰 수 있음 → **추가 정보 → 실행**
3. 제거: Windows 설정 → 앱 → FDP Reader
   - 설정·저장 서명(`%LOCALAPPDATA%\FDPReader`)은 남음. 지우려면 그 폴더를 직접 삭제

## 1. 실행

- 설치판: 시작 메뉴 **FDP Reader**
- 소스에서: `run.bat` 더블클릭 (Python 3.14 필요, 첫 실행 때 `.venv` 생성). PDF를 `run.bat` 위에 끌어다 놓아도 열림
- 오류로 창이 안 뜨면 `run_debug.bat` 또는 `%LOCALAPPDATA%\FDPReader\fdpreader.log` 확인
- 기본 PDF 앱으로 쓰기: 앱 메뉴 **설정 → PDF 연결 프로그램으로 등록** → 이어서 열리는 Windows 설정에서 선택
- 포터블: `FDPReader.exe`(소스는 `run.bat`) 옆에 빈 파일 `portable.flag`를 두면 설정·서명을 `data\`에 저장하고 레지스트리 등록 메뉴를 숨김
  - 서명은 DPAPI 암호화라 다른 PC·계정에서는 복호화되지 않음

## 2. 서명

1. **서명**(`Ctrl+E`) → 서명란 드래그 (서명 필드는 클릭)
2. 트랙패드에 한 손가락으로 서명 — 트랙패드 면 전체가 파란 틀과 1:1 대응
3. `Enter` 확정 → 이동·크기 조절 → `Ctrl+S` 저장

| 서명 창 키 | 동작 |
|---|---|
| `Enter` / `Esc` | 확정 / 취소 |
| `Ctrl+Z` / `Backspace` | 마지막 획 취소 / 전체 지우기 |
| `W` / `C` | 굵기 / 색 |
| `S` | 이 서명 저장 켜기·끄기 (기본 켬, 마지막 선택을 기억) |
| `M` | 트랙패드 ↔ 마우스·펜 |
| `Space` | 커서 고정이 풀렸을 때 이어서 쓰기 |

- 커서 고정은 Esc·Enter·30초 무입력·창 전환·앱 멈춤·강제 종료 시 풀림
- 저장 서명·이미지·타이핑 서명: 서명 단추 옆 ▾
- 놓은 서명·텍스트 상자·메모를 클릭 → `Ctrl+C` → 붙일 자리에 마우스를 두고 `Ctrl+V` (같은 문서 안에서만. 다른 문서에는 저장된 서명으로 넣음)
- 이미지형 전자 서명이며 인증서 기반 디지털 서명이 아님

## 3. 주요 단축키

| 키 | 동작 |
|---|---|
| `Ctrl+O` / `S` / `Shift+S` / `P` | 열기 / 저장 / 다른 이름 저장 / 인쇄 |
| `Ctrl+Shift+E` | 서명본 내보내기 (평탄화) |
| `Ctrl+F`, `F3` | 찾기, 다음 |
| `Ctrl+H` / `U` / `Shift+X` / `M` / `T` | 형광펜 / 밑줄 / 취소선 / 메모 / 텍스트 상자 |
| `Ctrl+1` / `2` / `3` | 실제 크기 / 폭 맞춤 / 쪽 맞춤 |
| `Ctrl+Alt+1`~`4` | 단일 / 연속 / 두 쪽 / 책 보기 |
| `Ctrl+R`, `Ctrl+D` | 보기 회전, 다크 모드 |
| `Alt+←` / `→`, `Ctrl+Tab` | 뒤로 / 앞으로, 탭 전환 |
| `Tab`, `Enter`, 방향키, `Shift+방향키` | 필드·주석·링크 순회, 실행, 이동, 크기 조절·글자 선택 |
| `F4`, `F6` | 옆 패널, 문서로 포커스 |

## 4. 검증 상태 (2026-11-23, Galaxy Book 960XGK)

### 확인함

- 실제 손가락 서명 동작: 사용자 확인 ("잘 됩니다"). 세부 지표는 아래 미확인
- 앱 멈춤 시 커서 해제: `tests.cursor_check` 실제 커서로 사용자 확인 (감시 프로세스 수정 뒤)
- 배치한 서명 모서리 끌어 크기 조절: 2026-11-23 수정 후 사용자 확인
- 최초 서명 30초 이내: 사용자 체감으로 충족 (2026-11-23). 스톱워치 10회 평균 측정은 아님
- Precision Touchpad 맞음 — 5점, 2320×1640, 가로세로비 1.415 (PRD 11절 미결 사항 해소), Raw Input 등록·해제 성공
- 자동 테스트 100개: `.venv\Scripts\python -m unittest`
- 표시 일치
  - 테스트 PDF 20종: MuPDF ↔ PDFium(Chrome 엔진) 비교에서 큰 차이 없음
    - 흐림 처리한 흑백 화면에서 밝기 차 45/255 초과 픽셀 기준. 픽셀 동일·색 일치를 뜻하지 않음
  - 그중 암호 없는 17종: 실제 Edge에서 육안 확인 (자동 생성 문서, 마지막 양식·렌더 수정 전)
  - 예제 동의서: 실제 Chrome·Edge에서 저장본 확인, Edge에서 평탄화본 확인
- 손상 PDF 1,500개 변형: 강제 종료 0건
- pythonw + 파일 인자 실행, 두 번째 실행 → 기존 창에 새 탭
- 설치판 0.1.0: 빌드 중 오프스크린 점검, 이 PC에 조용히 설치 → 실제 화면에서 첫 쪽 렌더·감시 프로세스 점검 → 제거 후 남은 파일·항목 없음
- 설치판 0.1.1: 빌드 중 오프스크린 점검만 (설치 스크립트는 0.1.0과 같음)

### 성능 (`.venv\Scripts\python -m tests.benchmark`, 최종 5회)

| 항목 | 목표 | 측정 범위 | 통과 |
|---|---|---|---|
| 시작 + 100쪽 첫 페이지 | 1000ms | 894~1159ms | **2/5 — 미달** |
| 쪽 이동 (최악) | 100ms | 84~91ms | 5/5 |
| 확대 (최악) | 100ms | 93~99ms | 5/5 (여유 거의 없음) |
| 접촉 → 획 그리기 | 16ms | 0.8~3.2ms | 5/5 |
| 1,000쪽 메모리 | 500MB | 290~292MB | 5/5 |

- 다른 프로그램이 CPU를 8~85% 쓰는 상태의 offscreen 측정임 → 유휴 상태에서 재측정 필요
- 시작 시간은 Python·Qt import가 약 40%라 부하에 민감함
- 획 그리기는 앱 처리 시간만이며 하드웨어 → 화면 전체 지연은 아님

### 아직 확인 못 함 (사람·장치 필요)

- [ ] 손가락 서명 세부 — 시작 위치 오차(5%), 제스처 간섭, 전체 지우기 횟수
- [ ] 서명 저장 기본 켬, 서명 복사·붙여넣기 (2026-11-23 사용자 신고로 추가, 실제 화면 확인 전)
- [ ] 유휴 상태에서 시작 1초 목표
- [ ] 최초 서명 30초(스톱워치 10회 평균)·재사용 5초 (PRD 12절)
- [ ] **게이트 1: Acrobat·Edge·Chrome 표시 일치** (Acrobat은 이 PC에 미설치)
  - `.venv\Scripts\python -m tests.make_corpus` → `build\corpus\`에 시험 PDF 20종 + 평탄화본 3종 + 기준 PNG + `검사표.md`
  - 각 PDF를 세 리더로 열어 같은 이름의 PNG와 비교하고 검사표에 기록
- [ ] 실제 프린터 출력 (PDF 파일 출력만 확인)
- [ ] 한글 IME 조합 입력, 트랙패드 핀치, 탭 끌어내기, 펜 필압
- [ ] 연결 프로그램 등록 (레지스트리를 바꾸므로 실행하지 않음)
- [ ] 고대비, UI 배율 100·200%, 화면 낭독기, 영어 UI 화면
- [ ] XFA 안내, 디지털 서명된 실제 문서
- [ ] `run.bat` 최초 설치 경로 (개발 venv는 PC에 있던 패키지를 복사해 만듦)

## 5. 범위

- 구현: PRD의 P0 전체 + 6.4 대체 입력(마우스·펜·이미지·타이핑)
- 미구현
  - P1·P2 전부
  - 설치판 (PRD 3절 배포 형태 — 패키징 도구 필요)
  - 터치스크린 한 손가락 스크롤
  - 본문 전체에 대한 UI Automation (현재 쪽 글만 설명으로 제공)
  - 양식 계산 스크립트 (JavaScript 미실행)
- PRD 미결 사항의 현재 기본값
  - 서명 방식: Stamp 주석 (메뉴에서 Ink 선택 가능, 평탄화는 내보내기)
  - 배포: 개인용 전제 — PyMuPDF가 AGPL이므로 공개 배포 시 재판단

## 6. 구조

```
app/              창, 탭, 문서 보기(page_view), 조작(interaction), 패널, 인쇄, 단일 실행
core/document/    엔진 어댑터 — PyMuPDF 는 여기서만 사용
core/render/      렌더 프로세스와 요청 큐
features/sign/    트랙패드 입력, 접촉 판정, 획 처리, 커서 고정·감시, 서명 보관함
features/annot/   타자기·메모 입력
features/forms/   양식 입력기
storage/          설정, 세션, 원자적 파일 쓰기
tests/            자동 테스트, benchmark, cursor_check(수동)
packaging/        설치판 빌드 (build.py, Inno Setup 스크립트, 제3자 라이선스 원문)
docs/             기획 문서 (PRD)
```

### 설치판 빌드

1. `.venv\Scripts\python -m pip install -r requirements-build.txt`
2. [Inno Setup 6](https://jrsoftware.org/isinfo.php) 설치 (현재 사용자용이면 `%LOCALAPPDATA%\Programs\Inno Setup 6`에서 찾음)
3. `.venv\Scripts\python packaging\build.py` → `dist\FDPReader-Setup-<버전>.exe`
   - 버전은 `app/__init__.py`의 `__version__`
   - 빌드 중 만든 exe를 화면 없이 띄워 첫 쪽 렌더·커서 감시 프로세스를 점검함 (`FDPREADER_SELF_TEST`)

## 7. 고칠 때 주의 — 실측으로 확인한 엔진·리더 함정

| 함정 | 대응 |
|---|---|
| PyMuPDF 1.28은 같은 핸들로 증분 저장 두 번 하면 파일이 0쪽으로 깨짐 | 편집 1회 = 새 핸들 + 저장 1회, Undo = 파일 자르기 (`document.py`) |
| Journal(실행 취소) 중 `get_new_xref` 등이 예외 | Journal을 쓰지 않음 |
| `page.transformation_matrix`가 회전 + CropBox에서 어긋남 | `engine.page_matrix`만 사용 |
| 타일마다 화면 전체를 다시 그리면 장당 5~10ms | 도착한 타일 자리만 갱신 |
| 렌더 중 GIL을 잡음 | 스레드가 아닌 프로세스로 렌더 |
| `TOOLS.store_size()`가 항상 None | 렌더 횟수로 캐시 비움 |
| MuPDF가 미서명 필드에 빨간 "SIGN"을 그리고 평탄화에도 넣음 | `hide_sign_tags` — 사본에서만 |
| 회전된 쪽의 Text 주석 위치가 리더마다 다름 | 회전 시 메모를 Stamp로 저장 |
| Edge는 글자 크기 자동(0)이면 표시 스트림을 무시 | 입력 시 크기를 고정하고 자동이었다는 표시를 남김 |
| MuPDF식 체크 글리프가 Adobe 엔진에서 네모로 깨짐 | 벡터 체크로 교체 |
| 서명 주석에 Contents가 있으면 Edge가 말풍선 표시 | Subj 사용 |
| NeedAppearances 양식은 리더가 제멋대로 다시 그림 | 첫 입력 때 직접 그리고 플래그 끔 |
| ClipCursor는 앞 창일 때만 유지되고 다른 앱 잠금과 전역으로 공유됨 | 본체·감시 프로세스 모두 내 잠금일 때만 해제, 확인 못 하면 푸는 쪽 |
| PageView 의 속성 이름이 EditView 메서드를 가려 실행 중에만 터짐 (`_resized` → 서명 크기 조절 불가였음) | `test_no_attribute_hides_a_method` 가 막음 |
| 이 PC의 편집 훅이 보이지 않는 유니코드(BOM 등)를 소스에서 지움 | 문자 대신 `chr(...)`·16진 표기 사용 |

## 8. 라이선스

- FDP Reader: [GNU AGPL-3.0](LICENSE) — PDF 엔진 PyMuPDF(MuPDF)가 AGPL-3.0이라 같은 조건으로 공개함
- 설치판에 들어 있는 구성요소와 각 라이선스: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)
- 이미지형 전자 서명이며 인증서 기반 디지털 서명이 아님. 법적 효력은 보증하지 않음
