#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_FILES_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PUBLIC_ROOT="$(cd "${APP_FILES_ROOT}/.." && pwd)"
OUT_DIR="${PUBLIC_ROOT}/dist/jelly-dict"
APP_FILES="${OUT_DIR}/app_files"

# Apply privacy filters to every source directory, including assets and scripts.
PRIVATE_EXCLUDES=(
  --exclude "docs/"
  --exclude "logs/"
  --exclude "*.md"
  --exclude "*.log"
  --exclude "*.log.*"
  --exclude "*.out"
  --exclude "*.err"
  --exclude "*.trace"
  --exclude "*.har"
  --exclude "*.json"
  --exclude "*.csv"
  --exclude "*.xls"
  --exclude "*.xlsx"
  --exclude "*.apkg"
  --exclude "*.tsv"
  --exclude "*.pdf"
  --exclude "*.docx"
  --exclude "*.zip"
  --exclude ".env"
  --exclude ".env.*"
  --exclude "*.key"
  --exclude "*.pem"
  --exclude "*.secret"
  --exclude "secrets.*"
  --exclude "*.sqlite"
  --exclude "*.sqlite3"
  --exclude "*.db"
)

usage() {
  cat <<'USAGE'
Usage: app_files/scripts/make_user_package.sh

Create an ignored dist/jelly-dict folder for user distribution.
USAGE
}

if [[ $# -gt 0 ]]; then
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
fi

if [[ -e "${OUT_DIR}" ]]; then
  echo "Output already exists: ${OUT_DIR}" >&2
  echo "Move or delete that folder first, then run this script again." >&2
  exit 1
fi

mkdir -p "${APP_FILES}"

cp "${PUBLIC_ROOT}/Install jelly dict.command" "${OUT_DIR}/"
cp "${PUBLIC_ROOT}/Update jelly dict.command" "${OUT_DIR}/"
cp "${PUBLIC_ROOT}/Run jelly dict.command" "${OUT_DIR}/"
cp "${PUBLIC_ROOT}/README.md" "${OUT_DIR}/"

for dir in assets packaging; do
  if [[ -d "${APP_FILES_ROOT}/${dir}" ]]; then
    mkdir -p "${APP_FILES}/${dir}"
    rsync -a "${PRIVATE_EXCLUDES[@]}" \
      --exclude ".DS_Store" \
      --exclude "__pycache__/" \
      --exclude "source/" \
      --include "/macos/" \
      --include "/app-icon-1024.png" \
      --include "/app-icon.icns" \
      --include "/macos/Info.plist" \
      --include "/macos/build_app.sh" \
      --include "/macos/jelly-dict-launcher.c" \
      --include "/macos/launcher.sh" \
      --include "/macos/make_icns.sh" \
      --exclude "*" \
      "${APP_FILES_ROOT}/${dir}/" "${APP_FILES}/${dir}/"
  fi
done

rsync -a --include "/README.md" "${PRIVATE_EXCLUDES[@]}" \
  --exclude ".DS_Store" \
  --exclude "tests/" \
  --exclude "benchmarks/" \
  --exclude "requirements-dev.txt" \
  --exclude ".venv/" \
  --exclude ".jelly_dict/" \
  --exclude ".mypy_cache/" \
  --exclude ".pytest_cache/" \
  --exclude ".ruff_cache/" \
  --exclude ".coverage" \
  --exclude "coverage.json" \
  --exclude ".install_mode" \
  --exclude ".install_incomplete" \
  --exclude ".python_cmd" \
  --exclude ".quickstart_ok" \
  --exclude "__pycache__/" \
  --exclude "*.pyc" \
  --exclude "*.xlsx" \
  --exclude "*.apkg" \
  --exclude "*.tsv" \
  --exclude "*.log" \
  --exclude "benchmarks/*.json" \
  --exclude ".env" \
  --exclude ".env.*" \
  --exclude "*.key" \
  --exclude "*.pem" \
  --exclude "*.secret" \
  --exclude "secrets.*" \
  --exclude "settings.local.json" \
  --exclude "*.sqlite" \
  --exclude "*.sqlite3" \
  --exclude "*.db" \
  --include "/app/" \
  --include "/app/**/" \
  --include "/app/*.py" \
  --include "/app/**/*.py" \
  --include "/app/anki/templates/***" \
  --include "/app/ui/resources/theme.qss" \
  --include "/resources/" \
  --include "/resources/icons/" \
  --include "/resources/icons/*.svg" \
  --include "/constraints/" \
  --include "/constraints/*.txt" \
  --include "/pyproject.toml" \
  --include "/requirements.txt" \
  --include "/requirements-tts.txt" \
  --exclude "*" \
  "${APP_FILES_ROOT}/jelly_dict/" "${APP_FILES}/jelly_dict/"

rsync -a "${PRIVATE_EXCLUDES[@]}" \
  --exclude ".DS_Store" \
  --exclude "make_user_package.sh" \
  --exclude "quality_gate.sh" \
  --exclude "check_coverage.py" \
  --exclude "dump_naver_entry.py" \
  --exclude "__pycache__/" \
  --include "/lib/" \
  --include "/lib/common.sh" \
  --include "/lib/install_flow.sh" \
  --include "/lib/terminal_ui.sh" \
  --include "/check_release_metadata.py" \
  --include "/cleanup.sh" \
  --include "/install_app.sh" \
  --include "/macos_app_smoke.py" \
  --include "/quickstart.sh" \
  --include "/run.sh" \
  --include "/runtime_checker.py" \
  --include "/sync_dependency_files.py" \
  --exclude "*" \
  "${APP_FILES_ROOT}/scripts/" "${APP_FILES}/scripts/"

for doc in LICENSE LICENSE_NOTICE.txt THIRD_PARTY_NOTICES.md; do
  if [[ -f "${APP_FILES_ROOT}/${doc}" ]]; then
    cp "${APP_FILES_ROOT}/${doc}" "${APP_FILES}/"
  fi
done

chmod +x "${OUT_DIR}/Install jelly dict.command" "${OUT_DIR}/Update jelly dict.command" "${OUT_DIR}/Run jelly dict.command"
chmod +x "${APP_FILES}/scripts/install_app.sh" "${APP_FILES}/scripts/quickstart.sh" "${APP_FILES}/scripts/run.sh"
chmod +x "${APP_FILES}/packaging/macos/build_app.sh" "${APP_FILES}/packaging/macos/make_icns.sh" 2>/dev/null || true

echo "Created: ${OUT_DIR}"
echo
echo "Top-level files:"
find "${OUT_DIR}" -maxdepth 1 -print | sort
