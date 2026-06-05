#!/usr/bin/env bash
set -euo pipefail

DETACH=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --detach)
      DETACH=1
      shift
      ;;
    -h|--help)
      echo "Usage: scripts/run.sh [--detach]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: scripts/run.sh [--detach]" >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=app_files/scripts/lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
REPO_ROOT="${JELLY_APP_FILES_ROOT}"
APP_DIR="${JELLY_APP_DIR}"
VENV_DIR="${JELLY_VENV_DIR}"
INSTALL_MODE_FILE="${APP_DIR}/.install_mode"
PYTHON_COMMAND_FILE="${APP_DIR}/.python_cmd"
SETUP_STATE_FILE="${APP_DIR}/.quickstart_ok"

INSTALL_MODE="$(jelly_saved_install_mode "${INSTALL_MODE_FILE}")"

base_python_command() {
  jelly_select_base_python "${PYTHON_COMMAND_FILE}"
}

quickstart_state_ok() {
  [[ -f "${SETUP_STATE_FILE}" ]] || return 1

  local ok=""
  local app_dir=""
  while IFS='=' read -r key value; do
    case "${key}" in
      quickstart_ok)
        ok="${value}"
        ;;
      app_dir)
        app_dir="${value}"
        ;;
    esac
  done < "${SETUP_STATE_FILE}"

  [[ "${ok}" == "1" && "${app_dir}" == "${APP_DIR}" ]]
}

if ! quickstart_state_ok; then
  echo "jelly dict initial setup is not complete for this folder." >&2
  echo "Run first:" >&2
  echo "  ${REPO_ROOT}/scripts/quickstart.sh" >&2
  exit 1
fi

if [[ "${INSTALL_MODE}" == "venv" ]]; then
  if [[ ! -d "${VENV_DIR}" ]]; then
    echo "Virtual environment not found: ${VENV_DIR}" >&2
    echo "Run first:" >&2
    echo "  ${REPO_ROOT}/scripts/quickstart.sh" >&2
    exit 1
  fi

  if ! jelly_venv_matches_current_location "${VENV_DIR}"; then
    echo "Virtual environment was created for a different folder." >&2
    echo "Run Install jelly dict.command and allow dependency installation to recreate it." >&2
    echo "  ${REPO_ROOT}/scripts/quickstart.sh" >&2
    exit 1
  fi

  if ! jelly_python_is_supported "${VENV_DIR}/bin/python"; then
    echo "Virtual environment Python is not supported: $("${VENV_DIR}/bin/python" -V 2>&1)" >&2
    echo "Jelly Dict.app currently uses Python 3.12 or 3.11 on macOS." >&2
    echo "Run Install jelly dict.command to recreate the environment." >&2
    exit 1
  fi
fi

cd "${APP_DIR}"

if [[ "${INSTALL_MODE}" == "venv" ]]; then
  # shellcheck source=/dev/null
  source "${VENV_DIR}/bin/activate"
  jelly_prepare_qt_runtime_env python || true
  if [[ "${DETACH}" -eq 1 ]]; then
    mkdir -p "${APP_DIR}/.jelly_dict/logs"
    nohup python -m app.main >> "${APP_DIR}/.jelly_dict/logs/launcher.log" 2>&1 &
    exit 0
  fi
  exec python -m app.main
fi

if [[ "${DETACH}" -eq 1 ]]; then
  mkdir -p "${APP_DIR}/.jelly_dict/logs"
  if ! base_python="$(base_python_command)"; then
    echo "Python 3.12 or 3.11 not found. Run Install jelly dict.command." >&2
    exit 1
  fi
  jelly_prepare_qt_runtime_env "${base_python}" || true
  nohup "${base_python}" -m app.main >> "${APP_DIR}/.jelly_dict/logs/launcher.log" 2>&1 &
  exit 0
fi

if ! base_python="$(base_python_command)"; then
  echo "Python 3.12 or 3.11 not found. Run Install jelly dict.command." >&2
  exit 1
fi
jelly_prepare_qt_runtime_env "${base_python}" || true
exec "${base_python}" -m app.main
