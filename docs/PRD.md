# FDP Reader PRD

> 2026-11-22 기준 기획 문서의 공개본임. 원본의 구조도·로드맵 그림은 빠져 있음.

작성일: 2026-11-22

## 1. 개요

일반 PDF 리더기 기능 전부에 "문서 위 영역 지정 → 트랙패드로 그 자리에 직접 서명" 기능을 더한 Windows 우선 개인용 PDF 리더기임. 제품명은 FDP Reader (For Document Player) — FDP는 PDF를 뒤집은 약자임.

**배경**

- 종이 출력 → 펜 서명 → 스캔 → 재전송 과정이 번거로움
- Windows용 리더기(Acrobat Reader, Edge 등)의 그리기 서명은 마우스·펜·터치 입력 기준임 → 펜이 없는 노트북에서는 마우스 드래그로 서명하게 되어 품질이 낮음
- macOS 미리보기(Preview)는 트랙패드 서명을 지원하나, 커서가 상자 중간에서 시작되고 손가락을 떼면 다음 획 위치를 알 수 없다는 불만이 반복됨 ([Apple 커뮤니티](https://discussions.apple.com/thread/256119658?page=2), [Apple 커뮤니티 2](https://discussions.apple.com/thread/251271046?page=3))
- 원인: 트랙패드를 상대 좌표(Relative, 커서 이동량) 입력으로 처리함 → 본 제품은 트랙패드 면 전체를 서명 영역에 1:1 대응시키는 절대 좌표(Absolute) 방식으로 차별화함

**목표**

1. 일반 리더기 수준의 보기·탐색·검색·주석·양식 기능 확보
2. 트랙패드 서명을 "영역 지정 → 서명 → 확정" 3단계 안에 끝냄
3. 포럼·리뷰에서 반복적으로 요청되는 기능(다크 모드, 탭, 읽던 위치 기억 등)을 기본 탑재함

**비목표 (1차 범위 제외)**

- 공인인증서 기반 Digital Signature (디지털 서명, PKI) 생성 — 이미지형 Electronic Signature (전자 서명)만 1차 지원, 디지털 서명은 v2 검토
- 본문 텍스트 재배치(Reflow) 수준의 전문 편집
- 계정·클라우드 동기화

## 2. 대상 사용자와 사용 시나리오

1차 사용자는 Windows 노트북으로 문서 서명·양식 작성·자료 읽기를 모두 하는 개인 사용자(개발자 본인 포함)임.

| 사용자 유형 | 주요 목적 | 핵심 기능 |
| --- | --- | --- |
| 서명이 잦은 학생·직장인 | 동의서·신청서·공문 서명 후 회신 | 트랙패드 서명, 서명 저장·재사용, 양식 작성 |
| 강의자료·논문을 오래 읽는 사용자 | 장시간 읽기, 필기, 요약 | 다크 모드, 하이라이트·메모, 참고문헌 미리보기 |
| 여러 문서를 동시에 다루는 사용자 | 비교·참조·병합 | 탭, 분할 보기, 페이지 편집 |

**주요 시나리오**

1. **최초 서명**: PDF 열기 → 서명란을 드래그해 영역 지정 → 트랙패드에 손가락으로 서명 → Enter로 확정 → 저장
2. **반복 서명**: 저장된 서명을 목록에서 골라 클릭 한 번으로 배치
3. **양식 제출**: 텍스트 필드·체크박스 입력 → 서명 → 편집 불가 사본으로 내보내기(Flatten, 평탄화)
4. **야간 자료 읽기**: 다크 모드로 열기 → 하이라이트·메모 → 다음에 열면 읽던 페이지에서 재개
5. **문서 비교**: 두 PDF를 탭으로 열고 좌우 분할 보기로 대조

## 3. 범위와 대상 플랫폼

1차 플랫폼은 Windows 10/11 x64로 한정함 — 트랙패드 서명이 Windows Precision Touchpad (정밀 터치패드)의 원시 터치 입력에 의존하기 때문임.

| 항목 | 1차 (MVP~v1) | 이후 검토 (v2+) |
| --- | --- | --- |
| OS | Windows 10/11 x64 | macOS, Windows ARM64 |
| 입력 장치 | Precision Touchpad, 마우스, 펜·터치스크린 | 스마트폰을 서명 패드로 연결 |
| 문서 포맷 | PDF (암호 걸린 PDF 포함) | EPUB, XPS, CBZ, 이미지 파일 열기 |
| UI 언어 | 한국어, 영어 | 추가 언어 |
| 배포 형태 | 설치판 + Portable (포터블) | Microsoft Store |
| 네트워크 | 없음 (완전 오프라인) | 선택적 업데이트 확인 |

- 등록 서명·문서는 외부로 전송하지 않음 (개인정보 원칙, 8절 참고)
- Precision Touchpad가 없는 기기는 마우스·펜 서명으로 대체함

## 4. 기능 요구사항 1 — 기본 리더기 기능

Acrobat Reader·Edge·SumatraPDF·PDF-XChange·Okular가 공통으로 제공하는 기능을 기준선으로 잡음. 우선순위는 P0 = MVP 필수, P1 = v1, P2 = v2 이후임.

| ID | 기능 | 요구 내용 | 우선순위 |
| --- | --- | --- | --- |
| V-01 | 파일 열기 | 대화상자, 드래그 앤 드롭, 기본 앱(연결 프로그램) 등록, 명령줄 인자 | P0 |
| V-02 | 암호 PDF | 사용자 암호 입력 후 열기, 권한(인쇄·복사 제한) 표시 | P0 |
| V-03 | 확대/축소 | 폭 맞춤, 페이지 맞춤, 실제 크기, Ctrl+휠, 트랙패드 핀치 | P0 |
| V-04 | 페이지 배치 | 단일, 연속 스크롤, 두 쪽 보기, 책 보기(표지 단독) | P0 |
| V-05 | 회전 | 보기 회전(90° 단위), 저장 시 페이지 회전 반영 선택 | P0 |
| V-06 | 목차 | PDF Outline (문서 내장 목차) 트리 표시·이동 | P0 |
| V-07 | 썸네일 | 페이지 썸네일 패널, 클릭 이동 | P0 |
| V-08 | 페이지 이동 | 페이지 번호 입력, Home/End/PgUp/PgDn | P0 |
| V-09 | 링크 | 내부·외부 링크 실행, 뒤로/앞으로(Alt+←/→) | P0 |
| V-10 | 검색 | 전체 텍스트 검색, 대소문자·단어 단위 옵션, 결과 목록 패널 | P0 |
| V-11 | 텍스트 선택·복사 | 드래그 선택, 더블·트리플 클릭, 복사 시 줄바꿈 정리 | P0 |
| V-12 | 영역 캡처 | 사각형 영역을 이미지로 클립보드 복사 | P1 |
| V-13 | 인쇄 | 범위·배율·양면·주석 포함 여부 선택 | P0 |
| V-14 | 탭 | 한 창에 여러 문서, Ctrl+Tab 전환, 탭 끌어서 새 창 | P0 |
| V-15 | 전체 화면·발표 모드 | F11 전체 화면, F5 발표 모드(도구 모두 숨김) | P1 |
| V-16 | 사용자 북마크 | 문서별 페이지 즐겨찾기 | P1 |
| V-17 | 최근 문서 | 최근 연 문서 목록, 고정(Pin) | P0 |
| V-18 | 키보드 단축키 | 기본 단축키 + 사용자 지정, Command Palette (명령 팔레트, Ctrl+K) | P1 |
| V-19 | 문서 속성 | 제목·작성자·PDF 버전·페이지 크기·글꼴 목록 표시 | P1 |
| V-20 | 첨부 파일 | PDF 내장 첨부 파일 목록·추출 | P2 |
| V-21 | 서명 검증 | 문서에 들어 있는 Digital Signature (디지털 서명) 유효성·변조 여부 표시 | P2 |

참고: [Edge PDF 리더 기능 목록](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-pdf), [SumatraPDF 명령 목록](https://www.sumatrapdfreader.org/docs/Commands.md), [Okular 소개](https://okular.kde.org/), [PDF-XChange 기능 개요](https://help.pdf-xchange.com/pdfxe11/features-overview.html)

## 5. 기능 요구사항 2 — 주석·양식·페이지 편집

모든 주석은 PDF 표준 Annotation (주석 객체)로 저장해 다른 리더에서도 보이게 함. 본문 텍스트·이미지 직접 편집은 비목표임.

| ID | 기능 | 요구 내용 | 우선순위 |
| --- | --- | --- | --- |
| A-01 | 텍스트 마크업 | Highlight (형광펜), Underline (밑줄), Strikeout (취소선), 색상 선택 | P0 |
| A-02 | 메모 | Sticky Note (점착 메모), 하이라이트에 메모 연결 | P0 |
| A-03 | 텍스트 상자 | Typewriter (타자기) — 양식 필드 없는 문서에 글자 입력 | P0 |
| A-04 | 펜 그리기 | Ink (자유 그리기), 굵기·색상, 펜 필압 반영 | P1 |
| A-05 | 도형·도장 | 사각형·원·선·화살표, Stamp (도장) — 체크·날짜·사용자 이미지 | P1 |
| A-06 | 주석 목록 | 문서 전체 주석을 패널에 모아 보기·필터·이동 | P1 |
| A-07 | 실행 취소 | 모든 주석·서명·페이지 편집에 Undo/Redo (Ctrl+Z/Y) | P0 |
| A-08 | 부분 지우개 | 획 전체가 아닌 닿은 부분만 지우는 지우개 | P2 |
| F-01 | 양식 입력 | AcroForm (PDF 대화형 양식) 텍스트·체크박스·라디오·드롭다운·날짜 필드 | P0 |
| F-02 | 서명 필드 연동 | 문서에 있는 서명 필드를 클릭하면 트랙패드 서명(6절)으로 바로 진입 | P0 |
| F-03 | 자동 입력 | 이름·학번·연락처 등 자주 쓰는 값 저장 후 필드에 채우기 | P1 |
| F-04 | 평탄화 | Flatten (평탄화) — 양식·주석·서명을 페이지 내용으로 굳혀 수정 불가 사본 저장 | P0 |
| P-01 | 페이지 관리 | 회전·삭제·순서 변경(썸네일 드래그)·추출·빈 페이지 삽입 | P1 |
| P-02 | 병합·분할 | 여러 PDF 합치기, 범위 지정 나누기, 이미지 → PDF | P1 |
| P-03 | 가리기 | Redaction (영구 가리기) — 텍스트·이미지를 실제 삭제 | P2 |
| P-04 | 암호 설정 | 열기 암호·권한 암호 설정 후 저장 | P2 |
| S-01 | 저장 방식 | 덮어쓰기 / 다른 이름으로 저장, 기본은 Incremental Save (증분 저장) | P0 |
| S-02 | 복구 | 비정상 종료 시 미저장 주석 자동 복구 | P1 |

- XFA 양식(구형 Adobe 전용 양식)은 미지원 — 열 때 안내 문구 표시
- 실행 취소는 Edge PDF 리더 사용자 포럼에서도 직접 요청된 항목임 ([Microsoft Tech Community](https://techcommunity.microsoft.com/t5/articles/microsoft-edge-extends-tools-for-the-pdf-reader/m-p/2002916))
- 부분 지우개·주석 목록·필압 펜은 Edge 로드맵의 사용자 요청 항목이었음 ([Edge 로드맵](https://techcommunity.microsoft.com/t5/articles/roadmap-for-pdf-reader-in-microsoft-edge/m-p/2175170))

## 6. 핵심 차별 기능 — 영역 지정 트랙패드 서명

트랙패드 면 전체를 지정한 서명 영역에 1:1로 대응시키는 절대 좌표 입력이 핵심임. 트랙패드 왼쪽 위 모서리를 누르면 서명 영역 왼쪽 위에 획이 시작되므로, 손가락을 떼도 다음 획 위치를 예측할 수 있음. macOS 미리보기의 시작 위치 문제(1절)를 구조적으로 피함.

### 6.1 사용자 흐름

1. **영역 지정**: 툴바 [서명] 또는 단축키 → 페이지 위를 드래그해 사각형 지정. 문서에 서명 필드가 있으면 필드 클릭으로 자동 지정
2. **서명 모드 진입**: 지정 영역을 크게 확대한 입력 창 표시, 트랙패드 비율의 안내 틀 표시, 커서 숨김·고정
3. **입력**: 한 손가락으로 트랙패드에 서명. 닿아 있는 동안만 획 기록, 떼면 획 종료
4. **수정**: Ctrl+Z 마지막 획 취소, Backspace 전체 지우기, 굵기·색상(검정·파랑) 선택
5. **확정**: Enter → 여백 자동 제거 후 비율 유지한 채 영역에 배치 → 이동·크기 조절 핸들 제공
6. **저장 여부**: "이 서명 저장" 선택 시 서명 목록에 추가. Esc는 언제나 취소 후 커서 복구

### 6.2 입력 처리 요구사항

| ID | 항목 | 요구 내용 | 우선순위 |
| --- | --- | --- | --- |
| T-01 | 장치 감지 | Raw Input (원시 입력) API로 Precision Touchpad (HID Usage Page 0x0D, Usage 0x05) 등록. 없으면 마우스·펜 서명으로 안내 | P0 |
| T-02 | 절대 좌표 매핑 | HID 보고서의 X/Y Logical Range (논리 범위)를 읽어 서명 영역에 대응. 가로세로비가 다르면 비율 유지(Letterbox) | P0 |
| T-03 | 접촉 판정 | Tip Switch (접촉 여부)와 Contact ID (접촉 번호)로 획 시작·끝 판단. 첫 손가락만 사용 | P0 |
| T-04 | 손바닥 무시 | Confidence (신뢰도) 비트가 꺼진 접촉(손바닥 등)은 제외 | P0 |
| T-05 | 커서 고정 | 서명 모드 동안 커서 숨김 + ClipCursor로 이동 제한, 탭·클릭 무시. Esc·Enter·무입력 30초 시 반드시 해제 | P0 |
| T-06 | 제스처 충돌 | 2손가락 스크롤·핀치는 서명 모드에서 무시. 3·4손가락 시스템 제스처는 앱에서 막기 어려우므로 안내 문구 표시 | P0 |
| T-07 | 떼는 순간 보정 | 손가락을 뗄 때 끝이 휘는 Hook (갈고리) 현상을 마지막 수 샘플 보정으로 제거 | P1 |
| T-08 | 획 다듬기 | 속도 기반 가변 굵기 Bézier (베지어) 보간 — 빠르게 그은 구간은 가늘게 | P0 |
| T-09 | 눌러서 쓰기 모드 | (선택) 가볍게 닿으면 위치 표시만, 트랙패드를 눌러 클릭 상태일 때만 그리기 — 첫 획 위치 맞추기용 | P1 |
| T-10 | 부분 다시 그리기 | 입력마다 창 전체가 아닌 서명 캔버스만 갱신 | P0 |

- Precision Touchpad의 HID 보고서 구조(디지타이저 Usage 정의, X/Y·Tip Switch·Confidence)는 [Microsoft 문서](https://learn.microsoft.com/windows-hardware/design/component-guidelines/touchpad-windows-precision-touchpad-collection)와 [디지타이저 Usage 표](https://learn.microsoft.com/en-us/previous-versions/windows/hardware/design/dn672278(v=vs.85)) 기준임
- 트랙패드 원시 입력으로 손글씨를 받는 선행 오픈소스 [windows-touchpad](https://github.com/ichisadashioko/windows-touchpad)는 RIDEV_INPUTSINK 등록·HidP 파싱 방식을 쓰며, 입력마다 UI 전체를 다시 그려 무거워진 문제를 기록함 → T-10의 근거
- Hook 현상은 Microsoft의 [터치패드 위치 정확도 테스트](https://learn.microsoft.com/en-us/windows-hardware/design/component-guidelines/touchpad-positional-accuracy---manual)에서도 확인 항목임 → T-07의 근거
- 가변 굵기 보간은 [signature_pad](https://github.com/szimek/signature_pad/blob/master/README.md)가 쓰는 Square의 Smoother Signatures 방식을 참고함

### 6.3 서명 데이터와 PDF 반영

- 저장 형식: 획 좌표 배열(0~1 정규화 + 시각) JSON — 벡터 유지, 해상도 무관
- 저장 위치: 로컬 앱 데이터, Windows DPAPI로 암호화. 저장 서명 사용 전 Windows Hello·PIN 확인 옵션(P2)
- 문서에 넣는 방식

| 방식 | 내용 | 장점 | 단점 | 적용 |
| --- | --- | --- | --- | --- |
| Stamp 주석 + 벡터 Appearance Stream (표시 스트림) | 서명을 벡터 그림으로 담은 주석 | 대부분 리더에서 동일하게 보임, 이동·삭제 가능 | 다른 사람도 삭제 가능 | 기본값 |
| Ink 주석 | 획을 InkList로 저장 | 향후 재편집 쉬움 | 리더마다 굵기 표현 차이 | 선택 |
| 페이지 평탄화 | 페이지 내용에 직접 기록 | 쉽게 분리·복사 안 됨 | 되돌리기 불가 | "서명본 내보내기" 시 |

### 6.4 대체 입력

- 마우스 드래그, 펜·터치스크린(필압 반영)
- 서명 이미지 불러오기 + 배경 자동 제거
- 타이핑 서명(필기체 글꼴) — Acrobat Reader도 그리기·타이핑·이미지 3가지를 제공함 ([Adobe](https://www.adobe.com/acrobat/pdf-reader.html?promoid=KSNEW))
- 손가락 대신 정전식 스타일러스로 트랙패드에 쓰면 더 정밀함 — 서명 모드 안내 문구에 포함 ([MacRumors](https://www.macrumors.com/how-to/digitally-sign-a-pdf-using-preview-on-mac))

### 6.5 법적 효력 고지

- 본 기능은 이미지형 전자 서명이며 인증서 기반 디지털 서명이 아님
- 2020년 전자서명법 전부개정으로 공인전자서명의 우월한 법적 효력이 폐지됨 ([정책브리핑](https://m.korea.kr/briefing/pressReleaseView.do?newsId=156391237)) — 인정 여부는 문서 수신처 요건에 따름
- 앱은 법적 효력을 보증하지 않는다는 문구를 최초 서명 시 1회 표시

## 7. 사용자 요구 기반 추가 기능

포럼·이슈 트래커·리뷰에서 가장 자주 보인 요구는 "가볍고 빠름", "제대로 된 다크 모드", "읽던 위치 기억", "탭·분할 보기", "선택 텍스트 번역·사전·읽어주기"였음. 아래 표는 요구 근거와 반영 방안임.

| ID | 기능 | 요구 근거 | 반영 방안 | 우선순위 |
| --- | --- | --- | --- | --- |
| U-01 | 가벼움·로그인 없음 | Acrobat 사용자들이 느린 시작, 업셀·로그인 요구를 불만으로 꼽음 ([UserVoice](https://acrobat.uservoice.com/forums/590923-acrobat-for-windows-and-mac/suggestions/51194563-adobe-must-be-stopped), [Adobe 커뮤니티](https://community.adobe.com/questions-9/too-much-with-the-online-accounts-1301901)) | 계정·광고·업셀 없음, 완전 오프라인, 시작 시간 목표는 8절 | P0 |
| U-02 | 페이지 다크 모드 | 배경만 어두워지는 것이 아니라 페이지 자체를 어둡게 해달라는 요청 ([Kavita #1523](https://www.github.com/Kareadita/Kavita/issues/1523)). 단순 색 반전은 이미지에서 잘 안 맞음 ([SumatraPDF](https://www.github.com/sumatrapdfreader/sumatrapdf/releases)) | 글자·배경만 반전하고 사진·그림은 원색 유지, 세피아·회색 테마, UI 다크 모드는 OS 설정 따름 | P0 |
| U-03 | 읽던 위치·세션 복원 | 문서가 직전 페이지를 기억하고 열려 있던 탭을 복원해달라는 요청 ([Zotero 포럼](https://forums.zotero.org/discussion/comment/376958/)), Edge도 View Recovery를 로드맵에 올림 ([Edge](https://techcommunity.microsoft.com/t5/articles/roadmap-for-pdf-reader-in-microsoft-edge/m-p/2175170)) | 문서별 마지막 페이지·확대율·보기 모드 저장, 재시작 시 탭 복원 | P0 |
| U-04 | 분할 보기·별도 창 | 여러 문서 동시 보기 요청 ([Zotero 포럼](https://forums.zotero.org/discussion/comment/376958/)), 독립 창으로 나란히 두고 싶다는 요청 ([Edge 포럼](https://techcommunity.microsoft.com/t5/articles/roadmap-for-pdf-reader-in-microsoft-edge/m-p/2188372)) | 좌우·상하 분할, 같은 문서의 두 위치 동시 보기, 탭을 끌어 새 창 | P1 |
| U-05 | 선택 텍스트 번역·사전·검색 | SumatraPDF "필수 기능" 요청에 사전·웹 검색 포함 ([#2761](https://github.com/sumatrapdfreader/sumatrapdf/discussions/2761)), 우클릭 번역 요청 ([Zotero 포럼](https://forums.zotero.org/discussion/124973/feature-request-translation-option-for-selected-text-in-pdf-reader)) | 우클릭·단축키 → 번역(브라우저 연결)·사전 팝업·웹 검색. 외부 전송은 사용자가 누를 때만 | P1 |
| U-06 | 소리 내어 읽기 | SumatraPDF 필수 기능 요청, Edge가 Read Aloud 기본 제공 ([Edge](https://www.microsoft.com/edge/features/pdf-reader?form=+)) | Windows 내장 음성 사용, 읽는 문장 표시, "여기부터 읽기" | P1 |
| U-07 | 주석 Markdown 내보내기 | 하이라이트를 원문 위치 링크와 함께 Markdown으로 뽑고 싶다는 요청 ([Zotero 포럼](https://forums.zotero.org/discussion/comment/385946/)) | 하이라이트·메모를 페이지 번호·색상별로 정리해 Markdown·텍스트 파일로 내보내기 | P1 |
| U-08 | 링크·참고문헌 미리보기 | 참고문헌·그림 링크에 마우스를 올리면 내용을 띄우고, 이동 후 되돌아오는 버튼 요청 ([Zotero 위시리스트](https://forums.zotero.org/discussion/89559/pdf-reader-wishlist-make-it-understand-scientific-publications)) | 내부 링크 대상 영역을 팝업으로 미리보기, 떠 있는 [돌아가기] 버튼 | P1 |
| U-09 | 하이라이트 표현 설정 | 하이라이트 투명도·두께 조절 요청 ([Zotero 포럼](https://forums.zotero.org/discussion/comment/377236)) | 색상 팔레트·투명도·두께 사용자 지정 | P2 |
| U-10 | 리플로우 읽기 모드 | 데스크톱에서도 리플로우를 원하는 요청 ([Zotero 포럼](https://forums.zotero.org/discussion/comment/511130/)), Xodo는 리플로우 모드 제공 ([App Store](https://apps.apple.com/kr/app/%ED%95%9C%EA%B8%80-%EC%8A%A4%EC%BA%90%EB%84%88-%EB%AA%A8%EB%B0%94%EC%9D%BC-%EB%B7%B0%EC%96%B4-%EB%B0%8F-%ED%8E%B8%EC%A7%91%EA%B8%B0-xodo-pdf/id805075929)) | 본문 텍스트를 추출해 글자 크기 조절 가능한 읽기 화면 제공 | P2 |
| U-11 | OCR (문자 인식) | 스캔 PDF는 텍스트가 없어 선택·번역이 안 됨 ([Mozilla](https://bugzilla.mozilla.org/show_bug.cgi?id=1917620)) | 한국어·영어 로컬 OCR 후 검색 가능한 텍스트 층 추가 | P2 |
| U-12 | 가장자리 클릭 넘김 | 화면 좌우 끝을 눌러 페이지를 넘기는 옵션 요청 ([Kavita #1523](https://www.github.com/Kareadita/Kavita/issues/1523)) | 설정에서 켜기, 태블릿 모드에서 기본 켜짐 | P2 |
| U-13 | AI 요약·질문 (선택) | Acrobat은 AI Assistant를 유료 추가 기능으로 판매하나 ([Adobe](https://www.adobe.com/products/reader/)), "AI 말고 기본 기능부터"라는 불만도 있음 ([Adobe 커뮤니티](https://community.adobe.com/t5/acrobat-discussions/why-does-it-feel-like-acrobat-gets-worse-with-every-update/m-p/14581152/highlight/true)) | 기본 꺼짐, 사용자 API 키, 전송 내용 매번 확인 후 실행 | P2 |

- 실행 취소(Ctrl+Z)도 Edge·Zotero 양쪽에서 반복 요청되어 5절 A-07을 P0로 둠
- 서명 여러 개 저장은 macOS 미리보기도 제공하는 기능임 ([MacRumors](https://www.macrumors.com/how-to/digitally-sign-a-pdf-using-preview-on-mac)) → 6절 서명 목록에 반영

## 8. 비기능 요구사항

아래 수치는 본 제품의 목표값이며, 측정 기준 기기는 개발자 본인의 Windows 노트북(SSD)임.

| 구분 | 요구 내용 | 목표값 |
| --- | --- | --- |
| 성능 | 앱 시작 + 100쪽 문서 첫 페이지 표시 | 1초 이내 |
| 성능 | 페이지 이동·확대 후 선명한 화면 | 100ms 이내 (그동안 저해상도 미리보기) |
| 성능 | 트랙패드 입력 → 획 표시 지연 | 16ms 이내 (60Hz 1프레임) |
| 성능 | 1,000쪽 문서 메모리 사용 | 500MB 이하, 보이는 페이지만 렌더링 |
| 안정성 | 손상된 PDF | 강제 종료 없이 오류 안내, 복구 가능한 페이지는 표시 |
| 안정성 | 저장 | 임시 파일에 쓴 뒤 교체 (저장 중 종료되어도 원본 유지) |
| 안정성 | 서명 모드 오류 | 어떤 경우에도 커서 제한·숨김 자동 해제 |
| 보안 | 네트워크 | 기본 통신 없음, 텔레메트리(사용 통계 전송) 없음 |
| 보안 | PDF JavaScript | 실행하지 않음 (양식 계산은 안전한 범위만 v2 검토) |
| 보안 | 외부 링크·첨부 실행 | 열기 전 주소·파일명 확인 창 |
| 보안 | 서명 데이터 | DPAPI 암호화, 삭제 시 즉시 파기 |
| 접근성 | 조작 | 키보드만으로 모든 기능 사용, 고대비 테마, UI 배율 100~200% |
| 접근성 | 화면 낭독기 | UI Automation (UI 자동화) 지원 |
| 호환성 | 저장 결과 | 주석·서명·양식값이 Acrobat Reader·Edge·Chrome에서 같게 보일 것 |
| 호환성 | 한글 | 텍스트 상자·양식·검색에서 한글 IME 정상 동작, 한글 글꼴 임베딩 |
| 배포 | 포터블 모드 | 설정·서명을 실행 파일 옆 폴더에 저장, 레지스트리 미사용 |

## 9. 기술 스택·아키텍처 제안

권장안은 Python + PySide6 + PyMuPDF임 — 005_ScreenAsk와 같은 스택이고, 렌더링·주석·양식·병합을 한 라이브러리로 처리함. 단, 공개 배포 계획이 있으면 라이선스 때문에 엔진 선택을 다시 판단해야 함.

| 안 | 구성 | 장점 | 단점 |
| --- | --- | --- | --- |
| A (권장) | Python + PySide6 + PyMuPDF | 개발 속도, 기존 스택 재사용, 주석·양식 쓰기 API 풍부, EPUB·XPS·CBZ도 열림 | AGPL — 배포 시 소스 공개 또는 Artifex 상용 라이선스 필요 ([MuPDF 라이선스](https://mupdf.readthedocs.io/en/1.27.0/license.html)) |
| B | Python + PySide6 + pypdfium2 | PDFium(Chrome이 쓰는 엔진), Apache-2.0/BSD-3로 배포 자유로움 ([PyPI](https://pypi.org/project/pypdfium2/2.6.0/)) | 주석·저장 API가 저수준이라 직접 구현량 많음 |
| C | C# + WinUI 3 + PDFium | Windows 네이티브 UI, Win32 호출 쉬움 | 개발 속도 느림, 새 스택 학습 필요 |
| D | Tauri/Electron + PDF.js | 웹 기술, 크로스 플랫폼 | 트랙패드 원시 입력에 네이티브 모듈 필요, Electron은 용량 큼 |

**권장안(A) 구조** (그림은 원본 문서 참고)

```
UI 층 (PySide6) — 메인 창 · 탭 · 분할 보기 · 패널 · 단축키
 ├─▶ 문서 코어 (엔진 어댑터) — 열기·텍스트 추출·검색 / 주석·양식·페이지 편집·저장 / 타일 렌더 캐시
 │     └─▶ PDF 엔진 (교체 가능) — PyMuPDF (권장 · AGPL) | pypdfium2 (대안 · Apache/BSD)
 └─▶ 서명 모듈 (features/sign)
       트랙패드 입력 (Raw Input · HidP 파싱 · 손바닥 제외)
        ▶ 획 처리 (절대 좌표 매핑 · 스무딩 · Hook 보정)
        ▶ 서명 캔버스 (입력 창 부분 다시 그리기 · 미리보기)
        ▶ 배치 · 저장 (영역 맞춤 · DPAPI 암호화 서명 목록) ──Stamp 주석으로 배치──▶ 문서 코어
```

트랙패드 입력은 서명 모듈 안에서만 처리되고, 문서에는 마지막 단계에서 Stamp 주석으로만 기록됨.

**설계 원칙**

- PDF 엔진은 Engine Adapter (엔진 어댑터) 인터페이스 뒤에 둠 → A에서 B로 교체 가능하게 함
- 렌더링은 백그라운드 스레드에서 타일 단위 수행, UI 스레드는 캐시된 타일만 그림
- 트랙패드 입력은 Qt의 nativeEvent에서 WM_INPUT을 받고, ctypes로 RegisterRawInputDevices·GetRawInputData·HidP_* (hid.dll) 호출 → 지연이 목표(16ms)를 넘으면 이 부분만 C 확장 모듈로 분리
- 서명 모듈은 문서 코어와 분리해 단독 테스트 가능하게 함 (입력 기록 재생으로 회귀 테스트)

**폴더 구조 초안**

```
app/            메인 창, 탭, 패널, 단축키
core/document/  엔진 어댑터 (열기·렌더·텍스트·주석·저장)
core/render/    타일 캐시, 렌더 스레드
features/sign/  touchpad_input, stroke_processor, sign_canvas, signature_store
features/annot/ 주석 도구
features/forms/ 양식 입력·자동 입력
features/pages/ 페이지 편집·병합
storage/        설정, 세션, 최근 문서, 읽던 위치
```

## 10. 우선순위와 릴리스 계획

MVP는 P0 기능만 담고, 각 단계는 게이트 기준을 통과해야 다음 단계로 넘어감. 날짜는 미정임. (그림은 원본 문서 참고)

**MVP — 읽기 + 트랙패드 서명 (P0 전체)**

- 보기·탐색·검색·인쇄·탭
- 하이라이트·메모·텍스트 상자
- 양식 입력·평탄화·실행 취소
- 트랙패드 서명 (절대 좌표·커서 고정)
- 서명 저장·재사용 (DPAPI 암호화)
- 페이지 다크 모드·읽던 위치 복원

**게이트 1** — 최초 서명 30초 이내 · Acrobat·Edge·Chrome 표시 일치

**v1 — 편집·생산성 (P1)**

- 펜·도형·도장·주석 목록
- 페이지 관리·병합·분할
- 눌러서 쓰기 모드·Hook 보정
- 분할 보기·명령 팔레트
- 번역·사전·소리 내어 읽기
- Markdown 내보내기·링크 미리보기

**게이트 2** — 기본 PDF 앱으로 2주 실사용 · 8절 성능 목표 충족

**v2 — 확장 (P2)**

- OCR·리플로우 읽기
- 가리기·암호 설정
- 부분 지우개·하이라이트 설정
- 디지털 서명(PKI)·서명 검증 검토
- macOS 지원
- AI 요약·질문 (선택, 기본 꺼짐)

게이트 기준은 12절 성공 지표에서 가져옴. 단계별 상세 기능은 4~7절 표의 우선순위 열(P0·P1·P2)을 따름.

## 11. 위험 요소와 미결 사항

가장 큰 위험은 기기별 트랙패드 차이와 서명 모드 중 커서 제어 실패임 — 둘 다 MVP 초기에 프로토타입으로 먼저 검증해야 함.

| 위험 | 영향 | 대응 |
| --- | --- | --- |
| Precision Touchpad가 아닌 구형 드라이버(제조사 전용) 기기 | 원시 좌표를 못 받아 트랙패드 서명 불가 | 감지 실패 시 마우스·펜 서명 자동 전환, 확인된 기기 목록 관리 |
| 서명 중 커서 이동·시스템 제스처 간섭 | 획 외 동작 발생, 창 전환 | 커서 숨김·제한, 3·4손가락 제스처는 안내 문구로 대응 |
| 커서 제한 상태에서 앱 멈춤 | 사용자가 PC를 조작하지 못함 | 감시 타이머로 자동 해제, Esc 전역 처리 |
| 손가락 서명 품질 한계 | 트랙패드 서명은 스캔본보다 품질이 낮다는 평가 ([Apple 커뮤니티](https://discussions-jp-prz.apple.com/thread/256119658)) | 스무딩, 큰 입력 창, 스타일러스 안내, 이미지 가져오기 대체 |
| 다른 리더에서 서명·주석이 다르게 보임 | 제출한 문서에서 서명 누락 가능 | Appearance Stream 항상 생성, 테스트 PDF 세트로 교차 확인 |
| AGPL 라이선스 | 공개 배포 시 전체 소스 공개 의무 | 개인용 유지 또는 엔진 어댑터로 pypdfium2 교체 |
| 악성 PDF | 렌더링 엔진 취약점 경유 공격 | JavaScript 미실행, 엔진 정기 업데이트 |
| 범위 과대 | MVP 지연 | P0만 MVP에 포함, P1·P2는 단계별 추가 |

**미결 사항**

- [x] 제품명 — FDP Reader (For Document Player), 개발 폴더 `006_FDPReader_code`
- [ ] 공개 배포 여부 — 엔진·라이선스 결정 요인
- [ ] 서명 확정 시 기본 방식(Stamp 주석 vs 평탄화)
- [ ] macOS 지원 시점
- [ ] 개발 기기의 트랙패드가 Precision Touchpad인지 확인 (설정 → 터치패드에서 "정밀 터치패드" 문구 확인)

## 12. 성공 지표

텔레메트리가 없으므로 모든 지표는 개발자 본인의 수동 테스트와 사용 기록으로 측정함.

| 지표 | 목표 | 측정 방법 |
| --- | --- | --- |
| 최초 서명 완료 시간 (영역 지정 → 저장) | 30초 이내 | 스톱워치, 10회 평균 |
| 저장 서명 재사용 시간 | 5초 이내 | 스톱워치, 10회 평균 |
| 서명 1회당 전체 지우기 횟수 | 평균 1회 이하 | 로컬 디버그 로그 |
| 획 시작 위치 오차 | 영역 폭의 5% 이내 | 격자 점 찍기 테스트 (목표 점 vs 실제 점) |
| 다른 리더 표시 일치 | 테스트 PDF 20종 전부 | Acrobat Reader·Edge·Chrome으로 열어 비교 |
| 성능 | 8절 목표값 충족 | 자체 벤치마크 스크립트 |
| 실사용 | 기본 PDF 앱으로 2주 이상 사용 | 불편 사항 메모 후 다음 단계 백로그 반영 |

## 13. 참고 자료

**페이지를 직접 열어 확인한 자료**

- [Zotero — PDF Reader Wishlist](https://forums.zotero.org/discussion/89559/pdf-reader-wishlist-make-it-understand-scientific-publications)
- [SumatraPDF — Must have features #2761](https://github.com/sumatrapdfreader/sumatrapdf/discussions/2761)
- [PDF-XChange Editor — Features Overview](https://help.pdf-xchange.com/pdfxe11/features-overview.html)
- [ichisadashioko/windows-touchpad](https://github.com/ichisadashioko/windows-touchpad)

**검색 결과 발췌로 확인한 자료 (원문 전체는 미확인)**

- 트랙패드·입력: [Precision Touchpad Collection](https://learn.microsoft.com/windows-hardware/design/component-guidelines/touchpad-windows-precision-touchpad-collection), [디지타이저 Usage 표](https://learn.microsoft.com/en-us/previous-versions/windows/hardware/design/dn672278(v=vs.85)), [위치 정확도 테스트](https://learn.microsoft.com/en-us/windows-hardware/design/component-guidelines/touchpad-positional-accuracy---manual), [signature_pad](https://github.com/szimek/signature_pad/blob/master/README.md)
- macOS 미리보기 서명: [Apple 커뮤니티 1](https://discussions.apple.com/thread/256119658?page=2), [Apple 커뮤니티 2](https://discussions.apple.com/thread/251271046?page=3), [MacRumors](https://www.macrumors.com/how-to/digitally-sign-a-pdf-using-preview-on-mac)
- 기존 리더 기능: [Edge PDF 리더](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-pdf), [Edge 로드맵](https://techcommunity.microsoft.com/t5/articles/roadmap-for-pdf-reader-in-microsoft-edge/m-p/2175170), [SumatraPDF 명령](https://www.sumatrapdfreader.org/docs/Commands.md), [SumatraPDF 릴리스](https://www.github.com/sumatrapdfreader/sumatrapdf/releases), [Okular](https://okular.kde.org/), [Acrobat Reader](https://www.adobe.com/acrobat/pdf-reader.html?promoid=KSNEW)
- 사용자 요구: [Kavita #1523](https://www.github.com/Kareadita/Kavita/issues/1523), [Zotero — 긴 문서 탐색](https://forums.zotero.org/discussion/comment/376958/), [Zotero — Markdown 내보내기](https://forums.zotero.org/discussion/comment/385946/), [Zotero — 번역 요청](https://forums.zotero.org/discussion/124973/feature-request-translation-option-for-selected-text-in-pdf-reader), [Edge — 실행 취소 요청](https://techcommunity.microsoft.com/t5/articles/microsoft-edge-extends-tools-for-the-pdf-reader/m-p/2002916), [Acrobat UserVoice](https://acrobat.uservoice.com/forums/590923-acrobat-for-windows-and-mac/suggestions/51194563-adobe-must-be-stopped)
- 라이선스·법규: [MuPDF 라이선스](https://mupdf.readthedocs.io/en/1.27.0/license.html), [pypdfium2](https://pypi.org/project/pypdfium2/2.6.0/), [전자서명법 전부개정 보도자료](https://m.korea.kr/briefing/pressReleaseView.do?newsId=156391237)
