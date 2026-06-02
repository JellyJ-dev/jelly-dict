#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
PUBLIC_ROOT="$(cd "${REPO_ROOT}/.." && pwd -P)"
APP_DIR="${REPO_ROOT}/jelly_dict"
VENV_DIR="${APP_DIR}/.venv"
INSTALL_MODE_FILE="${APP_DIR}/.install_mode"
PYTHON_COMMAND_FILE="${APP_DIR}/.python_cmd"
SETUP_STATE_FILE="${APP_DIR}/.quickstart_ok"
LOG_DIR="${APP_DIR}/.jelly_dict/logs"
QUICKSTART_LOG="${LOG_DIR}/quickstart.log"

WITH_TTS=0
RUN_AFTER=0
DETACH_RUN=0
CHECK_ONLY=0
INSTALL_MODE=""
LICENSE_ACCEPTED=0

if [[ -t 1 ]]; then
  RESET="$(printf '\033[0m')"
  ACCENT="$(printf '\033[38;5;209m')"
  MUTED="$(printf '\033[38;5;245m')"
  GREEN="$(printf '\033[38;5;108m')"
  RED="$(printf '\033[38;5;203m')"
else
  RESET=""
  ACCENT=""
  MUTED=""
  GREEN=""
  RED=""
fi

usage() {
  cat <<'USAGE'
Usage: scripts/quickstart.sh [--run] [--tts] [--mode venv|local]

Options:
  --run   Install/update dependencies, then start jelly dict.
  --detach
          When used with --run, launch the app in the background.
  --tts   Also install optional TTS Python dependencies.
  --mode  Choose dependency target. venv is recommended.
  --accept-license
         Confirm license/responsibility notice non-interactively.
  --check Validate the local environment without installing.
  -h, --help
         Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run)
      RUN_AFTER=1
      shift
      ;;
    --detach)
      DETACH_RUN=1
      shift
      ;;
    --tts)
      WITH_TTS=1
      shift
      ;;
    --check)
      CHECK_ONLY=1
      shift
      ;;
    --mode)
      if [[ $# -lt 2 ]]; then
        echo "--mode requires venv or local" >&2
        exit 2
      fi
      INSTALL_MODE="$2"
      shift 2
      ;;
    --accept-license)
      LICENSE_ACCEPTED=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -d "${APP_DIR}" ]]; then
  echo "jelly dict 앱 파일 구조가 원래 배포본과 다릅니다." >&2
  echo "필수 폴더를 찾을 수 없습니다: ${APP_DIR}" >&2
  echo >&2
  echo "의도한 수정이 아니라면 재다운로드하거나, git으로 받은 경우 git pull 후 다시 실행하세요." >&2
  echo "현재 폴더를 직접 옮기거나 일부 파일만 복사한 경우에는 지원하지 않습니다." >&2
  exit 1
fi

cd "${APP_DIR}"
mkdir -p "${LOG_DIR}"

saved_install_mode() {
  if [[ -f "${INSTALL_MODE_FILE}" ]]; then
    local mode
    mode="$(tr -d '[:space:]' < "${INSTALL_MODE_FILE}")"
    if [[ "${mode}" == "venv" || "${mode}" == "local" ]]; then
      printf '%s\n' "${mode}"
      return
    fi
  fi
  printf 'venv\n'
}

if [[ -z "${INSTALL_MODE}" ]]; then
  INSTALL_MODE="$(saved_install_mode)"
fi

if [[ "${INSTALL_MODE}" != "venv" && "${INSTALL_MODE}" != "local" ]]; then
  echo "Invalid install mode: ${INSTALL_MODE}" >&2
  echo "Use --mode venv or --mode local." >&2
  exit 2
fi

save_install_mode() {
  printf '%s\n' "${INSTALL_MODE}" > "${INSTALL_MODE_FILE}"
}

save_python_command() {
  printf '%s\n' "$(base_python_command)" > "${PYTHON_COMMAND_FILE}"
}

write_setup_state() {
  {
    printf 'quickstart_ok=1\n'
    printf 'mode=%s\n' "${INSTALL_MODE}"
    printf 'app_dir=%s\n' "${APP_DIR}"
    printf 'updated_at=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  } > "${SETUP_STATE_FILE}"
}

print_layout_recovery_hint() {
  cat <<EOF

jelly dict 앱 파일 구조가 원래 배포본과 다릅니다.
이 상태에서 설치를 계속하는 것은 권장하지 않습니다.

의도한 수정이 아니라면 아래 중 하나로 복구하세요.
  - 다운로드 받은 압축/폴더를 새로 받기
  - git으로 받은 경우: git pull 후 다시 실행
  - 일부 파일만 복사했다면 전체 폴더를 다시 복사

정상적인 최상위 구조:
  jelly-dict/
  ├── Install jelly dict.command
  ├── Run jelly dict.command
  ├── README.md
  └── app_files/
EOF
}

print_step() {
  printf '  %s•%s %s\n' "${ACCENT}" "${RESET}" "$1"
}

print_ok() {
  printf '    %s✓%s %s\n' "${GREEN}" "${RESET}" "$1"
}

print_fail() {
  printf '    %s✗%s %s\n' "${RED}" "${RESET}" "$1"
}

show_log_hint() {
  printf '    %s로그: %s%s\n' "${MUTED}" "${QUICKSTART_LOG}" "${RESET}"
}

sanitize_proxy_env() {
  # pip cannot use SOCKS proxies without the pysocks package — which we
  # haven't installed yet at this point. If the shell has ALL_PROXY /
  # HTTPS_PROXY / HTTP_PROXY pointing at a socks:// URL (common on macOS
  # with Clash, V2Ray, mihomo, etc.) strip them for our pip subprocess so
  # the install reaches PyPI over a direct connection. HTTP/HTTPS proxies
  # are left intact because pip handles those natively.
  local var val notified=0
  for var in ALL_PROXY all_proxy HTTPS_PROXY https_proxy HTTP_PROXY http_proxy; do
    eval "val=\${${var}:-}"
    if [[ -n "${val}" && "${val}" == socks* ]]; then
      unset "${var}"
      if [[ "${notified}" -eq 0 ]]; then
        printf '  %s!%s SOCKS proxy detected in environment — disabling for pip install\n' "${ACCENT}" "${RESET}"
        notified=1
      fi
    fi
  done
}

run_logged() {
  local label="$1"
  shift

  print_step "${label}"
  {
    echo
    echo "## ${label}"
    date -u '+%Y-%m-%dT%H:%M:%SZ'
    printf '$'
    printf ' %q' "$@"
    echo
  } >> "${QUICKSTART_LOG}"

  if "$@" >> "${QUICKSTART_LOG}" 2>&1; then
    print_ok "완료"
    return 0
  fi

  print_fail "실패"
  show_log_hint
  echo
  echo "마지막 로그:"
  tail -n 30 "${QUICKSTART_LOG}" | sed 's/^/    /'
  return 1
}

verify_public_layout() {
  local failed=0

  echo
  echo "앱 파일 구조 확인 중..."

  for path in \
    "${PUBLIC_ROOT}/Install jelly dict.command" \
    "${PUBLIC_ROOT}/Run jelly dict.command" \
    "${PUBLIC_ROOT}/README.md" \
    "${PUBLIC_ROOT}/app_files" \
    "${REPO_ROOT}/scripts/quickstart.sh" \
    "${REPO_ROOT}/scripts/run.sh" \
    "${APP_DIR}/app/main.py" \
    "${APP_DIR}/requirements.txt"; do
    if [[ ! -e "${path}" ]]; then
      echo "  ✗ 없음: ${path}"
      failed=1
    fi
  done

  for path in \
    "${PUBLIC_ROOT}/Install jelly dict.command" \
    "${PUBLIC_ROOT}/Run jelly dict.command" \
    "${REPO_ROOT}/scripts/quickstart.sh" \
    "${REPO_ROOT}/scripts/run.sh"; do
    if [[ -e "${path}" && ! -x "${path}" ]]; then
      echo "  ✗ 실행 권한 없음: ${path}"
      failed=1
    fi
  done

  if [[ -f "${PUBLIC_ROOT}/dev.md" ]]; then
    echo "  ✗ dev.md가 최상위 공개 폴더에 있습니다"
    failed=1
  fi

  if [[ "${failed}" -eq 0 ]]; then
    echo "  ✓ 앱 파일 구조 정상"
  else
    print_layout_recovery_hint
  fi

  return "${failed}"
}

venv_matches_current_location() {
  # Ask the venv's own Python where it lives. This is robust across
  # CPython versions (the activate script template has changed format
  # in 3.12+ / 3.13+) and across symlinked roots like /tmp → /private/tmp.
  [[ -x "${VENV_DIR}/bin/python" ]] || return 1

  local actual expected
  actual="$("${VENV_DIR}/bin/python" -c 'import sys, os; print(os.path.realpath(sys.prefix))' 2>/dev/null)" || return 1
  [[ -n "${actual}" && -d "${actual}" ]] || return 1
  expected="$(cd "${VENV_DIR}" && pwd -P)"
  [[ "${actual}" == "${expected}" ]]
}

python_command() {
  if [[ "${INSTALL_MODE}" == "venv" ]]; then
    printf 'python\n'
  else
    base_python_command
  fi
}

candidate_python_commands() {
  # Order matters: prefer versions with known-good Qt/macOS app behavior first.
  # Python 3.13 + PySide6 6.10 can abort while creating the Cocoa platform
  # integration when launched from the generated .app on some macOS 26 systems.
  printf '%s\n' \
    python3.12 \
    python3.11 \
    python3.13 \
    python3.14 \
    python3 \
    /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3.11 \
    /opt/homebrew/bin/python3.13 \
    /opt/homebrew/bin/python3.14 \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3.12 \
    /usr/local/bin/python3.11 \
    /usr/local/bin/python3.13 \
    /usr/local/bin/python3.14 \
    /usr/local/bin/python3 \
    /opt/homebrew/opt/python@3.12/bin/python3.12 \
    /opt/homebrew/opt/python@3.11/bin/python3.11 \
    /opt/homebrew/opt/python@3.13/bin/python3.13 \
    /opt/homebrew/opt/python@3.14/bin/python3.14 \
    /usr/local/opt/python@3.12/bin/python3.12 \
    /usr/local/opt/python@3.11/bin/python3.11 \
    /usr/local/opt/python@3.13/bin/python3.13 \
    /usr/local/opt/python@3.14/bin/python3.14
}

python_is_supported() {
  "$1" - <<'PY' >/dev/null 2>&1
import sys
version = sys.version_info[:2]
raise SystemExit(0 if (3, 11) <= version < (3, 13) else 1)
PY
}

python_version_text() {
  "$1" - <<'PY' 2>/dev/null
import sys
print(sys.version.split()[0])
PY
}

venv_python_is_supported() {
  [[ -x "${VENV_DIR}/bin/python" ]] || return 1
  python_is_supported "${VENV_DIR}/bin/python"
}

base_python_command() {
  local command
  command="$(select_base_python)"
  printf '%s\n' "${command}"
}

select_base_python() {
  local candidate
  local seen=":"

  if [[ -n "${JELLY_DICT_PYTHON:-}" ]]; then
    candidate="${JELLY_DICT_PYTHON}"
    if command -v "${candidate}" >/dev/null 2>&1 && python_is_supported "${candidate}"; then
      command -v "${candidate}"
      return 0
    fi
  fi

  if [[ -f "${PYTHON_COMMAND_FILE}" ]]; then
    candidate="$(tr -d '\r\n' < "${PYTHON_COMMAND_FILE}")"
    if [[ -n "${candidate}" && "${seen}" != *":${candidate}:"* ]]; then
      seen="${seen}${candidate}:"
      if command -v "${candidate}" >/dev/null 2>&1 && python_is_supported "${candidate}"; then
        command -v "${candidate}"
        return 0
      fi
    fi
  fi

  while IFS= read -r candidate; do
    [[ -n "${candidate}" ]] || continue
    [[ "${seen}" != *":${candidate}:"* ]] || continue
    seen="${seen}${candidate}:"
    if command -v "${candidate}" >/dev/null 2>&1 && python_is_supported "${candidate}"; then
      command -v "${candidate}"
      return 0
    fi
  done < <(candidate_python_commands)

  return 1
}

print_python_candidates() {
  local candidate
  local seen=":"

  while IFS= read -r candidate; do
    [[ -n "${candidate}" ]] || continue
    [[ "${seen}" != *":${candidate}:"* ]] || continue
    seen="${seen}${candidate}:"
    if command -v "${candidate}" >/dev/null 2>&1; then
      echo "    - ${candidate}: $("${candidate}" --version 2>&1)"
    fi
  done < <(candidate_python_commands)
}

check_python_packages() {
  "$(python_command)" - <<'PY'
import importlib.util
from importlib import metadata
import re
import sys

modules = ["PySide6", "openpyxl", "bs4", "lxml", "playwright", "genanki", "keyring", "Vision"]
missing = [name for name in modules if importlib.util.find_spec(name) is None]
if missing:
    print("  ✗ missing Python packages: " + ", ".join(missing))
    sys.exit(1)

checks = [
    ("PySide6", "PySide6", (6, 7), (6, 11), ">=6.7,<6.11"),
    ("openpyxl", "openpyxl", (3, 1), None, ">=3.1"),
    ("beautifulsoup4", "bs4", (4, 12), None, ">=4.12"),
    ("lxml", "lxml", (5, 0), None, ">=5.0"),
    ("playwright", "playwright", (1, 45), None, ">=1.45"),
    ("genanki", "genanki", (0, 13), None, ">=0.13"),
    ("keyring", "keyring", (24,), None, ">=24"),
    ("pyobjc-framework-Vision", "Vision", (10, 0), None, ">=10.0"),
]

def version_tuple(value):
    parts = re.findall(r"\d+", value)
    return tuple(int(part) for part in parts[:3])

bad = []
for dist_name, module_name, minimum, maximum, spec in checks:
    if importlib.util.find_spec(module_name) is None:
        bad.append(f"{module_name} missing")
        continue
    try:
        installed = metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        bad.append(f"{dist_name} metadata missing")
        continue
    parsed = version_tuple(installed)
    if parsed < minimum or (maximum is not None and parsed >= maximum):
        bad.append(f"{dist_name} {installed} does not satisfy {spec}")

if bad:
    print("  ✗ Python package version mismatch:")
    for item in bad:
        print("    - " + item)
    sys.exit(1)

print("  ✓ required Python packages and versions")
PY
}

check_qt_runtime() {
  "$(python_command)" - <<'PY'
import importlib.util
import os
from pathlib import Path

spec = importlib.util.find_spec("PySide6")
if spec is None or spec.origin is None:
    print("  ✗ PySide6 missing")
    raise SystemExit(1)

root = Path(spec.origin).resolve().parent
plugins = root / "Qt" / "plugins"
platforms = plugins / "platforms"
cocoa = platforms / "libqcocoa.dylib"
if not cocoa.exists():
    print(f"  ✗ Qt Cocoa platform plugin missing: {cocoa}")
    raise SystemExit(1)

os.environ["QT_PLUGIN_PATH"] = str(plugins)
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms)
os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")

from PySide6 import QtCore

print(f"  ✓ Qt runtime: {QtCore.qVersion()} / cocoa plugin")
PY
}

check_playwright_webkit() {
  "$(python_command)" - <<'PY'
import importlib.util
from pathlib import Path

if importlib.util.find_spec("playwright") is None:
    raise SystemExit(1)

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    path = Path(p.webkit.executable_path)
    if not path.exists():
        raise SystemExit(1)
print("  ✓ Playwright WebKit")
PY
}

install_requirements_or_explain() {
  if run_logged "필수 Python 패키지 설치" "$(python_command)" -m pip install -r requirements.txt; then
    return 0
  fi

  cat >&2 <<'EOF'

필수 패키지 설치에 실패했습니다.

PySide6는 Python 버전별 macOS wheel과 Qt/macOS 런타임 안정성의 영향을 받습니다.
이 앱은 PySide6 >=6.7,<6.11 범위를 사용하며, 현재 macOS 앱 번들은
Python 3.12 또는 3.11 환경만 사용합니다.

Homebrew 기본 Python이 3.13+ 인 경우 호환 버전을 설치하세요:
  brew install python@3.12     # 권장
  brew install python@3.11

그 뒤 Install jelly dict.command를 다시 실행하세요. 설치된 여러 Python 중
원하는 버전을 강제하려면 JELLY_DICT_PYTHON 환경변수도 가능합니다:
  JELLY_DICT_PYTHON=/opt/homebrew/bin/python3.12 ./Install\ jelly\ dict.command

로그에 "Missing dependencies for SOCKS support" 가 보이면 셸의
ALL_PROXY / HTTPS_PROXY 가 socks://... 로 설정돼 있는 경우입니다.
이번 실행에서는 자동으로 무시했지만, Clash/V2Ray/mihomo 같은 프록시 앱을
끄거나 다음 셸 세션에서 unset 해도 됩니다:
  unset ALL_PROXY HTTPS_PROXY HTTP_PROXY
EOF
  return 1
}

check_tts_packages() {
  "$(python_command)" - <<'PY'
import importlib.util
from importlib import metadata
import re
import sys

required = ["soundfile", "kokoro", "spacy", "en_core_web_sm", "misaki", "pyopenjtalk"]
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    print("  ✗ missing TTS Python packages: " + ", ".join(missing))
    sys.exit(1)

checks = [
    ("kokoro", "kokoro", (0, 3), ">=0.3"),
    ("soundfile", "soundfile", (0, 12), ">=0.12"),
    ("spacy", "spacy", (3, 8), ">=3.8"),
    ("misaki", "misaki", (0, 6), ">=0.6"),
]

def version_tuple(value):
    parts = re.findall(r"\d+", value)
    return tuple(int(part) for part in parts[:3])

bad = []
for dist_name, module_name, minimum, spec in checks:
    if importlib.util.find_spec(module_name) is None:
        bad.append(f"{module_name} missing")
        continue
    try:
        installed = metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        bad.append(f"{dist_name} metadata missing")
        continue
    if version_tuple(installed) < minimum:
        bad.append(f"{dist_name} {installed} does not satisfy {spec}")

if bad:
    print("  ✗ TTS package version mismatch:")
    for item in bad:
        print("    - " + item)
    sys.exit(1)

from pathlib import Path
root = Path.home() / ".cache" / "huggingface" / "hub" / "models--hexgrad--Kokoro-82M"
ref = root / "refs" / "main"
snapshot = root / "snapshots" / ref.read_text(encoding="utf-8").strip() if ref.exists() else None
files = [
    "config.json",
    "kokoro-v1_0.pth",
    "voices/af_heart.pt",
    "voices/jf_alpha.pt",
    "voices/jf_gongitsune.pt",
    "voices/jm_kumo.pt",
]
missing_files = []
if snapshot is None or not snapshot.exists():
    missing_files = files
else:
    missing_files = [name for name in files if not (snapshot / name).exists()]
if missing_files:
    print("  ✗ missing Kokoro local model cache: " + ", ".join(missing_files))
    sys.exit(1)

print("  ✓ TTS Python packages and versions")
PY
}

print_license_notice() {
  echo "라이선스 확인"
  echo "  jelly dict는 MIT License 조건으로 제공됩니다."
  echo "  외부 패키지와 선택 TTS 음성은 각각의 라이선스/약관을 따릅니다."
  echo "  이 앱의 설치, 실행, 생성물 사용으로 발생하는 책임은 관련 라이선스와 약관에 따라 사용자에게 있습니다."
  echo "  자세한 내용은 app_files/THIRD_PARTY_NOTICES.md를 확인하세요."
  echo
}

accept_license_or_exit() {
  local answer

  print_license_notice
  read -r -p "위 내용을 확인했고 동의합니까? [y/N] " answer
  answer="$(printf '%s' "${answer}" | tr '[:upper:]' '[:lower:]')"
  if [[ "${answer}" != "y" && "${answer}" != "yes" ]]; then
    echo "동의하지 않아 설치를 중단합니다."
    exit 1
  fi
}

check_python_version() {
  local python_cmd="$1"

  "${python_cmd}" - <<'PY'
import sys

required = (3, 11)
maximum = (3, 13)
current = sys.version_info[:2]
if current < required:
    print(f"  ✗ python3 >= {required[0]}.{required[1]} required, found {sys.version.split()[0]}")
    raise SystemExit(1)
if current >= maximum:
    print(f"  ✗ Python {current[0]}.{current[1]} is not used for Jelly Dict.app yet.")
    print("    Python 3.13 + Qt can abort while creating the macOS Cocoa platform plugin")
    print("    on some macOS 26 systems. Install Python 3.12 or 3.11 and rerun installer.")
    raise SystemExit(1)
print(f"  ✓ python3 version OK: {sys.version.split()[0]}")
PY
}

check_disk_space() {
  local available_kb

  available_kb="$(df -Pk "${APP_DIR}" | awk 'NR == 2 {print $4}')"
  if [[ -z "${available_kb}" ]]; then
    echo "  ! disk space check skipped"
    return
  fi

  if (( available_kb < 1048576 )); then
    echo "  ! free disk space is under 1 GB; dependency install may fail"
  else
    echo "  ✓ free disk space OK"
  fi
}

check_quarantine_warning() {
  local target="${REPO_ROOT}/.."

  if command -v xattr >/dev/null 2>&1 && xattr -p com.apple.quarantine "${target}" >/dev/null 2>&1; then
    echo "  ! macOS quarantine attribute detected on the app folder"
    echo "    If double-click fails, right-click the .command file and choose Open."
  fi
}

check_system_requirements() {
  local failed=0
  local os_name

  os_name="$(uname -s 2>/dev/null || true)"
  if [[ "${os_name}" != "Darwin" ]]; then
    echo "  ✗ macOS required. Current system: ${os_name:-unknown}"
    failed=1
  else
    if command -v sw_vers >/dev/null 2>&1; then
      echo "  ✓ macOS: $(sw_vers -productVersion)"
    else
      echo "  ✓ macOS detected"
    fi
  fi

  echo "  architecture: $(uname -m 2>/dev/null || echo unknown)"
  if [[ "$(sysctl -in sysctl.proc_translated 2>/dev/null || echo 0)" == "1" ]]; then
    echo "  ! running under Rosetta; native arm64/x86_64 Python is usually more stable"
  fi

  local base_python
  if ! base_python="$(select_base_python)"; then
    echo "  ✗ Python 3.12 또는 3.11을 찾지 못했습니다"
    echo "    확인한 Python 후보:"
    print_python_candidates
    failed=1
  elif ! check_python_version "${base_python}"; then
    failed=1
  else
    echo "  ✓ selected Python: ${base_python}"
  fi

  if [[ -n "${base_python:-}" ]] && ! "${base_python}" -m pip --version >/dev/null 2>&1; then
    echo "  ✗ selected Python pip is not available"
    failed=1
  elif [[ -n "${base_python:-}" ]]; then
    echo "  ✓ selected Python pip"
  fi

  if [[ "${INSTALL_MODE}" == "venv" && -n "${base_python:-}" ]]; then
    if ! "${base_python}" -m venv --help >/dev/null 2>&1; then
      echo "  ✗ selected Python venv module is not available"
      failed=1
    else
      echo "  ✓ selected Python venv"
    fi
  fi

  if [[ ! -w "${APP_DIR}" ]]; then
    echo "  ✗ app folder is not writable: ${APP_DIR}"
    failed=1
  else
    echo "  ✓ app folder writable"
  fi

  check_disk_space
  check_quarantine_warning

  return "${failed}"
}

check_environment() {
  local failed=0
  local can_check_packages=0

  echo "Checking environment..."
  echo "  install mode: ${INSTALL_MODE}"

  if ! check_system_requirements; then
    failed=1
  fi

  local base_python
  if ! base_python="$(select_base_python)"; then
    echo "  ✗ Python 3.12 또는 3.11을 찾지 못했습니다"
    failed=1
  else
    echo "  ✓ selected Python: ${base_python} $(python_version_text "${base_python}")"
  fi

  if [[ "${INSTALL_MODE}" == "venv" ]]; then
    if [[ ! -d "${VENV_DIR}" ]]; then
      echo "  ✗ virtual environment missing: ${VENV_DIR}"
      failed=1
    elif ! venv_matches_current_location; then
      echo "  ✗ virtual environment was created for a different folder"
      echo "    rerun Install jelly dict.command and allow dependency installation to recreate it"
      failed=1
    elif ! venv_python_is_supported; then
      echo "  ✗ virtual environment Python is not supported: $("${VENV_DIR}/bin/python" -V 2>&1)"
      echo "    Python 3.12 or 3.11 is required for the generated macOS app"
      echo "    rerun Install jelly dict.command to recreate the environment"
      failed=1
    else
      echo "  ✓ virtual environment: ${VENV_DIR}"
    fi
  else
    echo "  ✓ using local Python environment"
  fi

  if [[ ! -f requirements.txt ]]; then
    echo "  ✗ requirements.txt missing"
    failed=1
  else
    echo "  ✓ requirements.txt"
  fi

  if [[ "${INSTALL_MODE}" == "venv" && -d "${VENV_DIR}" ]] && venv_matches_current_location && venv_python_is_supported; then
    # shellcheck source=/dev/null
    source "${VENV_DIR}/bin/activate"
    can_check_packages=1
  elif [[ "${INSTALL_MODE}" == "local" ]]; then
    can_check_packages=1
  fi

  if [[ "${can_check_packages}" -eq 1 ]]; then
    if check_python_packages; then
      :
    else
      failed=1
    fi

    if check_qt_runtime; then
      :
    else
      failed=1
    fi

    if check_playwright_webkit; then
      :
    else
      echo "  ✗ Playwright WebKit missing"
      failed=1
    fi

    if [[ "${WITH_TTS}" -eq 1 ]]; then
      if check_tts_packages; then
        :
      else
        failed=1
      fi

      if command -v ffmpeg >/dev/null 2>&1; then
        echo "  ✓ ffmpeg"
      else
        echo "  ✗ ffmpeg missing"
        failed=1
      fi
    fi
  fi

  return "${failed}"
}

if ! verify_public_layout; then
  exit 1
fi

if [[ "${CHECK_ONLY}" -eq 1 ]]; then
  check_environment
  exit $?
fi

if [[ "${LICENSE_ACCEPTED}" -ne 1 ]]; then
  accept_license_or_exit
fi
save_install_mode
save_python_command

if [[ "${INSTALL_MODE}" == "venv" ]]; then
  if [[ -d "${VENV_DIR}" ]] && { ! venv_matches_current_location || ! venv_python_is_supported; }; then
    print_step "현재 폴더에 맞게 가상환경 재생성"
    rm -rf "${VENV_DIR}"
    print_ok "완료"
  fi

  if [[ ! -d "${VENV_DIR}" ]]; then
    run_logged "전용 가상환경 생성" "$(base_python_command)" -m venv "${VENV_DIR}"
  fi

  # shellcheck source=/dev/null
  source "${VENV_DIR}/bin/activate"
fi

sanitize_proxy_env

run_logged "pip 업데이트" "$(python_command)" -m pip install --upgrade pip
install_requirements_or_explain

if [[ "${WITH_TTS}" -eq 1 ]]; then
  run_logged "TTS Python 패키지 설치" "$(python_command)" -m pip install -r requirements-tts.txt
  run_logged "Kokoro 로컬 모델 캐시 설치" "$(python_command)" -c 'from huggingface_hub import snapshot_download; snapshot_download("hexgrad/Kokoro-82M", allow_patterns=["config.json", "kokoro-v1_0.pth", "voices/af_heart.pt", "voices/jf_alpha.pt", "voices/jf_gongitsune.pt", "voices/jm_kumo.pt"])'
  run_logged "Kokoro 영어 G2P 모델 설치" "$(python_command)" -m spacy download en_core_web_sm
  run_logged "Kokoro 일본어 사전 설치" "$(python_command)" -m unidic download
fi

run_logged "Playwright WebKit 설치" "$(python_command)" -m playwright install webkit

echo
if ! check_environment; then
  echo
  echo "Environment check failed. Review the messages above and rerun quickstart."
  exit 1
fi

if ! verify_public_layout; then
  exit 1
fi

echo
echo "Ready."
echo "Run the app with:"
echo "  ${REPO_ROOT}/scripts/run.sh"

write_setup_state

if [[ "${RUN_AFTER}" -eq 1 ]]; then
  if [[ "${DETACH_RUN}" -eq 1 ]]; then
    "${REPO_ROOT}/scripts/run.sh" --detach
  else
    exec "${REPO_ROOT}/scripts/run.sh"
  fi
fi
