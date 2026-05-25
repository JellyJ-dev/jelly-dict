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
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
APP_DIR="${REPO_ROOT}/jelly_dict"
VENV_DIR="${APP_DIR}/.venv"
INSTALL_MODE_FILE="${APP_DIR}/.install_mode"
PYTHON_COMMAND_FILE="${APP_DIR}/.python_cmd"
SETUP_STATE_FILE="${APP_DIR}/.quickstart_ok"

INSTALL_MODE="venv"
if [[ -f "${INSTALL_MODE_FILE}" ]]; then
  saved_mode="$(tr -d '[:space:]' < "${INSTALL_MODE_FILE}")"
  if [[ "${saved_mode}" == "venv" || "${saved_mode}" == "local" ]]; then
    INSTALL_MODE="${saved_mode}"
  fi
fi

base_python_command() {
  local candidate=""
  if [[ -f "${PYTHON_COMMAND_FILE}" ]]; then
    candidate="$(tr -d '\r\n' < "${PYTHON_COMMAND_FILE}")"
  fi

  if [[ -n "${candidate}" ]] && command -v "${candidate}" >/dev/null 2>&1; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    printf 'python3\n'
    return 0
  fi

  return 1
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

venv_matches_current_location() {
  # Use Python introspection — robust across CPython activate-template
  # changes and symlinked roots (e.g. /tmp → /private/tmp on macOS).
  [[ -x "${VENV_DIR}/bin/python" ]] || return 1

  local actual expected
  actual="$("${VENV_DIR}/bin/python" -c 'import sys, os; print(os.path.realpath(sys.prefix))' 2>/dev/null)" || return 1
  [[ -n "${actual}" && -d "${actual}" ]] || return 1
  expected="$(cd "${VENV_DIR}" && pwd -P)"
  [[ "${actual}" == "${expected}" ]]
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

  if ! venv_matches_current_location; then
    echo "Virtual environment was created for a different folder." >&2
    echo "Run Install jelly dict.command and allow dependency installation to recreate it." >&2
    echo "  ${REPO_ROOT}/scripts/quickstart.sh" >&2
    exit 1
  fi
fi

cd "${APP_DIR}"

if [[ "${INSTALL_MODE}" == "venv" ]]; then
  # shellcheck source=/dev/null
  source "${VENV_DIR}/bin/activate"
  if [[ "${DETACH}" -eq 1 ]]; then
    mkdir -p "${APP_DIR}/.jelly_dict/logs"
    nohup python -m app.main >> "${APP_DIR}/.jelly_dict/logs/launcher.log" 2>&1 &
    exit 0
  fi
  exec python -m app.main
fi

if [[ "${DETACH}" -eq 1 ]]; then
  mkdir -p "${APP_DIR}/.jelly_dict/logs"
  base_python="$(base_python_command)"
  nohup "${base_python}" -m app.main >> "${APP_DIR}/.jelly_dict/logs/launcher.log" 2>&1 &
  exit 0
fi

base_python="$(base_python_command)"
exec "${base_python}" -m app.main
