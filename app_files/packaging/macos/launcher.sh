#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
RESOURCES_DIR="${APP_ROOT}/Resources"
REPO_PATH_FILE="${RESOURCES_DIR}/repo_path.txt"
DIALOG_TITLE="Jelly Dict"

show_message() {
  local title="$1"
  local message="$2"
  message="${message//\\n/$'\n'}"

  if command -v osascript >/dev/null 2>&1; then
    osascript -e 'on run argv' \
      -e 'display dialog (item 1 of argv) with title (item 2 of argv) buttons {"OK"} default button "OK"' \
      -e 'end run' \
      -- "${message}" "${title}" >/dev/null 2>&1 || true
  else
    printf '%s\n%s\n' "${title}" "${message}" >&2
  fi
}

run_repair_silently() {
  local quickstart_script="$1"
  local run_script="$2"
  local log_file="$3"

  mkdir -p "$(dirname "${log_file}")"
  {
    echo
    echo "## app launcher repair"
    date -u '+%Y-%m-%dT%H:%M:%SZ'
  } >> "${log_file}"

  if "${quickstart_script}" --accept-license >> "${log_file}" 2>&1; then
    exec "${run_script}"
  fi

  return 1
}

if [[ ! -f "${REPO_PATH_FILE}" ]]; then
  show_message "${DIALOG_TITLE}" "repo_path.txt를 찾지 못했습니다. 앱을 다시 설치해 주세요."
  exit 1
fi

REPO_ROOT="$(tr -d '\r\n' < "${REPO_PATH_FILE}")"

if [[ -z "${REPO_ROOT}" || ! -d "${REPO_ROOT}" ]]; then
  show_message "${DIALOG_TITLE}" "원본 repo 위치를 찾지 못했습니다.\n\n${REPO_ROOT:-repo_path.txt is empty}\n\nrepo 폴더를 옮겼다면 Install jelly dict.command를 다시 실행해 주세요."
  exit 1
fi

QUICKSTART_SCRIPT="${REPO_ROOT}/app_files/scripts/quickstart.sh"
RUN_SCRIPT="${REPO_ROOT}/app_files/scripts/run.sh"
LOG_FILE="${REPO_ROOT}/app_files/jelly_dict/.jelly_dict/logs/quickstart.log"
APP_LOG_FILE="${REPO_ROOT}/app_files/jelly_dict/.jelly_dict/logs/app.log"

if [[ ! -x "${QUICKSTART_SCRIPT}" || ! -x "${RUN_SCRIPT}" ]]; then
  show_message "${DIALOG_TITLE}" "필수 실행 파일을 찾지 못했습니다.\n\n${QUICKSTART_SCRIPT}\n${RUN_SCRIPT}\n\nrepo가 깨졌거나 위치가 바뀌었습니다. 다시 다운로드하거나 git pull 후 Install jelly dict.command를 다시 실행해 주세요."
  exit 1
fi

cd "${REPO_ROOT}"

mkdir -p "$(dirname "${LOG_FILE}")"
{
  echo
  echo "## app launcher check"
  date -u '+%Y-%m-%dT%H:%M:%SZ'
} >> "${LOG_FILE}"

if "${QUICKSTART_SCRIPT}" --check >> "${LOG_FILE}" 2>&1; then
  exec "${RUN_SCRIPT}"
fi

if run_repair_silently "${QUICKSTART_SCRIPT}" "${RUN_SCRIPT}" "${LOG_FILE}"; then
  exit 0
fi

{
  echo
  echo "## app launcher direct run fallback"
  date -u '+%Y-%m-%dT%H:%M:%SZ'
  echo "quickstart check/repair failed; trying run.sh before showing a blocking dialog"
} >> "${LOG_FILE}"

if "${RUN_SCRIPT}" >> "${APP_LOG_FILE}" 2>&1; then
  exit 0
fi

show_message "${DIALOG_TITLE}" "앱 실행에 실패했습니다.\n\nInstall jelly dict.command를 다시 실행해 주세요.\n\n설치 로그: ${LOG_FILE}\n앱 로그: ${APP_LOG_FILE}"
exit 1
