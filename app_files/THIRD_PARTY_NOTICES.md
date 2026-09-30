# Third-Party Notices

`jelly_dict`는 MIT 라이선스로 배포됩니다. 아래 항목은 앱이 사용하거나 선택적으로 호출하는 외부 컴포넌트입니다. 각 컴포넌트의 라이선스 전문은 해당 프로젝트 페이지나 PyPI 페이지에서 확인하세요.

## Runtime

`requirements.txt`에 포함되는 기본 실행 의존성입니다.

- PySide6
  - Version: `>=6.7,<6.11`
  - License: LGPL-3.0 / commercial dual license
  - Source: https://wiki.qt.io/Qt_for_Python
  - Note: Qt for Python을 동적 링크로 사용합니다. PySide6 자체를 수정해 재배포하지 않습니다.

- beautifulsoup4
  - Version: `>=4.12`
  - License: MIT
  - Source: https://www.crummy.com/software/BeautifulSoup/

- lxml
  - Version: `>=5.0`
  - License: BSD-3-Clause
  - Source: https://lxml.de/
  - Note: libxml2/libxslt는 MIT 계열 라이선스입니다.

- playwright
  - Version: `>=1.45`
  - License: Apache-2.0
  - Source: https://playwright.dev/python/
  - Note: Chromium 브라우저 바이너리는 첫 설치 시 사용자 환경에 다운로드됩니다.

- openpyxl
  - Version: `>=3.1`
  - License: MIT
  - Source: https://openpyxl.readthedocs.io/

- genanki
  - Version: `>=0.13`
  - License: MIT
  - Source: https://github.com/kerrickstaley/genanki

- keyring
  - Version: `>=24`
  - License: MIT
  - Source: https://github.com/jaraco/keyring
  - Note: macOS Keychain 같은 OS 시크릿 저장소 접근에 사용합니다.

- pyobjc-framework-Vision
  - Version: `>=10.0`
  - License: MIT
  - Source: https://github.com/ronaldoussoren/pyobjc
  - Note: macOS Apple Vision OCR 연동에 사용합니다.

- Apple Vision Framework
  - License: Apple Software License Agreement
  - Note: macOS 시스템 프레임워크입니다. 앱에 포함해 배포하지 않습니다.

## Optional TTS

`requirements-tts.txt` 또는 사용자의 별도 설치로 활성화되는 선택 기능입니다.

- Kokoro model
  - License: Apache-2.0
  - Source: https://huggingface.co/hexgrad/Kokoro-82M
  - Note: 로컬 추론용 모델입니다. 가중치는 첫 사용 시 Hugging Face에서 다운로드됩니다.

- kokoro Python package
  - License: MIT
  - Source: https://pypi.org/project/kokoro/

- soundfile
  - License: BSD-3-Clause
  - Source: https://github.com/bastibe/python-soundfile
  - Note: TTS 음성 파일 출력에 사용합니다.

- VOICEVOX
  - License: engine LGPL-3.0, voice output subject to each character terms
  - Source: https://voicevox.hiroshiba.jp/
  - Note: 사용자가 별도로 설치한 로컬 엔진을 `127.0.0.1:50021`로 호출합니다. 앱은 VOICEVOX 엔진을 포함해 배포하지 않습니다. 생성 음성은 `VOICEVOX:캐릭터명` 크레딧을 Anki 덱 설명에 자동 표기합니다.

- edge-tts
  - License: GPL-3.0-or-later
  - Source: https://github.com/rany2/edge-tts
  - Note: 사용자가 별도로 설치한 CLI를 subprocess로만 호출합니다. 앱은 `import edge_tts`를 하지 않습니다. Microsoft 비공식 엔드포인트를 사용하므로 안정성을 보장하지 않습니다.

## Optional OCR

- Google Cloud Vision API
  - Terms: Google Cloud Terms of Service
  - Source: https://cloud.google.com/vision
  - Note: 사용자가 직접 API 키를 설정한 경우에만 REST API로 호출합니다. 비용은 사용자 부담입니다.

## Data Sources

- Naver Dictionary
  - Source: https://dict.naver.com
  - Note: 개인 학습용 단어 조회에 사용합니다. 네이버 이용약관과 robots 정책을 존중해 사용해야 하며, 최종 사용자가 사용 책임을 가집니다.

## Project License

본 프로젝트 자체의 라이선스 전문은 [LICENSE](LICENSE)를 참고하세요.
