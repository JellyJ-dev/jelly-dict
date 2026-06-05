#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
INSTALL_SCRIPT="${SCRIPT_DIR}/app_files/scripts/install_app.sh"

if [[ ! -x "${INSTALL_SCRIPT}" ]]; then
  echo "jelly dict installer script를 찾지 못했습니다."
  echo "현재 위치: ${SCRIPT_DIR}"
  echo "필수 파일: ${INSTALL_SCRIPT}"
  echo
  echo "다운로드한 폴더 구조가 깨졌을 수 있습니다."
  read -r -p "Press Enter to close..." _
  exit 1
fi

exec "${INSTALL_SCRIPT}" "$@"
