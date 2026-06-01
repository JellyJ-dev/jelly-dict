# jelly dict 개발 메모

macOS용 영어/일본어 단어 정리 앱. 네이버 사전 조회 결과를 Excel에 저장하고, 필요하면 Anki 파일로 내보낸다. UI는 PySide6/QSS 기반이며 별도 프론트엔드 프레임워크는 쓰지 않는다.

현재 릴리스 버전은 `2.0`이다. 공개 버전 표기는 `README.md`, `Install jelly dict.command`, `app_files/jelly_dict/pyproject.toml`, `app_files/packaging/macos/Info.plist`에서 같은 값으로 유지한다.

## 현재 방향

- 메인 화면은 `jelly dict` 타이틀, 작은 단어 입력 박스, 단어장/최근 단어 패널 중심의 다크 미니멀 UI.
- 실패 로그와 디버그 정보는 메인 화면에 노출하지 않고, 메뉴의 개발자 도구에서만 확인한다.
- 최근 단어와 영어/일본어 단어장은 같은 메인 카드 안에서 전환한다.
- 최근 단어와 단어장 모드는 같은 확장 버튼을 쓴다. 확장해도 행 포맷은 유지하고, 상단 입력 영역만 접어 UI가 흔들리지 않게 한다.
- 단어장 모드는 별도 창이 아니라 메인 카드 안에서 검색, 상세 조회, 수정, 재조회, 선택 삭제, Anki 내보내기를 처리한다.
- 최근 단어 목록은 선택 강조를 쓰지 않는다. 더블클릭 또는 Enter로 상세만 열고, 저장 단어가 삭제되면 최근 목록에서도 자동으로 사라진다.
- 마지막으로 열어둔 화면(`최근 단어`, 영어 단어장, 일본어 단어장)과 단어장 정렬 기준은 SQLite `app_state`에 저장해 다음 실행 때 복원한다.
- 삭제 후에는 작은 반투명 되돌리기 toast를 띄우고, 버튼 또는 `Command+Z`로 바로 복원할 수 있게 한다.
- 사진 OCR은 보조 입력 수단이다. 텍스트 입력/조회/저장 흐름을 대체하지 않는다.
- 앱 UI 문구에는 내부 구현 방식이 드러나는 표현을 쓰지 않는다. 사용자에게는 `네이버 사전`, `조회`, `사전 소스` 같은 표현만 노출한다.
- 배포/설치 UX도 같은 원칙을 따른다. installer 화면에는 내부 설치 엔진, `런처`, `packaging` 같은 내부 구현 설명을 노출하지 않고, 사용자가 할 행동과 결과만 보여준다.

## 실행

일반 사용자용 첫 실행:

```bash
./Install\ jelly\ dict.command
```

설치가 끝난 뒤 실행 앱 이름은 `Jelly Dict.app`이다.

```text
~/Applications/Jelly Dict.app
```

repo 안에서만 실행할 경우 생성 위치는 다음이다.

```text
app_files/dist/Jelly Dict.app
```

개발자 직접 실행:

```bash
./app_files/scripts/run.sh
```

의존성 재설치가 필요할 때:

```bash
./app_files/scripts/quickstart.sh
```

내부 quickstart 스크립트는 설치 방식을 지원한다.

- `--mode venv`: 앱 폴더의 `.venv` 사용. 기본값이며 권장.
- `--mode local`: 현재 `python3` 환경에 직접 설치.

선택값은 `app_files/jelly_dict/.install_mode`에 저장하고, `run.sh`가 같은 모드로 실행한다. `.install_mode`는 사용자 로컬 상태이므로 커밋하지 않는다.

초기 설정 완료 후 `app_files/jelly_dict/.quickstart_ok`를 기록한다. 앱 시작 시 이 파일이 없거나 현재 앱 경로와 맞지 않으면 실행 전에 환경 복구를 시도한다. `.quickstart_ok`는 사용자 로컬 상태이므로 커밋하지 않는다.

macOS 초기 환경 검사는 다음을 포함한다.

- 공개 루트/내부 앱 폴더 구조 확인
- 비-macOS 실행 차단
- Python 3.11 이상 확인
- `pip`/`venv` 사용 가능 여부 확인
- 앱 폴더 쓰기 권한 확인
- 디스크 여유 공간 경고
- 폴더 이동으로 깨진 `.venv` 감지
- 필수 Python 패키지 존재 여부와 버전 확인
- Playwright WebKit 설치 확인
- macOS quarantine 속성 경고
- Rosetta 실행 경고

PySide6는 `>=6.7,<6.11`로 설치한다. Qt 6.11 계열은 macOS 앱 실행 직후 QThread 정리 중 segfault가 확인되어 제외한다. Python 3.13 + PySide6 6.10 조합도 일부 macOS 26 환경에서 `.app` 실행 시 Cocoa platform plugin 생성 단계에서 abort가 확인되어, installer는 Python 3.12/3.11만 선택한다. 내부 quickstart 스크립트의 패키지 검증도 같은 범위를 기준으로 한다.

installer 시작 시 라이선스 동의를 먼저 받는다. 앱 자체는 MIT이고, 외부 의존성과 선택 TTS 음성은 각 라이선스/약관을 따르며, 설치/실행/생성물 사용 책임은 관련 라이선스와 약관에 따라 사용자에게 있다는 점을 설치 전에 명확히 보여준다. `quickstart.sh --check`는 검증용이라 동의 프롬프트 없이 동작하고, 실제 설치는 `--accept-license`가 없으면 직접 동의를 받는다.

installer는 시작 직후와 설치 완료 후에 공개 루트 구조를 검증한다. 구조가 맞지 않으면 “원래 배포본과 다르다”는 안내와 함께 설치를 중단하고, 의도한 수정이 아니라면 재다운로드 또는 `git pull` 후 재실행을 권장한다. 사용자가 별도 명령을 칠 필요는 없다.

배포/다운로드용 루트 구조:

```text
jelly-dict/
├── Install jelly dict.command
├── Run jelly dict.command
├── README.md
└── app_files/
```

일반 사용자는 루트의 `Install jelly dict.command`만 누르면 된다. `Run jelly dict.command`는 개발자/문제 해결용으로 남긴다. 루트의 별도 quickstart starter는 배포하지 않고, 내부 `app_files/scripts/quickstart.sh`만 설치/복구 엔진으로 유지한다. `app_files/`는 앱 실행에 필요한 소스, 스크립트, 라이선스, 아이콘, 패키징 파일을 모아둔 내부 폴더다. 개발 체크아웃에는 `dev.md`가 있지만 배포 폴더에는 포함하지 않는다.

최상위 Finder 첫 화면에는 사용자에게 필요한 `.command` 파일과 `README.md`, `app_files/`만 둔다. 내부 자산은 모두 `app_files/` 아래에 둔다.

```text
app_files/
├── assets/
│   ├── app-icon-1024.png
│   └── app-icon.icns
├── design/
│   └── jelly-dict-icon-flat.svg
├── packaging/
│   └── macos/
│       ├── Info.plist
│       ├── build_app.sh
│       ├── launcher.sh
│       └── make_icns.sh
├── scripts/
└── jelly_dict/
```

`assets/`, `packaging/`, `design/`, `dist/`, `docs/` 같은 내부/생성 폴더를 repo 최상위에 다시 만들지 않는다. 앱 번들 생성물은 `app_files/dist/` 아래에만 둔다.

### macOS 앱 설치 흐름

`Install jelly dict.command`는 내부 quickstart 기능을 자체 UI 안에서 수행한다. 별도 starter 파일이나 추가 터미널 창을 띄우지 않는다.

- 라이선스 확인
- 기존 앱 감지
  - `~/Applications/Jelly Dict.app`이 있으면 `재설치 / 기존 앱 실행 / 닫기`
  - `app_files/dist/Jelly Dict.app`만 있으면 `Applications에 설치 / dist 앱 실행 / 재생성 / 닫기`
  - `기존 앱 실행` / `dist 앱 실행`은 앱 파일 존재만 믿고 바로 열지 않는다. 먼저 `quickstart.sh --check`를 실행하고, 실패하면 앱을 열지 않고 설치/복구 흐름으로 돌린다.
- 환경 점검
- 환경 정상 시 `앱 설치 계속 / 환경 정리·재설치 / 닫기`
- 환경 문제 또는 정리 후 의존성 설치
- `app_files/dist/Jelly Dict.app` 생성
- `~/Applications` 복사 여부 질문
- 완료 후 실행 여부 질문

installer UI는 기존 quickstart 화면의 디자인 원칙을 유지한다.

- 같은 워드마크, 색상, bordered header, 선택 UI, spinner를 사용한다.
- 최소 터미널 크기 80x24 기준으로 각 단계가 스크롤 없이 보여야 한다.
- 단계마다 화면을 clear 후 다시 그린다.
- 긴 로그는 화면에 풀어 쓰지 않고 로그 경로만 표시한다.
- 의존성/TTS 설치처럼 오래 걸리는 단계는 단순 spinner만 보여주지 않는다. `quickstart.log`를 읽어서 같은 화면 안에 `단계`, `현재 항목`, progress bar, 퍼센트, 로그 경로를 고정 영역으로 표시한다.
- pip/Playwright의 상세 출력은 로그에만 남기고, installer 화면은 5줄 고정 진행 영역만 갱신해 스크롤을 만들지 않는다.
- 설치 시작 시 `app_files/jelly_dict/.install_incomplete`를 만들고, 설치 성공 시에만 지운다. 사용자가 다운로드/설치 중간에 끊으면 다음 installer 실행에서 중단된 설치를 감지하고 `.venv`, `.install_mode`, `.python_cmd`, `.quickstart_ok`, `.install_incomplete`만 정리한 뒤 재설치로 보낸다.
- 사용자 화면에는 내부 구현 방식 설명을 노출하지 않는다.

`Jelly Dict.app` 자체 실행 시에는 별도 Terminal 창이 뜨면 안 된다. `app_files/packaging/macos/launcher.sh`는 다음 순서로 동작한다.

- `Contents/Resources/repo_path.txt`에서 원본 repo 위치 읽기
- `app_files/scripts/quickstart.sh --check`를 실행하고 결과를 `quickstart.log`에 남김
- 정상일 때 `app_files/scripts/run.sh` 실행
- 문제가 있으면 `quickstart.sh --accept-license`로 조용히 복구 시도
- 복구 성공 시 `run.sh` 실행
- 복구 실패 시에도 `run.sh`를 마지막으로 한 번 직접 시도한다. Finder/LaunchServices 환경에서 `quickstart --check`만 false-negative가 나는 경우 앱 실행을 막지 않기 위함이다.
- 마지막 실행까지 실패하면 macOS dialog로 `Install jelly dict.command` 재실행과 `quickstart.log` / `app.log` 위치만 안내

앱 실행 과정에서 `Terminal.app`, `osascript tell application "Terminal"`, `do script`를 사용하지 않는다.
installer가 앱을 실행할 때는 `open -n`을 사용해 이미 떠 있는 예전 실패 다이얼로그를 다시 활성화하지 않고 새 앱 인스턴스를 연다.

앱 이름은 사용자-facing 영역에서 `Jelly Dict`를 쓴다.

- 번들명: `Jelly Dict.app`
- `CFBundleDisplayName`: `Jelly Dict`
- `CFBundleName`: `Jelly Dict`
- 실행 파일명은 내부용으로 `jelly-dict` 유지

경로 계산은 항상 실행 중인 스크립트 위치 기준으로 한다. repo를 다른 곳에 clone/download해도 동작해야 한다.

- `Install jelly dict.command`: repo root 기준
- `app_files/packaging/macos/build_app.sh`: `SCRIPT_DIR/../../..`로 repo root 계산
- `app_files/packaging/macos/make_icns.sh`: `SCRIPT_DIR/../../..`로 repo root 계산
- `.app` 내부 `repo_path.txt`: 설치 당시 repo root 절대경로 저장

repo 위치를 옮기면 기존 `.app`의 `repo_path.txt`가 틀어지므로 installer를 다시 실행해야 한다.

사용자 사전 데이터는 repo 밖에 있다.

```text
~/Documents/jelly-dict/
```

이 폴더와 그 안의 `vocab*.xlsx`, `*.apkg`는 installer, cleanup, 패키징 구조 정리에서 삭제하면 안 된다. 초기 설치 재현을 위해 지울 수 있는 것은 repo 내부의 `.venv`, 설치 마커, 앱 번들 생성물뿐이다.

`Install jelly dict.command`의 환경 정리 메뉴에는 사용자 사전 데이터 삭제 옵션을 두지 않는다. installer에서 접근 가능한 정리 범위는 최대 `.venv`/설치 마커, repo 내부 런타임 데이터, Playwright 캐시까지다.

개발자가 배포 폴더를 만들 때만 내부 도구를 실행한다.

```bash
./app_files/scripts/make_user_package.sh
```

생성된 사용자 배포 폴더는 처음 보이는 위치에 `Install jelly dict.command`, `Run jelly dict.command`, `README.md`만 두고, 나머지 파일은 `app_files/` 안에 둔다. `dev.md`와 `make_user_package.sh`는 개발용이므로 배포 폴더에는 포함하지 않는다.

검증:

```bash
app_files/jelly_dict/.venv/bin/python -m pip install -r app_files/jelly_dict/requirements-dev.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPYCACHEPREFIX=/private/tmp/jelly_dict_pycache \
app_files/jelly_dict/.venv/bin/python -m pytest app_files/jelly_dict/tests
```

마지막으로 확인된 전체 테스트 결과는 `262 passed, 3 warnings`이다. 최소 검증으로는 변경 UI 파일에 대해 `python -m py_compile`, `git diff --check`, 관련 pytest 묶음, 필요 시 오프스크린 렌더 캡처를 수행한다.

## 주요 구현 상태

### 메인 UI

- `app/ui/word_input_view.py`
  - 단어 입력, 언어 선택, OCR 모델 선택, 사진 입력, 조회 버튼을 작은 입력 패널 안에 둔다.
  - 조회 버튼은 입력값이 있을 때만 나타나며, 조회 중에는 느린 원형 스피너와 `조회 중` 상태로 대체된다.
  - 입력 패널 컨트롤은 텍스트 버튼 + 통일된 화살표 스타일을 쓴다.
  - 사진 버튼과 Anki 버튼은 배경 없는 선형 SVG 아이콘을 사용하고, hover 시 텍스트/아이콘이 함께 강조된다.
  - 최근 단어는 작은 리스트로 표시하고 더블클릭 시 상세 페이지를 연다. 최근 단어는 선택 가능한 삭제 대상이 아니므로 주황색 선택 강조를 쓰지 않는다.
  - 조회 대기열(Queue): 여러 단어가 차례로 조회되거나 대기할 때 검색 패널 하단에 `queuePanel`이 나타나며, 조회 중인 항목은 `진행`, 대기 중인 항목은 회색 칩, 실패 항목은 `실패` 칩으로 실시간 상태를 보여준다.
  - 각 queue 항목은 `LookupJob.id`를 가진다. 취소/재시도 signal은 단어 문자열이 아니라 job id 기준으로 처리하여 같은 단어가 언어별로 대기열에 있어도 개별 조작이 가능하다.
  - 대기 중인 칩은 클릭하여 개별 취소한다. 실패 칩은 클릭하면 재시도하고, 우클릭하면 대기열에서 삭제한다. 조회 중인 칩은 실제 비동기 워커 스레드 제어 안전을 위해 클릭 및 호버 스타일을 차단하여 조회 상태만 표현한다.
  - 실패 항목이 있으면 queue 헤더에 `실패 재시도`, `실패 지우기`를 표시한다. 실패 항목은 queue 안에 보류되며, pending 항목만 순차 조회 대상으로 다시 진행된다.
  - 대기열은 최대 10개(`MAX_VISIBLE_CHIPS`)까지만 칩으로 표시한다. 초과 분량은 `+ 외 N개` 요약 칩으로 대체하며, 클릭 시 숨겨진 항목을 재시도/취소/삭제할 수 있는 메뉴를 연다.
  - 단어장 모드에서는 검색창, 행별 수정/삭제, 선택 삭제 단축키, Anki 내보내기, 확장 버튼을 표시한다.
  - 확장 버튼은 최근 단어와 단어장 모드 모두에서 동작한다.
  - 확장 시 상단 타이틀과 입력 패널만 부드럽게 접고, 검색창은 유지해 레이아웃 꿀렁임을 막는다. 패널 너비는 유지하고 높이만 키운다.
  - 단어장 리스트와 주요 ScrollArea는 직접 그린 pill scrollbar를 써서 macOS/offscreen 스타일에서도 각진 막대가 보이지 않게 한다.

### 단어장 표시

- 단어장은 엑셀 표처럼 보이지 않게 카드형 리스트로 표시한다.
- 인라인 단어장과 별도 단어장 창 모두 정렬 옵션을 제공한다.
  - `최신순`: Excel 행 순서를 역순(`reversed()`)으로 렌더링하여 새로 추가된 단어를 위에 표시한다.
  - `오래된순`: Excel 행 순서 그대로 표시한다.
  - `가나다순`: 단어 문자열 기준으로 정렬한다.
- 영어 단어장 행:
  - 위: 영어 단어
  - 아래: 뜻 요약
- 일본어 단어장 행:
  - 위: 일본어 표기 또는 한자 + 발음
  - 아래: 뜻 요약
- 행 내부는 수직 레이아웃으로 두고, 뜻 요약이 가로 너비를 최대한 쓰도록 한다.
- 다중 의미 요약은 UI 표시에서 `1.뜻 2.뜻 3.뜻` 형식을 쓴다.
- 단일 의미는 번호 없이 자연스럽게 표시한다.
- Excel/Anki 저장 데이터는 UI 요약 포맷 때문에 변경하지 않는다.
- 더블클릭 시 `EntryDetailDialog`로 상세 조회한다.

### 단어장 검색/삭제/내보내기

- 메인 단어장 모드에서 `단어 / 뜻 검색...`으로 즉시 필터링한다.
- 여러 항목 선택 후 `선택 삭제`가 가능하다.
- 선택된 단어장 항목을 한 번 클릭하면 double-click interval 이후 선택 해제한다. 더블클릭은 선택 해제 timer를 취소하고 상세 페이지를 연다.
- 삭제 시:
  - Excel 행 삭제
  - SQLite 캐시 항목 삭제
  - 최근 조회 목록에서 같은 단어 삭제
  - AnkiConnect가 켜져 있으면 Anki 카드 삭제도 시도
- 삭제 후 현재 단어장 모드를 다시 로드하고, 작은 하단 toast로 `N개를 삭제했습니다`와 되돌리기를 표시한다.
- 사용자는 toast 버튼 또는 `Command+Z`로 방금 삭제한 Excel/캐시 항목을 복원할 수 있다.
- `Anki 내보내기`는 현재 단어장을 APKG 파일로 다시 생성한다.
- 영어/일본어 Excel 경로가 같은 파일을 가리켜도 내보내기는 요청 언어 행만 포함한다.
- APKG import 중복 방지를 위해 Anki 모델 ID와 note GUID는 안정적으로 유지한다.

### Anki 카드 디자인

- 일본어 Anki 카드의 헤드워드는 기준선이 흔들리지 않아야 한다.
  - 앞면은 요미가나 영역을 보이지 않게 예약하고, 뒷면은 같은 위치에 요미가나를 표시한다.
  - `정답 보기` 시 한자/가나 본문이 아래로 밀리면 안 된다.
- 일본어 요미가나는 작은 보조 텍스트가 아니라 헤드워드의 일부처럼 충분히 크게 표시한다.
- 요미가나 정렬은 단순히 reading 전체를 한 줄로 위에 올리는 방식이 아니다.
  - `漏らす`처럼 한자 + kana suffix 구조면 `も`는 `漏` 위에, `ら`/`す`는 각각 `ら`/`す` 위에 맞춘다.
  - `寄り`, `盗む`처럼 한자 어간 + kana 끝부분 구조도 같은 원칙으로 표시한다.
  - `臆病`처럼 한자 묶음 전체에 하나의 reading이 붙는 경우에는 reading 전체를 한자 묶음 위에 중앙 정렬한다.
- 긴 요미가나가 붙어도 base 글자 간격을 벌리면 안 된다.
  - base 글자 폭은 원래 글자 폭을 기준으로 유지한다.
  - 요미가나는 absolute overlay처럼 위에 얹어야 하며, 요미가나 문자열 폭이 다음 base 글자를 밀면 안 된다.
- 일본어 headword variant 정책:
  - 네이버가 `盗む·偸む`, `蘇る·甦る`처럼 중간점으로 여러 표기를 반환해도 카드에는 하나만 표시한다.
  - 사용자가 입력한 표기가 반환된 variant 중 하나면 그 표기를 저장/표시한다.
  - 사용자가 입력한 표기가 variant에 없거나 활용형 등으로 판단되면 사전 lemma를 저장한다.

### 상세 페이지

- `app/ui/entry_detail_dialog.py`
  - 최근 단어 또는 단어장 항목 더블클릭 시 상세 정보 표시.
  - Anki 카드 스타일에 맞춰 어두운 헤더와 밝은 본문 카드로 표시한다.
  - 영어는 발음/품사/뜻을 과도하게 반복하지 않도록 정리한다.
  - `source_provider == unknown` 같은 내부 fallback 값은 사용자에게 표시하지 않는다.
  - 일본어 표기가 여러 개면 대표 표기 중심으로 보여준다.
  - 예문, 관련어, 품사별 뜻 그룹을 읽기 쉬운 세로 흐름으로 표시한다.

### 개발자 도구

- `app/ui/developer_tools_dialog.py`
  - 메뉴 `보기 > 개발자 도구`
  - 단축키 `Cmd/Ctrl+Shift+I`
  - `.jelly_dict/logs/app.log` 표시
  - 새로고침, 로그 복사, 로그 파일 위치 열기, 닫기 버튼
- 일반 사용자가 볼 필요 없는 실패 로그는 메인 화면에 두지 않는다.

### 사진 OCR

- `app/ocr/`
  - `OcrProvider`, `OcrResult`, `OcrToken` 모델과 provider factory를 둔다.
  - 기본 provider는 `apple_vision`이며 macOS Vision 로컬 OCR을 사용한다.
  - `google_vision`은 사용자가 직접 API 키를 설정한 경우에만 동작한다. 이 모드는 이미지가 Google Vision API로 전송된다는 점을 설정/문서에서 명확히 고지한다.
  - 붙여넣기 이미지는 `.jelly_dict/ocr_clipboard/` 아래 임시 파일로만 저장한다.
  - OCR 닫기, 새 OCR 교체, 앱 종료, 다음 앱 시작 시 OCR temp 파일을 삭제한다.
  - 파일 선택/드롭은 사용자가 고른 원본 path만 읽고 내부 복사본을 만들지 않는다.
- `app/ui/ocr_worker.py`
  - OCR 실행은 `QThread` worker에서 처리해 UI 입력 흐름을 막지 않는다.
  - 실패는 모달 없이 transient status overlay와 로그로만 남긴다.
- 이미지 입력:
  - 파일 선택
  - 입력 패널 드래그 앤 드롭
  - 클립보드 이미지 붙여넣기
- 후보 후처리:
  - 빈 토큰, 문장부호만 있는 토큰, 중복 토큰을 제거한다.
  - 영어/일본어 후보는 유지하고 최대 노출 수를 제한한다.
- OCR 후보 chip:
  - 클릭 시 선택/해제 토글.
  - 여러 개 선택 가능.
  - 마지막으로 선택한 후보는 입력창에 채운다.
  - 더블클릭 시 후보 텍스트를 직접 수정한다.
  - 우클릭 시 후보를 삭제한다.
  - `선택/전체 후보 조회` 버튼은 선택된 후보가 있으면 선택 후보만, 선택된 후보가 없으면 전체 후보를 queue에 등록한다.
  - 여러 후보를 선택한 뒤 조회하면 선택 순서대로 한 단어씩 queue에 등록하고 순차 조회한다.
  - 각 조회 사이에는 1초 지연을 둔다.
- OCR은 자동 저장을 하지 않는다. 사용자가 후보를 고르고 조회를 실행해야 기존 조회/저장 흐름을 탄다.

### 설정

- `app/ui/settings_view.py`
  - Excel/Anki 경로 필드는 긴 경로를 볼 수 있도록 폭을 키움.
  - 설정창은 메인 UI와 같은 다크 카드 톤, 라벨/입력 중앙 정렬, 통일된 버튼 스타일을 사용한다.
  - 사전 소스 표기는 사용자 문구 기준으로 정리.
  - 캐시 사용, 저장 전 미리보기, 중복 처리, 요청 간격, AnkiConnect 설정 유지.
  - AnkiConnect 연결 테스트와 Google Vision 키 테스트는 `QThread` worker에서 실행해 설정창 UI를 막지 않는다.

## 핵심 파일

UI:

- 메인 윈도우/조회 큐: `app_files/jelly_dict/app/ui/main_window.py`
- 메인 입력/단어장 카드: `app_files/jelly_dict/app/ui/word_input_view.py`
- 상세 페이지: `app_files/jelly_dict/app/ui/entry_detail_dialog.py`
- 개발자 도구: `app_files/jelly_dict/app/ui/developer_tools_dialog.py`
- 설정 창: `app_files/jelly_dict/app/ui/settings_view.py`
- 기존 별도 단어장 다이얼로그: `app_files/jelly_dict/app/ui/word_list_view.py`
- 단어장 행 위젯: `app_files/jelly_dict/app/ui/widgets/wordbook_row.py`
- 언어 메뉴 행 위젯: `app_files/jelly_dict/app/ui/widgets/language_menu_item.py`
- QSS 테마: `app_files/jelly_dict/app/ui/resources/theme.qss`
- UI 아이콘: `app_files/jelly_dict/resources/icons/`

조회/OCR:

- 조회 서비스: `app_files/jelly_dict/app/services/lookup_service.py`
- OCR 서비스: `app_files/jelly_dict/app/ocr/`
- OCR 워커: `app_files/jelly_dict/app/ui/ocr_worker.py`
- 모델/표시 helper: `app_files/jelly_dict/app/core/models.py`

저장/내보내기:

- 저장 서비스: `app_files/jelly_dict/app/services/save_service.py`
- Excel 쓰기: `app_files/jelly_dict/app/storage/excel_writer.py`
- Excel 읽기: `app_files/jelly_dict/app/storage/excel_reader.py`
- Excel 직렬화: `app_files/jelly_dict/app/storage/excel_serializer.py`
- 캐시: `app_files/jelly_dict/app/storage/cache_store.py`
- APKG/TSV 내보내기: `app_files/jelly_dict/app/services/export_service.py`
- Anki 삭제 동기화: `app_files/jelly_dict/app/services/anki_sync_service.py`
- AnkiConnect 클라이언트: `app_files/jelly_dict/app/anki/ankiconnect_client.py`

컨트롤러:

- export / wordbook 컨트롤러: `app_files/jelly_dict/app/ui/controllers/`

## 데이터 흐름

일반 조회:

```text
입력
  -> 언어 감지 또는 강제 언어
  -> 캐시 확인
  -> 네이버 사전 조회
  -> 미리보기 여부 확인
  -> 중복 처리
  -> Excel 저장
  -> 캐시/최근 단어 갱신
```

사진 OCR 보조 입력:

```text
사진 선택/드롭/붙여넣기
  -> Apple Vision 로컬 OCR
  -> 후보 후처리
  -> 후보 chip 표시
  -> 후보 선택
  -> 입력창에 마지막 선택 후보 채움
```

OCR 다중 조회:

```text
후보 여러 개 선택
  -> 조회
  -> 1번째 단어 조회/저장
  -> 1초 대기
  -> 다음 단어 조회/저장
  -> 큐가 빌 때까지 반복
```

단어장 삭제:

```text
메인 단어장 선택
  -> 선택 삭제
  -> Excel delete_entries
  -> entries_cache 삭제
  -> recent_lookups 삭제
  -> AnkiConnect 활성 시 카드 삭제 시도
  -> 단어장 재로드
  -> 되돌리기 toast / Command+Z 복원
```

Anki 파일 내보내기:

```text
단어장 모드
  -> Anki 내보내기
  -> 저장 경로 선택
  -> 요청 언어 행만 필터링
  -> 현재 Excel 단어장 기준 APKG 재생성
  -> cache는 meaning_groups/examples 보강용으로만 사용
```

TTS 포함 APKG 내보내기:

```text
Excel row
  -> entry 구성 (Excel 값 우선)
  -> TTS cache key(language, engine, voice, text, bitrate, sample_rate)
  -> cache hit면 mp3 재사용
  -> cache miss면 mp3 생성
  -> APKG media_files에는 같은 mp3를 한 번만 포함
```

내보내기 중에는 앱 종료를 막는다. genanki 패키징 중 강제 종료되면 반쯤 작성된 APKG나 스레드 정리 문제가 생길 수 있기 때문이다.

## UI/UX 원칙

- 메인 화면은 사전 앱이라기보다 조용한 작업 도구처럼 보여야 한다.
- 에러/실패/디버그 텍스트는 메인 작업 흐름에서 제거한다.
- 사용자가 즉시 조치해야 하는 저장 실패 같은 문제만 최소 메시지로 알린다.
- 네트워크/파싱 실패는 transient status overlay와 로그에 남긴다.
- 중복 처리처럼 사용자의 선택이 필요한 흐름은 다이얼로그를 유지한다.
- 단어장과 최근 단어는 같은 패널에서 통일된 카드 리스트로 보여준다.
- 확장 모드는 최근 단어와 단어장 모두에서 쓸 수 있는 집중 보기다. 입력창/타이틀을 숨기고 리스트 높이만 키우며 검색창은 유지한다.
- 버튼, 아이콘, 화살표는 같은 색상/두께/hover 강도를 유지한다.
- 버튼 hover는 레이아웃 크기를 흔들지 않고 배경/테두리/텍스트 밝기만 바꾼다.
- 모든 주요 전환은 팍 튀지 않게 짧은 애니메이션을 사용한다.
- 불필요한 버튼형 UI보다 텍스트 버튼과 낮은 대비의 컨트롤을 우선한다.
- OCR UI는 이미지가 있을 때만 보조 영역으로 노출한다. 기본 텍스트 입력 경험을 대체하지 않는다.
- OCR temp는 장기 보관하지 않는다. 실패한 OCR도 사용자가 OCR을 지우거나 앱을 닫으면 삭제한다.
- 최근 단어 목록에는 선택 상태를 시각 강조로 남기지 않는다. 삭제/수정 대상 선택은 단어장 모드에서만 표현한다.
- 하단 상태/되돌리기 UI는 overlay로 띄워 전체 레이아웃 높이를 바꾸지 않는다.

## 디자인 토큰

- 배경: `#1b1b1a`
- 입력/패널: `#2a2a28`, `#242422`
- 내부 행: `#20201f`
- 테두리: `#454542`, `#3f3f3c`
- 기본 텍스트: `#e7e1d6`
- 보조 텍스트: `#aaa59c`, `#c8c1b7`
- 포인트 컬러: `#e8744f`
- 대표 폰트: `"Apple SD Gothic Neo"`, `"Helvetica Neue"`

## 2026-05-25 변경 메모

### 설치 / macOS 앱 번들

- `Install jelly dict.command`를 일반 사용자의 첫 진입점으로 확정했다.
- installer는 quickstart를 별도 창으로 띄우지 않고, 같은 터미널 UI 철학 안에서 라이선스 확인, 환경 점검, 복구/재설치, 앱 번들 생성, `~/Applications` 복사를 처리한다.
- 기존 앱이 있을 때는 `재설치 / 기존 앱 실행 / 닫기` 분기를 둔다. 기존 앱 실행도 먼저 환경 check를 거치고 실패 시 복구 흐름으로 보낸다.
- `.app` 실행은 Terminal 창을 띄우지 않는다. `launcher.sh`가 repo 경로를 읽고 `quickstart.sh --check`, 필요 시 복구, 마지막 `run.sh` 실행 순서로 처리한다.
- 사용자-facing 앱 이름은 `Jelly Dict`로 통일한다. 내부 실행 파일명은 `jelly-dict`를 유지한다.
- repo 내부 생성물은 `app_files/dist/` 아래에만 둔다. 사용자 사전 데이터 `~/Documents/jelly-dict/`는 installer/cleanup에서 삭제 대상이 아니다.

### Installer UI

- installer UI는 기존 quickstart 워드마크, 색상, 선택 UI, spinner를 따른다.
- 최소 터미널 기준에서 스크롤이 생기지 않게 각 단계를 clear 후 고정 영역으로 다시 그린다.
- 긴 pip/Playwright 로그는 화면에 직접 뿌리지 않고 로그 파일에만 남긴다.
- 의존성/TTS 설치 중에는 로그를 읽어 현재 단계, 현재 항목, progress bar, 퍼센트를 표시한다.
- 설치 중단 감지를 위해 `.install_incomplete`를 사용한다. 다음 실행 시 중단된 `.venv`/설치 마커만 정리하고 사전 데이터는 건드리지 않는다.

### 앱 UI / 디자인 정리

- 설정창, 미리보기/편집창, 중복 다이얼로그, Anki 내보내기 popup, 단어장 헤더 버튼, checkbox, combo/menu 스타일을 다크 라운드 UI로 맞췄다.
- 파란 체크 표시는 앱 포인트 컬러 `#e8744f` 계열로 바꾼다. macOS 기본 파란 체크는 이 앱 톤에 맞지 않는다.
- 같은 행에 놓이는 버튼은 같은 높이, 폰트 크기, weight, radius, border 기준을 써야 한다.
- 단어장 헤더 행(`영어/일본어 단어장`, `최신순`, `Anki 내보내기`, `선택 삭제`)은 투명 배경 + 무테두리 텍스트 버튼 스타일을 기본으로 한다. hover/active 때만 배경 또는 테두리를 살짝 드러낸다.
- 버튼 내부 텍스트/아이콘/chevron/dots는 커스텀 페인트 시 같은 기준선에서 중앙 정렬한다. Qt 기본 버튼과 커스텀 페인트 버튼을 같은 행에 섞을 때는 높이와 baseline을 직접 맞춘다.
- 단어장/언어/OCR/정렬 메뉴는 같은 `LanguageMenuItem` 계열 행을 쓴다. 메뉴 폭은 단어장 선택 메뉴 기준으로 넓게 유지하고, 현재 선택된 항목은 `최신순` 메뉴처럼 둥근 배경 highlight와 포인트 체크를 보여준다.
- Anki 내보내기는 붙어 있는 두 개의 커스텀 버튼으로 둔다. 왼쪽은 기본 내보내기, 오른쪽 dots 버튼은 옵션 popup을 연다. 두 버튼은 2px 간격으로 붙여 split control처럼 보이게 하되 hover/active는 각각 독립적으로 반응한다.
- Anki popup의 `Anki 카드 음성 비우기`는 위험/강조 항목처럼 보이게 하지 않는다. 일반 옵션과 같은 레벨로 둔다.
- 설정창과 보조 popup은 사각 프레임/이중창처럼 보이지 않게 하나의 rounded panel로 통일한다.

### 성능 / 반응성

- 앱 시작 직후 Excel 저장 단어 캐시 로딩은 UI 스레드에서 실행하지 않는다. `SavedWordsCacheWorker`가 `QThread`에서 읽고 완료 후 최근 단어 저장 상태를 갱신한다.
- WebKit/Playwright 예열은 첫 타이핑 즉시 시작하지 않고 900ms idle 뒤로 미룬다. 첫 입력/검색 순간의 CPU 버벅임을 줄이기 위함이다.
- 설정창 생성 시 Keychain 상태, TTS 설치 상태, Kokoro 모델 캐시 크기 확인은 백그라운드 worker에서 수행한다.
- 설정창 엔진 combo 생성 중 VOICEVOX live probe를 하지 않는다. VOICEVOX 실제 가동 여부는 사용자가 VOICEVOX 음성 picker를 열 때 확인한다.
- 단어장 Excel 읽기 결과는 파일 path와 mtime 기준으로 캐시한다. 같은 파일에서 정렬/재표시만 하는 경우 Excel을 다시 열지 않는다.
- 단어장 리스트 스크롤은 `ScrollPerPixel` + 트랙패드 pixel delta 감쇠를 적용해 작은 움직임은 부드럽고, 빠른 스와이프는 비례해서 더 많이 이동하게 한다.

### 검증

- UI 변경 후 최소 검증은 `py_compile`, `git diff --check`, 오프스크린 렌더 캡처를 수행한다.
- 최근 전체 검증은 `python -m pytest` 전체 실행으로 `262 passed, 3 warnings`를 확인했다.
- Playwright/WebKit 관련 검증은 offscreen/minimal 플랫폼에서 자동 예열이 실행되지 않는지 확인해야 한다.

## 2026-06-01 v2.0 변경 메모

- 최근 단어/영어 단어장/일본어 단어장 마지막 화면과 단어장 정렬 기준을 `app_state`에 저장한다.
- 최근 단어 목록은 선택 강조를 제거하고, 상세 열기만 유지한다.
- 단어장 선택 UX는 단일 클릭 선택 해제와 더블클릭 상세 열기를 timer로 분리한다.
- 삭제 후 Excel/cache/recent 목록을 함께 정리하고, 하단 되돌리기 toast와 `Command+Z` 복원을 제공한다.
- 단어장 수정 창에서 직접 편집과 재조회를 처리한다. 재조회는 기존 항목을 임시 보관한 뒤 삭제/조회/편입하고, 결과가 없으면 기존 항목을 복원한다.
- 메뉴, combo popup, checkbox, 스크롤바, footer/status UI를 다크 라운드 톤으로 통일했다.
- 상세 페이지에서 품사/출처 중복 노출을 줄이고, `source: NAVER`처럼 작은 출처 표기로 정리했다.
- 전체 테스트 기준을 `262 passed`로 갱신했다.

## 테스트 현황

- `tests/test_models.py` — 모델 helper, 단어장 표시용 다중 의미 요약 포함
- `tests/test_language_detector.py`
- `tests/test_settings_store.py`
- `tests/test_cache_store.py` — `delete_entries`, `delete_recent_entries`, `app_state`, `recent_with_entries` 포함
- `tests/test_excel_writer.py`
- `tests/test_duplicate_checker.py`
- `tests/test_save_service.py`
- `tests/test_anki_render.py` — 영어/일본어 Anki 카드 조건부 렌더링, ruby-only 예문 HTML sanitizer 포함
- `tests/test_no_network_imports.py` — AST 기반 import guard
- `tests/test_naver_english_parser.py` — apple/jelly/recalibration 픽스처
- `tests/test_naver_japanese_parser.py` — 蘇る (yomigaeru) 픽스처
- `tests/test_lookup_service.py` — 캐시 hit/miss, ambiguous, parse_failed 라우팅
- `tests/test_ankiconnect_client.py` — urlopen 모킹 + 에러 매핑
- `tests/test_ocr.py` — OCR 후보 후처리, provider 선택, payload 모델, OCR temp 정리
- `tests/test_export_service.py` — Excel 값 우선 export 변환, cache 구조 보강, 언어별 export 필터
- `tests/test_tts_pipeline.py` — TTS cache key, media dedup, failure swallow, credit 수집
- `tests/fixtures/*.html` — 파서 테스트용 HTML 픽스처

마지막 전체 테스트 확인값은 `262 passed, 3 warnings`다.

## 작업 시 주의

1. 네트워크 접근은 기본적으로 `app/dictionary/` 계층으로 제한한다. 예외는 `app/anki/ankiconnect_client.py`(`127.0.0.1`), `app/anki/tts/voicevox_provider.py`(`127.0.0.1`), `app/ocr/google_vision.py`(사용자 키 설정 시), 외부 TTS provider 실행 경로뿐이다.
2. `app/core/config.py`의 허용 도메인 정책을 우회하지 않는다.
3. Anki 모델 ID와 GUID 알고리즘은 변경하지 않는다.
4. 사용자가 만든 Excel 데이터를 기준 데이터로 취급한다.
5. 사용자에게 보이는 문구에서는 내부 구현 용어보다 작업 흐름 중심 표현을 쓴다.
6. 메인 화면에 긴 실패 로그, 스택 트레이스, 디버그 패널을 다시 넣지 않는다.
7. 외부 온라인 요청은 사용자가 명시적으로 실행한 조회만 허용한다.
8. OCR 다중 조회 및 일반 순차 조회는 동시 요청하지 않고 1초 간격으로 순차 처리한다. 비동기 딜레이와 사용자 추가 제출이 겹쳐 발생하는 레이스 컨디션을 방지하기 위해, 단일 `QTimer` 인스턴스 및 `_is_lookup_active()` 상태 검사로 순차 조회의 흐름을 보장한다.
9. 백그라운드 prefetch / 자동 재시도 / 임의의 온라인 요청을 추가하지 않는다.
10. `tests/fixtures/*.html` 은 네트워크 없이 파서 회귀를 잡는 캐릭터라이제이션 테스트의 입력이다. 파서 동작을 의도적으로 바꿀 때만 갱신한다.
11. UI 시그널은 동일하게 유지하면서 컨트롤러(`app/ui/controllers/`)로 로직을 옮길 수 있다. 위젯 트리는 보존한다.
12. Anki `FIELD_ORDER`는 기존 Excel/Anki 필드 prefix를 보존하고 새 필드는 뒤에만 append한다.
13. APKG export에서 Excel은 사용자가 수정하는 최종 데이터 원본이다. cache는 nested meaning/examples 복구에만 사용하고 Excel 셀 값을 덮지 않는다.
14. TTS mp3 cache는 성능상 유지하되, cache key에는 출력 설정을 포함하고 APKG에는 중복 media를 넣지 않는다.
15. Anki 예문 HTML은 렌더링 경계에서 `<ruby>`, `<rt>`, `<rp>`만 허용한다. 일본어 파서의 ruby 표시는 보존하되 Excel/미리보기/수동 입력에서 온 임의 HTML은 카드 구조에 들어가지 않게 escape한다.
16. 설정창에서 네트워크 테스트를 추가할 때는 UI 스레드에서 직접 호출하지 말고 worker thread로 분리한다.
17. 일본어 Anki headword 요미가나는 base 글자 사이 간격을 넓히지 않는 방식으로 구현한다. reading 폭이 layout 폭 계산에 참여해 `蘇 る`처럼 벌어지는 구현은 금지한다.
