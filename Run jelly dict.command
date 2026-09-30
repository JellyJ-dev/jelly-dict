#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"

close_terminal_window() {
  if [[ "${TERM_PROGRAM:-}" == "Apple_Terminal" ]] && command -v osascript >/dev/null 2>&1; then
    (sleep 0.2; osascript -e 'tell application "Terminal" to close front window') >/dev/null 2>&1 &
  fi
}

SUPPORT_DIR="${SCRIPT_DIR}"
if [[ ! -x "${SUPPORT_DIR}/scripts/run.sh" && -x "${SCRIPT_DIR}/app_files/scripts/run.sh" ]]; then
  SUPPORT_DIR="${SCRIPT_DIR}/app_files"
fi

if [[ ! -x "${SUPPORT_DIR}/scripts/run.sh" ]]; then
  echo "jelly dict 실행 파일을 찾지 못했습니다."
  echo "현재 위치: ${SCRIPT_DIR}"
  echo
  echo "다운로드한 폴더 구조가 깨졌을 수 있습니다."
  read -r -p "Press Enter to close..." _
  close_terminal_window
  exit 1
fi

echo "Starting jelly dict..."
echo
"${SUPPORT_DIR}/scripts/run.sh" --detach
close_terminal_window
