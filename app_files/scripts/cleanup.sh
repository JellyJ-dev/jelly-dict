#!/usr/bin/env bash
# Backend cleanup helper. Run via "Reset jelly dict.command" or directly:
#   scripts/cleanup.sh --sandbox        # venv + setup markers (safe)
#   scripts/cleanup.sh --data           # also wipe runtime data (.jelly_dict)
#   scripts/cleanup.sh --playwright     # also wipe Playwright browser cache
#   scripts/cleanup.sh --all            # sandbox + runtime data + Playwright cache
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
APP_DIR="${REPO_ROOT}/jelly_dict"
VENV_DIR="${APP_DIR}/.venv"
RUNTIME_DIR="${APP_DIR}/.jelly_dict"
PLAYWRIGHT_CACHE="${HOME}/Library/Caches/ms-playwright"

WIPE_SANDBOX=0
WIPE_DATA=0
WIPE_PLAYWRIGHT=0

usage() {
  cat <<'USAGE'
Usage: cleanup.sh [--sandbox] [--data] [--playwright] [--all]

  --sandbox      Remove .venv and setup markers (safe, reinstallable).
  --data         Also remove runtime data (.jelly_dict): settings, cache, logs.
  --playwright   Also remove Playwright browser cache (~/Library/Caches/ms-playwright).
  --all          Equivalent to --sandbox --data --playwright.

User vocab/Anki files at ~/Documents/jelly-dict are never removed by this script.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sandbox)    WIPE_SANDBOX=1 ;;
    --data)       WIPE_SANDBOX=1; WIPE_DATA=1 ;;
    --playwright) WIPE_PLAYWRIGHT=1 ;;
    --all)        WIPE_SANDBOX=1; WIPE_DATA=1; WIPE_PLAYWRIGHT=1 ;;
    -h|--help)    usage; exit 0 ;;
    *)            echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if (( WIPE_SANDBOX == 0 && WIPE_DATA == 0 && WIPE_PLAYWRIGHT == 0 )); then
  usage >&2
  exit 2
fi

remove_path() {
  local label="$1" path="$2"
  if [[ -e "${path}" || -L "${path}" ]]; then
    printf '  removing %s (%s)\n' "${label}" "${path}"
    rm -rf -- "${path}"
    return 0
  else
    printf '  skip %s (not present)\n' "${label}"
    return 0
  fi
}

if (( WIPE_SANDBOX )); then
  remove_path "virtual environment" "${VENV_DIR}"
  remove_path "install mode marker"  "${APP_DIR}/.install_mode"
  remove_path "python command marker" "${APP_DIR}/.python_cmd"
  remove_path "setup state marker"   "${APP_DIR}/.quickstart_ok"
fi

if (( WIPE_DATA )); then
  remove_path "runtime data" "${RUNTIME_DIR}"
fi

if (( WIPE_PLAYWRIGHT )); then
  remove_path "Playwright browser cache" "${PLAYWRIGHT_CACHE}"
fi

echo "done."
