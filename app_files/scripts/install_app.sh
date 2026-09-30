#!/usr/bin/env bash
set -uo pipefail

# Keep this installer visually aligned with the existing jelly dict terminal UI.

if [[ -z "${JELLY_INSTALL_REEXEC:-}" && "${BASH_VERSINFO[0]:-0}" -lt 4 ]]; then
  for _cand in /opt/homebrew/bin/bash /usr/local/bin/bash /opt/local/bin/bash; do
    if [[ -x "${_cand}" ]]; then
      export JELLY_INSTALL_REEXEC=1
      exec "${_cand}" "$0" "$@"
    fi
  done
fi

if [[ "${BASH_VERSINFO[0]:-0}" -ge 4 ]]; then
  ESC_READ_TIMEOUT=0.05
else
  ESC_READ_TIMEOUT=1
fi

INSTALLER_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
SCRIPT_DIR="$(cd "${INSTALLER_SCRIPT_DIR}/../.." && pwd -P)"
JELLY_DICT_VERSION="2.1"
COMMAND_ROLE="${JELLY_DICT_COMMAND_ROLE:-install}"
case "${COMMAND_ROLE}" in
  update)
    COMMAND_LABEL="Updater"
    COMMAND_NOUN="업데이트"
    COMMAND_DONE_LABEL="업데이트 완료"
    ;;
  *)
    COMMAND_ROLE="install"
    COMMAND_LABEL="Installer"
    COMMAND_NOUN="설치"
    COMMAND_DONE_LABEL="설치 완료"
    ;;
esac

APP_NAME="Jelly Dict.app"
QUICKSTART_SCRIPT="${SCRIPT_DIR}/app_files/scripts/quickstart.sh"
BUILD_APP_SCRIPT="${SCRIPT_DIR}/app_files/packaging/macos/build_app.sh"
LICENSE_NOTICE_FILE="${SCRIPT_DIR}/app_files/LICENSE_NOTICE.txt"
DIST_APP="${SCRIPT_DIR}/app_files/dist/${APP_NAME}"
USER_APPS_DIR="${HOME}/Applications"
USER_APP="${USER_APPS_DIR}/${APP_NAME}"
QUICKSTART_LOG="${SCRIPT_DIR}/app_files/jelly_dict/.jelly_dict/logs/quickstart.log"
INSTALL_LOG="${SCRIPT_DIR}/app_files/jelly_dict/.jelly_dict/logs/install_app.log"
UPDATE_LOG="${SCRIPT_DIR}/app_files/jelly_dict/.jelly_dict/logs/update_app.log"
APP_DIR="${SCRIPT_DIR}/app_files/jelly_dict"
VENV_DIR="${APP_DIR}/.venv"
INSTALL_INCOMPLETE_FILE="${APP_DIR}/.install_incomplete"
QUICKSTART_CHECK_TIMEOUT_SECONDS="${JELLY_QUICKSTART_CHECK_TIMEOUT_SECONDS:-180}"
QUICKSTART_INSTALL_TIMEOUT_SECONDS="${JELLY_QUICKSTART_INSTALL_TIMEOUT_SECONDS:-1800}"
APP_BUILD_TIMEOUT_SECONDS="${JELLY_APP_BUILD_TIMEOUT_SECONDS:-600}"
GIT_PULL_TIMEOUT_SECONDS="${JELLY_GIT_PULL_TIMEOUT_SECONDS:-180}"

if [[ -t 1 ]]; then
  RESET=$'\033[0m'
  BOLD=$'\033[1m'
  ACCENT=$'\033[38;5;209m'
  CREAM=$'\033[38;5;223m'
  MUTED=$'\033[38;5;245m'
  FAINT=$'\033[38;5;240m'
  GREEN=$'\033[38;5;108m'
  RED=$'\033[38;5;203m'
  INK=$'\033[38;5;253m'
  HIDE_CURSOR=$'\033[?25l'
  SHOW_CURSOR=$'\033[?25h'
else
  RESET=""; BOLD=""; ACCENT=""; CREAM=""; MUTED=""; FAINT=""; GREEN=""; RED=""; INK=""
  HIDE_CURSOR=""; SHOW_CURSOR=""
fi

cleanup_tty() {
  printf '%s%s' "${SHOW_CURSOR}" "${RESET}"
  stty echo 2>/dev/null || true
  stty icanon 2>/dev/null || true
}
trap cleanup_tty EXIT INT TERM

# shellcheck source=app_files/scripts/lib/terminal_ui.sh
source "${INSTALLER_SCRIPT_DIR}/lib/terminal_ui.sh"

# shellcheck source=app_files/scripts/lib/install_flow.sh
source "${INSTALLER_SCRIPT_DIR}/lib/install_flow.sh"

if [[ "${JELLY_INSTALL_SOURCE_ONLY:-0}" != "1" ]]; then
  jelly_run_installer
fi
