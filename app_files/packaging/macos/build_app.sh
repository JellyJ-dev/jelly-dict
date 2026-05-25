#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd -P)"
APP_FILES_DIR="${REPO_ROOT}/app_files"
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
SHIM_SOURCE="${BUILD_DIR}/jelly-dict-launcher.c"

for required in "${INFO_PLIST}" "${LAUNCHER}" "${ICON_FILE}"; do
  if [[ ! -f "${required}" ]]; then
    echo "Required file missing: ${required}" >&2
    exit 1
  fi
done

rm -rf "${APP_DIR}"
mkdir -p "${MACOS_DIR}" "${RESOURCES_DIR}" "${BUILD_DIR}"

cp "${INFO_PLIST}" "${CONTENTS_DIR}/Info.plist"
cp "${LAUNCHER}" "${RESOURCES_DIR}/launcher.sh"
cp "${ICON_FILE}" "${RESOURCES_DIR}/app_icon.icns"
printf '%s\n' "${REPO_ROOT}" > "${RESOURCES_DIR}/repo_path.txt"

cat > "${SHIM_SOURCE}" <<'C'
#include <mach-o/dyld.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(void) {
  char executable[PATH_MAX];
  char resolved[PATH_MAX];
  char script[PATH_MAX];
  uint32_t size = sizeof(executable);

  if (_NSGetExecutablePath(executable, &size) != 0) {
    fprintf(stderr, "Unable to locate executable path.\n");
    return 1;
  }

  if (realpath(executable, resolved) == NULL) {
    perror("realpath");
    return 1;
  }

  char *slash = strrchr(resolved, '/');
  if (slash == NULL) {
    fprintf(stderr, "Unexpected executable path.\n");
    return 1;
  }
  *slash = '\0';

  if (snprintf(script, sizeof(script), "%s/../Resources/launcher.sh", resolved) >= (int)sizeof(script)) {
    fprintf(stderr, "Launcher path is too long.\n");
    return 1;
  }

  char *const argv[] = {"/bin/bash", script, NULL};
  execv("/bin/bash", argv);
  perror("execv");
  return 127;
}
C

if command -v cc >/dev/null 2>&1; then
  cc -Os -Wall -Wextra -o "${MACOS_DIR}/jelly-dict" "${SHIM_SOURCE}"
else
  echo "cc not found; falling back to shell launcher executable." >&2
  cp "${LAUNCHER}" "${MACOS_DIR}/jelly-dict"
fi

chmod 755 "${MACOS_DIR}/jelly-dict" "${RESOURCES_DIR}/launcher.sh"

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "${APP_DIR}"
else
  echo "codesign not found; leaving app bundle unsigned." >&2
fi

echo "Created ${APP_DIR}"
