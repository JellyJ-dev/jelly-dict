#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd -P)"
APP_FILES_DIR="${REPO_ROOT}/app_files"
APP_SOURCE_DIR="${APP_FILES_DIR}/jelly_dict"
DIST_DIR="${APP_FILES_DIR}/dist"
APP_NAME="Jelly Dict.app"
APP_DIR="${DIST_DIR}/${APP_NAME}"
CONTENTS_DIR="${APP_DIR}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"
BUILD_DIR="${APP_FILES_DIR}/build/macos"

INFO_PLIST="${SCRIPT_DIR}/Info.plist"
LAUNCHER="${SCRIPT_DIR}/launcher.sh"
ICON_FILE="${APP_FILES_DIR}/assets/app-icon.icns"
SHIM_SOURCE="${SCRIPT_DIR}/jelly-dict-launcher.c"
EMBED_FLAGS_FILE="${BUILD_DIR}/python-embed-flags.sh"

# shellcheck source=app_files/scripts/lib/common.sh
source "${APP_FILES_DIR}/scripts/lib/common.sh"

for required in "${INFO_PLIST}" "${LAUNCHER}" "${ICON_FILE}" "${SHIM_SOURCE}"; do
  if [[ ! -f "${required}" ]]; then
    echo "Required file missing: ${required}" >&2
    exit 1
  fi
done

select_embed_python() {
  local candidate

  candidate="${APP_SOURCE_DIR}/.venv/bin/python"
  if [[ -x "${candidate}" ]] && jelly_python_is_supported "${candidate}"; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  if [[ -f "${APP_SOURCE_DIR}/.python_cmd" ]]; then
    candidate="$(tr -d '\r\n' < "${APP_SOURCE_DIR}/.python_cmd")"
    if [[ -n "${candidate}" && "$(command -v "${candidate}" 2>/dev/null || true)" != "" ]] && jelly_python_is_supported "${candidate}"; then
      command -v "${candidate}"
      return 0
    fi
  fi

  while IFS= read -r candidate; do
    if command -v "${candidate}" >/dev/null 2>&1 && jelly_python_is_supported "${candidate}"; then
      command -v "${candidate}"
      return 0
    fi
  done < <(jelly_candidate_python_commands)

  return 1
}

rm -rf "${APP_DIR}"
mkdir -p "${MACOS_DIR}" "${RESOURCES_DIR}" "${BUILD_DIR}"

cp "${INFO_PLIST}" "${CONTENTS_DIR}/Info.plist"
cp "${LAUNCHER}" "${RESOURCES_DIR}/launcher.sh"
cp "${ICON_FILE}" "${RESOURCES_DIR}/app_icon.icns"
printf '%s\n' "${REPO_ROOT}" > "${RESOURCES_DIR}/repo_path.txt"

if ! command -v cc >/dev/null 2>&1; then
  echo "cc not found. Install Xcode Command Line Tools, then rerun Install jelly dict.command." >&2
  exit 1
fi

if ! EMBED_PYTHON="$(select_embed_python)"; then
  echo "Python 3.12 or 3.11 not found for embedded app launcher." >&2
  echo "Run app_files/scripts/quickstart.sh first." >&2
  exit 1
fi

"${EMBED_PYTHON}" - <<'PY' > "${EMBED_FLAGS_FILE}"
from __future__ import annotations

import shlex
import sysconfig
from pathlib import Path


def quote_words(name: str, values: list[str]) -> None:
    print(f"{name}=(" + " ".join(shlex.quote(value) for value in values if value) + ")")


include = sysconfig.get_config_var("INCLUDEPY")
libdir = sysconfig.get_config_var("LIBDIR")
version = sysconfig.get_config_var("VERSION")
ldlibrary = sysconfig.get_config_var("LDLIBRARY") or ""
library = sysconfig.get_config_var("LIBRARY") or ""
libs = shlex.split(sysconfig.get_config_var("LIBS") or "")
libs += shlex.split(sysconfig.get_config_var("SYSLIBS") or "")
# Match python-config --ldflags --embed: LINKFORSHARED is for rebuilding
# Python itself and can contain a relative Python.framework build-tree path.
# The installed embed library is resolved explicitly below.

if not include or not Path(include).is_dir():
    raise SystemExit("Python headers not found")
if not libdir or not Path(libdir).is_dir():
    raise SystemExit("Python library directory not found")

libdir_path = Path(libdir)
library_candidates = [
    ldlibrary,
    library,
    f"libpython{version}.dylib",
    f"libpython{version}.a",
]
library_path = next(
    (libdir_path / name for name in library_candidates if name and (libdir_path / name).exists()),
    None,
)
if library_path is None:
    raise SystemExit("Python embed library not found")

ldflags = [str(library_path), *libs]
if library_path.suffix == ".dylib":
    ldflags.insert(0, f"-Wl,-rpath,{libdir}")

quote_words("EMBED_CFLAGS", [f"-I{include}"])
quote_words("EMBED_LDFLAGS", ldflags)
PY

# shellcheck source=/dev/null
source "${EMBED_FLAGS_FILE}"

cc -Os -Wall -Wextra "${EMBED_CFLAGS[@]}" -o "${MACOS_DIR}/jelly-dict" "${SHIM_SOURCE}" "${EMBED_LDFLAGS[@]}"

chmod 755 "${MACOS_DIR}/jelly-dict" "${RESOURCES_DIR}/launcher.sh"

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "${APP_DIR}"
else
  echo "codesign not found; leaving app bundle unsigned." >&2
fi

echo "Created ${APP_DIR}"
