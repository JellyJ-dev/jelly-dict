#!/usr/bin/env bash

JELLY_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
JELLY_SCRIPTS_DIR="$(cd "${JELLY_COMMON_DIR}/.." && pwd -P)"
JELLY_APP_FILES_ROOT="$(cd "${JELLY_SCRIPTS_DIR}/.." && pwd -P)"
JELLY_PUBLIC_ROOT="$(cd "${JELLY_APP_FILES_ROOT}/.." && pwd -P)"
JELLY_APP_DIR="${JELLY_APP_FILES_ROOT}/jelly_dict"
JELLY_VENV_DIR="${JELLY_APP_DIR}/.venv"

jelly_saved_install_mode() {
  local mode_file="$1"
  if [[ -f "${mode_file}" ]]; then
    local mode
    mode="$(tr -d '[:space:]' < "${mode_file}")"
    if [[ "${mode}" == "venv" || "${mode}" == "local" ]]; then
      printf '%s\n' "${mode}"
      return
    fi
  fi
  printf 'venv\n'
}

jelly_candidate_python_commands() {
  # Order matters: prefer versions with known-good Qt/macOS app behavior first.
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

jelly_python_is_supported() {
  "$1" - <<'PY' >/dev/null 2>&1
import sys
version = sys.version_info[:2]
raise SystemExit(0 if (3, 11) <= version < (3, 13) else 1)
PY
}

jelly_python_version_text() {
  "$1" - <<'PY' 2>/dev/null
import sys
print(sys.version.split()[0])
PY
}

jelly_venv_matches_current_location() {
  local venv_dir="$1"
  [[ -x "${venv_dir}/bin/python" ]] || return 1

  local actual expected
  actual="$("${venv_dir}/bin/python" -c 'import sys, os; print(os.path.realpath(sys.prefix))' 2>/dev/null)" || return 1
  [[ -n "${actual}" && -d "${actual}" ]] || return 1
  expected="$(cd "${venv_dir}" && pwd -P)"
  [[ "${actual}" == "${expected}" ]]
}

jelly_select_base_python() {
  local python_command_file="$1"
  local candidate
  local seen=":"

  if [[ -n "${JELLY_DICT_PYTHON:-}" ]]; then
    candidate="${JELLY_DICT_PYTHON}"
    if command -v "${candidate}" >/dev/null 2>&1 && jelly_python_is_supported "${candidate}"; then
      command -v "${candidate}"
      return 0
    fi
  fi

  if [[ -f "${python_command_file}" ]]; then
    candidate="$(tr -d '\r\n' < "${python_command_file}")"
    if [[ -n "${candidate}" && "${seen}" != *":${candidate}:"* ]]; then
      seen="${seen}${candidate}:"
      if command -v "${candidate}" >/dev/null 2>&1 && jelly_python_is_supported "${candidate}"; then
        command -v "${candidate}"
        return 0
      fi
    fi
  fi

  while IFS= read -r candidate; do
    [[ -n "${candidate}" ]] || continue
    [[ "${seen}" != *":${candidate}:"* ]] || continue
    seen="${seen}${candidate}:"
    if command -v "${candidate}" >/dev/null 2>&1 && jelly_python_is_supported "${candidate}"; then
      command -v "${candidate}"
      return 0
    fi
  done < <(jelly_candidate_python_commands)

  return 1
}

jelly_prepare_qt_runtime_env() {
  local python_bin="$1"
  local pyside_root

  pyside_root="$("${python_bin}" - <<'PY' 2>/dev/null
import importlib.util
from pathlib import Path

spec = importlib.util.find_spec("PySide6")
if spec is None or spec.origin is None:
    raise SystemExit(1)
print(Path(spec.origin).resolve().parent)
PY
)" || return 1

  if [[ -d "${pyside_root}/Qt/plugins/platforms" ]]; then
    export QT_PLUGIN_PATH="${pyside_root}/Qt/plugins"
    export QT_QPA_PLATFORM_PLUGIN_PATH="${pyside_root}/Qt/plugins/platforms"
  fi

  if [[ -d "${pyside_root}/Qt/qml" ]]; then
    case ":${QML2_IMPORT_PATH:-}:" in
      *":${pyside_root}/Qt/qml:"*) ;;
      *) export QML2_IMPORT_PATH="${pyside_root}/Qt/qml${QML2_IMPORT_PATH:+:${QML2_IMPORT_PATH}}" ;;
    esac
  fi

  export QT_MAC_WANTS_LAYER=1
}
