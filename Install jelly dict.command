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

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
JELLY_DICT_VERSION="1.0.1"

APP_NAME="Jelly Dict.app"
QUICKSTART_SCRIPT="${SCRIPT_DIR}/app_files/scripts/quickstart.sh"
BUILD_APP_SCRIPT="${SCRIPT_DIR}/app_files/packaging/macos/build_app.sh"
DIST_APP="${SCRIPT_DIR}/app_files/dist/${APP_NAME}"
USER_APPS_DIR="${HOME}/Applications"
USER_APP="${USER_APPS_DIR}/${APP_NAME}"
QUICKSTART_LOG="${SCRIPT_DIR}/app_files/jelly_dict/.jelly_dict/logs/quickstart.log"
INSTALL_LOG="${SCRIPT_DIR}/app_files/jelly_dict/.jelly_dict/logs/install_app.log"
APP_DIR="${SCRIPT_DIR}/app_files/jelly_dict"
VENV_DIR="${APP_DIR}/.venv"
INSTALL_INCOMPLETE_FILE="${APP_DIR}/.install_incomplete"

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

term_cols() {
  local cols
  cols="$(tput cols 2>/dev/null || echo "${COLUMNS:-80}")"
  [[ -z "${cols}" || "${cols}" -lt 40 ]] && cols=80
  printf '%s' "${cols}"
}

term_rows() {
  local rows
  rows="$(tput lines 2>/dev/null || echo "${LINES:-24}")"
  [[ -z "${rows}" || "${rows}" -lt 10 ]] && rows=24
  printf '%s' "${rows}"
}

clear_screen() {
  [[ -t 1 ]] || return
  if command -v clear >/dev/null 2>&1; then clear; else printf '\033c'; fi
}

repeat_char() {
  local ch="$1" n="$2" out=""
  while ((n-- > 0)); do out+="${ch}"; done
  printf '%s' "${out}"
}

strip_ansi() {
  printf '%s' "$1" | LC_ALL=C sed $'s/\033\\[[0-9;?]*[A-Za-z]//g'
}

vlen() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c '
import sys, unicodedata
s = sys.argv[1] if len(sys.argv) > 1 else ""
w = 0
for c in s:
    if unicodedata.category(c).startswith("M"):
        continue
    w += 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
print(w)
' "$1"
  else
    printf '%s' "$1" | awk '{print length($0)}'
  fi
}

draw_border() {
  local pos="$1" title="${2:-}" cols width left right bar
  cols="$(term_cols)"
  width=$(( cols - 2 ))
  ((width < 30)) && width=30

  case "${pos}" in
    top) left="╭"; right="╮"; bar="─" ;;
    mid) left="├"; right="┤"; bar="─" ;;
    bottom) left="╰"; right="╯"; bar="─" ;;
  esac

  if [[ -n "${title}" ]]; then
    local chip=" ${title} "
    local chip_w left_bar right_bar
    chip_w="$(vlen "${chip}")"
    left_bar=$(( (width - chip_w) / 2 ))
    right_bar=$(( width - chip_w - left_bar ))
    ((left_bar < 2)) && left_bar=2
    ((right_bar < 2)) && right_bar=2
    printf '%s%s%s%s%s%s%s\n' \
      "${ACCENT}" "${left}" \
      "$(repeat_char "${bar}" "${left_bar}")" \
      "${RESET}${BOLD}${CREAM}${chip}${RESET}${ACCENT}" \
      "$(repeat_char "${bar}" "${right_bar}")" \
      "${right}" "${RESET}"
  else
    printf '%s%s%s%s%s\n' "${ACCENT}" "${left}" "$(repeat_char "${bar}" "${width}")" "${right}" "${RESET}"
  fi
}

frame_line() {
  local text="${1:-}" cols width plain w pad
  cols="$(term_cols)"
  width=$(( cols - 2 ))
  ((width < 30)) && width=30
  plain="$(strip_ansi "${text}")"
  w="$(vlen "${plain}")"
  pad=$(( width - w ))
  ((pad < 0)) && pad=0
  printf '%s│%s%s%s%s│%s\n' "${ACCENT}" "${RESET}" "${text}" "$(repeat_char ' ' "${pad}")" "${ACCENT}" "${RESET}"
}

frame_blank() { frame_line ""; }

brand_logo_lines() {
  cat <<'LOGO'
     ██╗███████╗██╗     ██╗  ██╗   ██╗    ██████╗ ██╗ ██████╗████████╗
     ██║██╔════╝██║     ██║  ╚██╗ ██╔╝    ██╔══██╗██║██╔════╝╚══██╔══╝
     ██║█████╗  ██║     ██║   ╚████╔╝     ██║  ██║██║██║        ██║
██   ██║██╔══╝  ██║     ██║    ╚██╔╝      ██║  ██║██║██║        ██║
╚█████╔╝███████╗███████╗███████╗██║       ██████╔╝██║╚██████╗   ██║
 ╚════╝ ╚══════╝╚══════╝╚══════╝╚═╝       ╚═════╝ ╚═╝ ╚═════╝   ╚═╝
LOGO
}

print_header() {
  local step_label="${1:-}" step_caption="${2:-}" force_mode="${3:-}"
  local cols rows mode
  cols="$(term_cols)"
  rows="$(term_rows)"
  clear_screen

  mode="normal"
  if   (( rows < 16 || cols < 50 )); then mode="tiny"
  elif (( rows < 22 ));               then mode="compact"
  fi
  [[ -n "${force_mode}" ]] && mode="${force_mode}"

  if [[ "${mode}" == "tiny" ]]; then
    printf '%s%s✦ jelly dict%s  %s· Installer · v%s%s\n\n' \
      "${BOLD}" "${ACCENT}" "${RESET}" "${MUTED}" "${JELLY_DICT_VERSION}" "${RESET}"
    [[ -n "${step_label}" ]] && printf '%s●%s %s%s%s   %s%s%s\n\n' \
      "${ACCENT}" "${RESET}" "${BOLD}${INK}" "${step_label}" "${RESET}" "${MUTED}" "${step_caption}" "${RESET}"
    return
  fi

  draw_border top "jelly dict  ·  Installer  ·  v${JELLY_DICT_VERSION}"
  frame_blank

  if [[ "${mode}" == "normal" ]]; then
    local -a logo=()
    local line max_w=0 w inner lead pad
    while IFS= read -r line; do
      logo+=("${line}")
      w="$(vlen "${line}")"
      (( w > max_w )) && max_w=$w
    done < <(brand_logo_lines)
    inner=$(( cols - 2 ))
    lead=$(( (inner - max_w) / 2 ))
    (( lead < 0 )) && lead=0
    pad="$(repeat_char ' ' "${lead}")"
    for line in "${logo[@]}"; do
      frame_line "${pad}${CREAM}${line}${RESET}"
    done
    frame_blank
  fi

  draw_border bottom

  if [[ -n "${step_label}" ]]; then
    if [[ -n "${step_caption}" ]]; then
      printf '\n  %s●%s %s%s%s   %s%s%s\n' \
        "${ACCENT}" "${RESET}" "${BOLD}${INK}" "${step_label}" "${RESET}" "${MUTED}" "${step_caption}" "${RESET}"
    else
      printf '\n  %s●%s %s%s%s\n' "${ACCENT}" "${RESET}" "${BOLD}${INK}" "${step_label}" "${RESET}"
    fi
  fi
  printf '\n'
}

body() {
  local pad=2 line
  while IFS= read -r line; do
    printf '%*s%s\n' "${pad}" "" "${line}"
  done <<<"$1"
}

success() { printf '  %s✓%s %s\n' "${GREEN}" "${RESET}" "$1"; }
warn()    { printf '  %s!%s %s\n' "${ACCENT}" "${RESET}" "$1"; }
fail_ln() { printf '  %s✗%s %s\n' "${RED}" "${RESET}" "$1"; }
note()    { printf '  %s%s%s\n' "${MUTED}" "$1" "${RESET}"; }

read_key() {
  local k k2 k3
  IFS= read -rsn1 k || return 1
  if [[ "${k}" == $'\x1b' ]]; then
    IFS= read -rsn1 -t "${ESC_READ_TIMEOUT}" k2 || { printf 'esc'; return; }
    if [[ "${k2}" == "[" || "${k2}" == "O" ]]; then
      IFS= read -rsn1 -t "${ESC_READ_TIMEOUT}" k3 || { printf 'esc'; return; }
      case "${k3}" in
        A) printf 'up' ;;
        B) printf 'down' ;;
        C) printf 'right' ;;
        D) printf 'left' ;;
        *) printf 'esc' ;;
      esac
    else
      printf 'esc'
    fi
    return
  fi
  case "${k}" in
    ""|$'\n'|$'\r'|" ") printf 'enter' ;;
    q|Q) printf 'q' ;;
    y|Y) printf 'y' ;;
    n|N) printf 'n' ;;
    *) printf 'char:%s' "${k}" ;;
  esac
}

ask_choice() {
  local prompt="$1" default_idx="$2"; shift 2
  local options=("$@")
  local count=${#options[@]}
  local idx=$default_idx
  CHOICE_INDEX=$idx
  CHOICE_TEXT="${options[$idx]}"

  if [[ ! -t 0 || ! -t 1 ]]; then
    return 0
  fi

  printf '  %s%s%s\n' "${BOLD}${INK}" "${prompt}" "${RESET}"
  printf '  %s↑/↓ 또는 ←/→ 로 이동, Enter로 선택%s\n\n' "${MUTED}" "${RESET}"

  printf '%s' "${HIDE_CURSOR}"
  stty -echo -icanon 2>/dev/null || true

  local first=1
  while true; do
    if (( first )); then
      first=0
    else
      printf '\033[1A\033[2K'
    fi

    local line="  "
    local i
    for ((i=0; i<count; i++)); do
      if (( i == idx )); then
        line+="${BOLD}${ACCENT}❯ ${CREAM}${options[i]}${RESET}"
      else
        line+="${FAINT}  ${options[i]}${RESET}"
      fi
      (( i < count - 1 )) && line+="    "
    done
    printf '%s\n' "${line}"

    local key
    key="$(read_key)"
    case "${key}" in
      up|left)    (( idx > 0 )) && idx=$(( idx - 1 )) ;;
      down|right) (( idx < count - 1 )) && idx=$(( idx + 1 )) ;;
      enter)      break ;;
      q|esc)      stty echo icanon 2>/dev/null || true
                  printf '%s' "${SHOW_CURSOR}"
                  return 130 ;;
      char:1)     (( count >= 1 )) && { idx=0; break; } ;;
      char:2)     (( count >= 2 )) && { idx=1; break; } ;;
      char:3)     (( count >= 3 )) && { idx=2; break; } ;;
      char:4)     (( count >= 4 )) && { idx=3; break; } ;;
    esac
  done

  stty echo icanon 2>/dev/null || true
  printf '%s\n' "${SHOW_CURSOR}"
  CHOICE_INDEX=$idx
  CHOICE_TEXT="${options[$idx]}"
  return 0
}

ask_vertical_choice() {
  local prompt="$1" default_idx="$2"; shift 2
  local -a labels=() hints=()
  local item
  for item in "$@"; do
    labels+=("${item%%::*}")
    hints+=("${item#*::}")
  done
  local count=${#labels[@]}
  local idx=$default_idx
  CHOICE_INDEX=$idx

  if [[ ! -t 0 || ! -t 1 ]]; then
    return 0
  fi

  printf '  %s%s%s\n' "${BOLD}${INK}" "${prompt}" "${RESET}"
  printf '  %s↑/↓ 로 이동, Enter로 선택, q 로 취소%s\n' "${MUTED}" "${RESET}"

  printf '%s' "${HIDE_CURSOR}"
  stty -echo -icanon 2>/dev/null || true

  local rendered=0 i
  while true; do
    if (( rendered )); then
      printf '\033[%dA' "$(( count * 2 + 1 ))"
    fi
    rendered=1

    printf '\033[2K\n'
    for ((i=0; i<count; i++)); do
      if (( i == idx )); then
        printf '\033[2K  %s❯ %s%s%s\n' "${ACCENT}" "${CREAM}${BOLD}" "${labels[i]}" "${RESET}"
        printf '\033[2K      %s%s%s\n'  "${MUTED}" "${hints[i]}" "${RESET}"
      else
        printf '\033[2K  %s  %s%s\n'    "${FAINT}" "${labels[i]}" "${RESET}"
        printf '\033[2K      %s%s%s\n'  "${FAINT}" "${hints[i]}" "${RESET}"
      fi
    done

    local key
    key="$(read_key)"
    case "${key}" in
      up|left)    (( idx > 0 )) && idx=$(( idx - 1 )) ;;
      down|right) (( idx < count - 1 )) && idx=$(( idx + 1 )) ;;
      enter)      break ;;
      char:1)     (( count >= 1 )) && { idx=0; break; } ;;
      char:2)     (( count >= 2 )) && { idx=1; break; } ;;
      char:3)     (( count >= 3 )) && { idx=2; break; } ;;
      char:4)     (( count >= 4 )) && { idx=3; break; } ;;
      q|esc)      stty echo icanon 2>/dev/null || true
                  printf '%s' "${SHOW_CURSOR}"
                  return 130 ;;
    esac
  done

  stty echo icanon 2>/dev/null || true
  printf '%s\n' "${SHOW_CURSOR}"
  CHOICE_INDEX=$idx
  return 0
}

ask_yes_no() {
  local prompt="$1" default="$2"
  local default_idx=1
  [[ "${default}" == "yes" ]] && default_idx=0

  ask_choice "${prompt}" "${default_idx}" "예  Yes" "아니오  No"
  local rc=$?
  (( rc == 130 )) && return 1
  (( CHOICE_INDEX == 0 ))
}

ask_install_mode() {
  INSTALL_MODE_CHOICE="venv"
  ask_vertical_choice "설치 위치를 선택하세요" 0 \
    "전용 가상환경 (권장)::이 앱 폴더 안 .venv 에만 설치합니다" \
    "현재 로컬 Python::현재 사용 중인 Python에 직접 설치합니다"
  local rc=$?
  (( rc == 130 )) && return 130
  if (( CHOICE_INDEX == 0 )); then
    INSTALL_MODE_CHOICE="venv"
  else
    INSTALL_MODE_CHOICE="local"
  fi
  return 0
}

press_any_key() {
  local msg="${1:-계속하려면 아무 키나 누르세요}"
  printf '\n  %s%s%s' "${MUTED}" "${msg}" "${RESET}"
  if [[ -t 0 ]]; then
    stty -echo -icanon 2>/dev/null || true
    IFS= read -rsn1 _ || true
    stty echo icanon 2>/dev/null || true
  fi
  printf '\n'
}

spin() {
  local label="$1"; shift
  if [[ ! -t 1 ]]; then
    "$@"
    return $?
  fi

  local frames=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
  printf '%s' "${HIDE_CURSOR}"
  ( "$@" ) &
  local pid=$!
  local i=0
  while kill -0 "${pid}" 2>/dev/null; do
    printf '\r  %s%s%s %s' "${ACCENT}" "${frames[i]}" "${RESET}" "${label}"
    i=$(( (i + 1) % ${#frames[@]} ))
    sleep 0.08
  done
  wait "${pid}"
  local rc=$?
  if (( rc == 0 )); then
    printf '\r  %s✓%s %s\n' "${GREEN}" "${RESET}" "${label}"
  else
    printf '\r  %s✗%s %s\n' "${RED}" "${RESET}" "${label}"
  fi
  printf '%s' "${SHOW_CURSOR}"
  return $rc
}

progress_bar() {
  local percent="${1:-}"
  local width="${2:-28}"
  local filled=0 empty

  if [[ "${percent}" =~ ^[0-9]+$ ]]; then
    (( percent < 0 )) && percent=0
    (( percent > 100 )) && percent=100
    filled=$(( percent * width / 100 ))
  fi
  empty=$(( width - filled ))
  printf '%s%s' "$(repeat_char '█' "${filled}")" "$(repeat_char '░' "${empty}")"
}

short_text() {
  local text="$1"
  local limit="${2:-64}"
  if (( ${#text} > limit )); then
    printf '%s…' "${text:0:$((limit - 1))}"
  else
    printf '%s' "${text}"
  fi
}

install_progress_snapshot() {
  local log_path="$1"

  if [[ ! -f "${log_path}" ]]; then
    printf '준비 중\t대기 중\t\n'
    return
  fi

  if command -v python3 >/dev/null 2>&1; then
    python3 - "${log_path}" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text(errors="replace")[-60000:]
lines = [line.strip() for line in text.replace("\r", "\n").splitlines() if line.strip()]

stage = "준비 중"
current = "대기 중"
percent = ""

for line in lines:
    if line.startswith("## "):
        stage = line[3:].strip()
        current = "준비 중"
        percent = ""
        continue

    if line.startswith("Collecting "):
        current = "패키지 확인: " + line[len("Collecting "):].split()[0]
    elif line.startswith("Downloading "):
        current = "다운로드: " + Path(line[len("Downloading "):].split()[0]).name
    elif line.startswith("Using cached "):
        current = "캐시 사용: " + Path(line[len("Using cached "):].split()[0]).name
    elif line.startswith("Installing collected packages:"):
        package_text = line.split(":", 1)[1].strip()
        count = len([part for part in package_text.split(",") if part.strip()])
        current = f"패키지 적용 중: {count}개"
        if not percent:
            percent = "90"
    elif line.startswith("Successfully installed"):
        current = "패키지 설치 완료"
        percent = "100"
    elif "Downloading Webkit" in line or "Downloading WebKit" in line:
        current = "Playwright WebKit 다운로드"
    elif "Failed to install browsers" in line:
        current = "Playwright WebKit 설치 실패"

    size_match = re.search(r"([0-9]+(?:\.[0-9]+)?)/([0-9]+(?:\.[0-9]+)?)\s*([kMGT]?B)", line)
    if size_match:
        done = float(size_match.group(1))
        total = float(size_match.group(2))
        if total > 0:
            percent = str(max(0, min(100, round(done / total * 100))))

    pct_match = re.search(r"\b([0-9]{1,3})%", line)
    if pct_match:
        percent = str(max(0, min(100, int(pct_match.group(1)))))

print(stage.replace("\t", " "), current.replace("\t", " "), percent, sep="\t")
PY
    return
  fi

  local stage current
  stage="$(awk '/^## / { value=substr($0, 4) } END { print value }' "${log_path}" 2>/dev/null)"
  current="$(tail -n 20 "${log_path}" | tr '\r' '\n' | awk '/Collecting |Downloading |Using cached |Installing collected packages|Successfully installed/ { value=$0 } END { print value }')"
  [[ -n "${stage}" ]] || stage="준비 중"
  [[ -n "${current}" ]] || current="대기 중"
  printf '%s\t%s\t\n' "${stage}" "${current}"
}

install_progress() {
  local label="$1"
  local log_path="$2"
  shift 2

  if [[ ! -t 1 ]]; then
    "$@"
    return $?
  fi

  local frames=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
  printf '%s' "${HIDE_CURSOR}"
  ( "$@" ) &
  local pid=$!
  local frame=0
  local rendered=0

  while kill -0 "${pid}" 2>/dev/null; do
    local snapshot stage current percent bar pct_label
    snapshot="$(install_progress_snapshot "${log_path}")"
    IFS=$'\t' read -r stage current percent <<< "${snapshot}"
    [[ -n "${stage}" ]] || stage="준비 중"
    [[ -n "${current}" ]] || current="대기 중"
    if [[ "${percent}" =~ ^[0-9]+$ ]]; then
      pct_label="${percent}%"
    else
      pct_label="계산 중"
    fi
    bar="$(progress_bar "${percent}" 28)"

    if (( rendered )); then
      printf '\033[5A'
    fi
    rendered=1

    printf '\033[2K  %s%s%s %s\n' "${ACCENT}" "${frames[frame]}" "${RESET}" "${label}"
    printf '\033[2K  %s단계%s  %s\n' "${MUTED}" "${RESET}" "$(short_text "${stage}" 58)"
    printf '\033[2K  %s현재%s  %s\n' "${MUTED}" "${RESET}" "$(short_text "${current}" 58)"
    printf '\033[2K  %s[%s]%s %s%s%s\n' "${FAINT}" "${bar}" "${RESET}" "${BOLD}${CREAM}" "${pct_label}" "${RESET}"
    printf '\033[2K  %s로그%s  %s\n' "${FAINT}" "${RESET}" "$(short_text "${log_path}" 58)"

    frame=$(( (frame + 1) % ${#frames[@]} ))
    sleep 0.25
  done

  wait "${pid}"
  local rc=$?
  local snapshot stage current percent
  snapshot="$(install_progress_snapshot "${log_path}")"
  IFS=$'\t' read -r stage current percent <<< "${snapshot}"
  if (( rendered )); then
    printf '\033[5A'
  fi
  if (( rc == 0 )); then
    printf '\033[2K  %s✓%s %s\n' "${GREEN}" "${RESET}" "${label}"
    printf '\033[2K  %s단계%s  완료\n' "${MUTED}" "${RESET}"
    printf '\033[2K  %s현재%s  설치 완료\n' "${MUTED}" "${RESET}"
    printf '\033[2K  %s[%s]%s %s100%%%s\n' "${FAINT}" "$(progress_bar 100 28)" "${RESET}" "${BOLD}${CREAM}" "${RESET}"
    printf '\033[2K  %s로그%s  %s\n' "${FAINT}" "${RESET}" "$(short_text "${log_path}" 58)"
  else
    printf '\033[2K  %s✗%s %s\n' "${RED}" "${RESET}" "${label}"
    printf '\033[2K  %s단계%s  %s\n' "${MUTED}" "${RESET}" "$(short_text "${stage:-실패}" 58)"
    printf '\033[2K  %s현재%s  %s\n' "${MUTED}" "${RESET}" "$(short_text "${current:-오류 발생}" 58)"
    printf '\033[2K  %s[%s]%s 실패\n' "${FAINT}" "$(progress_bar "${percent}" 28)" "${RESET}"
    printf '\033[2K  %s로그%s  %s\n' "${FAINT}" "${RESET}" "$(short_text "${log_path}" 58)"
  fi
  printf '%s' "${SHOW_CURSOR}"
  return $rc
}

close_terminal_window() {
  if ! command -v osascript >/dev/null 2>&1; then
    return
  fi
  case "${TERM_PROGRAM:-}" in
    Apple_Terminal)
      (
        sleep 0.3
        osascript -e 'tell application "Terminal" to close front window' >/dev/null 2>&1 \
          || osascript -e 'tell application "System Events" to keystroke "w" using {command down}' >/dev/null 2>&1
      ) &
      ;;
    iTerm.app)
      ( sleep 0.3; osascript -e 'tell application "iTerm" to close current window' >/dev/null 2>&1 ) &
      ;;
  esac
}

show_log_tail() {
  local path="$1"
  if [[ -f "${path}" ]]; then
    echo
    note "마지막 로그:"
    tail -n 8 "${path}" | sed "s/^/    ${FAINT}/; s/$/${RESET}/"
  fi
}

require_file() {
  local path="$1"
  local label="$2"
  if [[ -x "${path}" || -f "${path}" ]]; then
    return 0
  fi

  print_header "오류" "파일 누락" "compact"
  fail_ln "${label}을 찾지 못했습니다."
  note "${path}"
  echo
  body "${MUTED}repo 다운로드/clone이 완전한지 확인한 뒤 다시 실행하세요.${RESET}"
  press_any_key "닫으려면 아무 키나"
  exit 1
}

run_quickstart_check_logged() {
  "${QUICKSTART_SCRIPT}" --check >> "${QUICKSTART_LOG}" 2>&1
}

run_quickstart_install_logged() {
  "${QUICKSTART_SCRIPT}" --accept-license "$@" >> "${QUICKSTART_LOG}" 2>&1
}

run_build_app_logged() {
  "${BUILD_APP_SCRIPT}" >> "${INSTALL_LOG}" 2>&1
}

cleanup_interrupted_install_logged() {
  rm -rf "${VENV_DIR}" \
    "${APP_DIR}/.install_mode" \
    "${APP_DIR}/.python_cmd" \
    "${APP_DIR}/.quickstart_ok" \
    "${INSTALL_INCOMPLETE_FILE}" >> "${QUICKSTART_LOG}" 2>&1
}

mark_install_incomplete() {
  mkdir -p "${APP_DIR}"
  {
    printf 'started_at=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf 'repo=%s\n' "${SCRIPT_DIR}"
  } > "${INSTALL_INCOMPLETE_FILE}"
}

clear_install_incomplete() {
  rm -f "${INSTALL_INCOMPLETE_FILE}"
}

handle_interrupted_install_if_needed() {
  [[ -f "${INSTALL_INCOMPLETE_FILE}" ]] || return 0

  print_header "Step 1 / 5" "중단된 설치 발견" "compact"
  body "$(cat <<EOF
${INK}이전 설치가 완료되기 전에 중단되었습니다.${RESET}
${MUTED}부분 설치된 가상환경은 신뢰하지 않고 다시 만듭니다.${RESET}

${FAINT}사전 데이터(~/Documents/jelly-dict)는 건드리지 않습니다.${RESET}
EOF
)"
  echo
  if ! ask_yes_no "중단된 설치를 정리하고 다시 설치할까요?" "yes"; then
    print_header "취소" "설치 중단" "compact"
    note "정리하지 않았습니다. 다음 실행 때 다시 확인합니다."
    press_any_key "닫으려면 아무 키나"
    exit 1
  fi

  mkdir -p "$(dirname "${QUICKSTART_LOG}")" 2>/dev/null || true
  {
    echo
    echo "## interrupted install cleanup"
    date -u '+%Y-%m-%dT%H:%M:%SZ'
  } >> "${QUICKSTART_LOG}"

  print_header "Step 1 / 5" "설치 정리" "compact"
  body "${INK}부분 설치된 가상환경과 설치 마커를 정리합니다.${RESET}"
  echo
  if spin "중단된 설치 정리 중" cleanup_interrupted_install_logged; then
    success "정리 완료"
    return 0
  fi

  print_header "오류" "정리 실패"
  fail_ln "중단된 설치를 정리하지 못했습니다."
  note "로그: ${QUICKSTART_LOG}"
  show_log_tail "${QUICKSTART_LOG}"
  press_any_key "닫으려면 아무 키나"
  exit 1
}

size_of() {
  local path="$1"
  if [[ -e "${path}" ]]; then
    du -sh "${path}" 2>/dev/null | awk '{print $1}'
  else
    printf '없음'
  fi
}

run_cleanup_flow() {
  local app_dir="${SCRIPT_DIR}/app_files/jelly_dict"
  local cleanup_script="${SCRIPT_DIR}/app_files/scripts/cleanup.sh"
  local venv_dir="${app_dir}/.venv"
  local runtime_dir="${app_dir}/.jelly_dict"
  local user_data_dir="${HOME}/Documents/jelly-dict"
  local playwright_cache="${HOME}/Library/Caches/ms-playwright"
  local cleanup_log="${app_dir}/.jelly_dict/logs/cleanup.log"

  if [[ ! -x "${cleanup_script}" ]]; then
    print_header "환경 정리" "불가" "compact"
    fail_ln "cleanup.sh를 찾지 못했습니다."
    press_any_key "닫으려면 아무 키나"
    return 1
  fi

  print_header "환경 정리" "" "compact"
  body "${MUTED}현재 점유: venv $(size_of "${venv_dir}") · data $(size_of "${runtime_dir}") · playwright $(size_of "${playwright_cache}") · 단어장 $(size_of "${user_data_dir}")${RESET}"
  echo
  ask_vertical_choice "어디까지 정리할까요?" 0 \
    "샌드박스만 (안전 · 권장)::가상환경 + 설치 마커. 재설치로 복구 가능" \
    "런타임 데이터까지::위 + 설정·캐시·로그·OCR/TTS 임시파일" \
    "Playwright 캐시까지::위 + ~/Library/Caches/ms-playwright"
  local rc=$?
  (( rc == 130 )) && return 1

  local -a cleanup_args=()
  local scope=""
  case "${CHOICE_INDEX}" in
    0) cleanup_args=(--sandbox);           scope="가상환경 + 설치 마커" ;;
    1) cleanup_args=(--data);              scope="가상환경 + 런타임 데이터" ;;
    2) cleanup_args=(--data --playwright); scope="가상환경 + 런타임 데이터 + Playwright 캐시" ;;
  esac

  print_header "환경 정리 · 확인" "" "compact"
  body "${INK}선택:${RESET} ${CREAM}${scope}${RESET}"
  echo
  if ! ask_yes_no "정말 진행할까요?" "no"; then
    return 1
  fi

  print_header "환경 정리 · 진행" "" "compact"
  echo
  mkdir -p "$(dirname "${cleanup_log}")" 2>/dev/null || true
  : > "${cleanup_log}" 2>/dev/null || true
  _install_cleanup_logged() {
    "${cleanup_script}" "$@" >> "${cleanup_log}" 2>&1
  }
  if spin "정리 중" _install_cleanup_logged "${cleanup_args[@]}"; then
    print_header "환경 정리 · 완료" "" "compact"
    success "${scope} 를 정리했습니다."
  else
    print_header "환경 정리 · 오류" "" "compact"
    fail_ln "정리 중 오류가 발생했습니다."
    note "로그: ${cleanup_log}"
  fi
  echo
  return 0
}

APP_TO_OPEN="${DIST_APP}"
SKIP_START_PROMPT=0

require_file "${QUICKSTART_SCRIPT}" "setup script"
require_file "${BUILD_APP_SCRIPT}" "App builder"

accept_license_or_exit() {
  print_header "Step 1 / 5" "라이선스 확인"
  body "$(cat <<EOF
${INK}jelly dict는 ${BOLD}MIT License${RESET}${INK}로 제공됩니다.${RESET}
${MUTED}외부 패키지와 선택 TTS 음성은 각자의 라이선스/약관을 따릅니다.${RESET}
${MUTED}설치·실행·생성물 사용 책임은 사용자에게 있습니다.${RESET}

${FAINT}자세한 내용 → app_files/THIRD_PARTY_NOTICES.md${RESET}
EOF
)"
  echo
  if ! ask_yes_no "위 내용을 확인했고 동의합니까?" "no"; then
    print_header "취소" "라이선스 미동의" "compact"
    warn "동의하지 않아 설치를 중단합니다."
    press_any_key "닫으려면 아무 키나"
    exit 1
  fi
}

existing_app_kind() {
  if [[ -d "${USER_APP}" ]]; then
    printf 'user\n'
  elif [[ -d "${DIST_APP}" ]]; then
    printf 'dist\n'
  fi
}

existing_app_path() {
  if [[ -d "${USER_APP}" ]]; then
    printf '%s\n' "${USER_APP}"
  elif [[ -d "${DIST_APP}" ]]; then
    printf '%s\n' "${DIST_APP}"
  fi
}

run_existing_app() {
  local app_path="$1"
  print_header "앱 실행" "" "compact"
  body "$(cat <<EOF
${INK}기존 Jelly Dict.app을 실행합니다.${RESET}
${MUTED}${app_path}${RESET}
EOF
)"
  echo

  mkdir -p "$(dirname "${QUICKSTART_LOG}")" 2>/dev/null || true
  : > "${QUICKSTART_LOG}" 2>/dev/null || true
  if ! spin "실행 전 환경 점검" run_quickstart_check_logged; then
    print_header "Step 2 / 5" "복구 필요"
    body "$(cat <<EOF
${INK}앱 파일은 있지만 실행 환경이 아직 준비되지 않았습니다.${RESET}
${MUTED}${app_path}${RESET}

${FAINT}Jelly Dict.app을 열기 전에 설치/복구를 먼저 진행합니다.${RESET}
${FAINT}로그: ${QUICKSTART_LOG}${RESET}
EOF
)"
    echo
    show_log_tail "${QUICKSTART_LOG}"
    echo
    if ask_yes_no "지금 설치/복구를 진행할까요?" "yes"; then
      return 1
    fi
    print_header "닫기" "" "compact"
    note "앱을 실행하지 않았습니다."
    press_any_key "닫으려면 아무 키나"
    exit 0
  fi

  if command -v open >/dev/null 2>&1; then
    open -n "${app_path}"
    close_terminal_window
    exit 0
  fi
  warn "open 명령을 찾지 못했습니다. Finder에서 앱을 직접 실행하세요."
  press_any_key "닫으려면 아무 키나"
  exit 1
}

copy_dist_app_to_user_apps() {
  print_header "Step 4 / 5" "Applications 복사"
  body "$(cat <<EOF
${INK}생성된 앱을 개인 Applications 폴더에 설치합니다.${RESET}
${MUTED}${USER_APPS_DIR}${RESET}
EOF
)"
  echo

  mkdir -p "${USER_APPS_DIR}"
  rm -rf "${USER_APP}"
  if cp -R "${DIST_APP}" "${USER_APP}"; then
    APP_TO_OPEN="${USER_APP}"
    success "설치 완료: ${USER_APP}"
    return 0
  fi

  print_header "오류" "복사 실패"
  fail_ln "~/Applications에 복사하지 못했습니다."
  note "dist 앱은 그대로 사용할 수 있습니다: ${DIST_APP}"
  press_any_key "닫으려면 아무 키나"
  exit 1
}

finish_with_app() {
  local app_path="$1"
  print_header "Step 5 / 5" "설치 완료"
  body "$(cat <<EOF
${GREEN}Jelly Dict.app 준비가 끝났습니다.${RESET}

${INK}실행 앱:${RESET}
${MUTED}${app_path}${RESET}

${FAINT}repo 위치를 옮기면 이 installer를 다시 실행해야 합니다.${RESET}
EOF
)"
  echo

  if ask_yes_no "지금 Jelly Dict.app을 실행할까요?" "yes"; then
    if command -v open >/dev/null 2>&1; then
      open -n "${app_path}"
      close_terminal_window
      exit 0
    fi
    warn "open 명령을 찾지 못했습니다. Finder에서 앱을 직접 실행하세요."
  fi

  press_any_key "닫으려면 아무 키나"
  exit 0
}

run_dependency_install_flow() {
  print_header "Step 2 / 5" "설치 필요"
  body "$(cat <<EOF
${INK}의존성 설치 또는 복구가 필요합니다.${RESET}
${FAINT}자세한 로그: ${QUICKSTART_LOG}${RESET}
EOF
)"
  echo
  if ! ask_yes_no "의존성을 설치/업데이트할까요?" "yes"; then
    return 1
  fi

  print_header "Step 2 / 5" "설치 위치" "compact"
  if ! ask_install_mode; then
    return 1
  fi
  local install_mode="${INSTALL_MODE_CHOICE}"
  local -a args=(--mode "${install_mode}")

  print_header "Step 2 / 5" "선택 기능 (TTS)" "compact"
  body "$(cat <<EOF
${INK}TTS(음성 합성) 기능도 함께 설치하시겠어요?${RESET}
${MUTED}나중에 다시 실행해도 추가할 수 있습니다.${RESET}
EOF
)"
  echo
  if ask_yes_no "TTS 기능도 설치할까요?" "no"; then
    args=(--mode "${install_mode}" --tts)
  fi

  print_header "Step 2 / 5" "설치 진행" "compact"
  body "$(cat <<EOF
${INK}필요한 패키지를 설치하고 환경을 점검합니다.${RESET}
${FAINT}자세한 로그: ${QUICKSTART_LOG}${RESET}
EOF
)"
  echo
  : > "${QUICKSTART_LOG}" 2>/dev/null || true
  mark_install_incomplete
  if install_progress "패키지 설치 중" "${QUICKSTART_LOG}" run_quickstart_install_logged "${args[@]}"; then
    clear_install_incomplete
    return 0
  fi

  print_header "오류" "설치 실패"
  fail_ln "설치를 완료하지 못했습니다."
  warn "다음 실행 때 부분 설치된 가상환경을 먼저 정리합니다."
  note "로그: ${QUICKSTART_LOG}"
  show_log_tail "${QUICKSTART_LOG}"
  press_any_key "닫으려면 아무 키나"
  exit 1
}

accept_license_or_exit
handle_interrupted_install_if_needed

EXISTING_KIND="$(existing_app_kind)"
EXISTING_APP="$(existing_app_path)"
if [[ "${EXISTING_KIND}" == "user" ]]; then
  print_header "Step 1 / 5" "기존 앱 발견"
  body "$(cat <<EOF
${GREEN}이미 Jelly Dict.app이 있습니다.${RESET}
${MUTED}${EXISTING_APP}${RESET}

${FAINT}repo를 옮겼거나 아이콘/런처를 갱신하려면 재설치하세요.${RESET}
EOF
)"
  echo
  ask_choice "지금 어떻게 할까요?" 0 "재설치" "기존 앱 실행" "닫기"
  rc=$?
  if (( rc == 130 )); then
    print_header "닫기" "" "compact"
    note "취소했습니다."
    press_any_key "닫으려면 아무 키나"
    exit 0
  fi
  case "${CHOICE_INDEX}" in
    1) run_existing_app "${EXISTING_APP}" ;;
    2)
      print_header "닫기" "" "compact"
      note "필요할 때 다시 실행하세요."
      press_any_key "닫으려면 아무 키나"
      exit 0
      ;;
  esac
  SKIP_START_PROMPT=1
elif [[ "${EXISTING_KIND}" == "dist" ]]; then
  print_header "Step 1 / 5" "생성된 앱 발견"
  body "$(cat <<EOF
${GREEN}app_files/dist에 Jelly Dict.app이 있습니다.${RESET}
${MUTED}${DIST_APP}${RESET}

${FAINT}아직 ~/Applications에는 설치되지 않았습니다.${RESET}
EOF
)"
  echo
  ask_choice "지금 어떻게 할까요?" 0 "Applications에 설치" "dist 앱 실행" "재생성" "닫기"
  rc=$?
  if (( rc == 130 )); then
    print_header "닫기" "" "compact"
    note "취소했습니다."
    press_any_key "닫으려면 아무 키나"
    exit 0
  fi
  case "${CHOICE_INDEX}" in
    0)
      copy_dist_app_to_user_apps
      finish_with_app "${APP_TO_OPEN}"
      ;;
    1) run_existing_app "${DIST_APP}" ;;
    3)
      print_header "닫기" "" "compact"
      note "필요할 때 다시 실행하세요."
      press_any_key "닫으려면 아무 키나"
      exit 0
      ;;
  esac
  SKIP_START_PROMPT=1
fi

if (( SKIP_START_PROMPT == 0 )); then
  print_header "Step 1 / 5" "설치 시작"
  body "$(cat <<EOF
${INK}repo 위치를 확인했습니다.${RESET}
${MUTED}${SCRIPT_DIR}${RESET}

${FAINT}환경 점검 후 macOS 앱 번들을 만듭니다.${RESET}
EOF
)"
  echo

  if ! ask_yes_no "Jelly Dict.app 설치를 시작할까요?" "yes"; then
    print_header "취소" "설치 중단" "compact"
    note "설치를 시작하지 않았습니다."
    press_any_key "닫으려면 아무 키나"
    exit 0
  fi
fi

print_header "Step 2 / 5" "환경 점검"
body "$(cat <<EOF
${INK}macOS · Python · 가상환경 · 패키지 상태를 확인합니다.${RESET}
${FAINT}자세한 로그: ${QUICKSTART_LOG}${RESET}
EOF
)"
echo

mkdir -p "$(dirname "${QUICKSTART_LOG}")" 2>/dev/null || true
if spin "환경 점검 중" run_quickstart_check_logged; then
  while true; do
    print_header "Step 2 / 5" "준비 완료"
    body "${GREEN}✓${RESET} ${INK}환경이 정상적으로 보입니다.${RESET}
${MUTED}오류가 나서 재설치하고 싶다면 '환경 정리' 를 선택하세요.${RESET}"
    echo
    ask_choice "지금 어떻게 할까요?" 0 "앱 설치 계속" "환경 정리·재설치" "닫기"
    rc=$?
    if (( rc == 130 )); then
      print_header "닫기" "" "compact"
      note "취소했습니다."
      press_any_key "닫으려면 아무 키나"
      exit 0
    fi
    case "${CHOICE_INDEX}" in
      0) break ;;
      1)
        if run_cleanup_flow; then
          if ! run_dependency_install_flow; then
            print_header "취소" "설치 중단" "compact"
            note "의존성 설치를 건너뛰어 앱 번들을 만들지 않았습니다."
            press_any_key "닫으려면 아무 키나"
            exit 1
          fi
          break
        fi
        ;;
      2)
        print_header "닫기" "" "compact"
        note "필요할 때 다시 실행하세요."
        press_any_key "닫으려면 아무 키나"
        exit 0
        ;;
    esac
  done
else
  warn "설치 또는 복구가 필요합니다."
  echo
  if ! run_dependency_install_flow; then
    print_header "취소" "설치 중단" "compact"
    note "의존성 설치를 건너뛰어 앱 번들을 만들지 않았습니다."
    press_any_key "닫으려면 아무 키나"
    exit 1
  fi
fi

print_header "Step 3 / 5" "앱 번들 생성"
body "$(cat <<EOF
${INK}app_files/dist/${APP_NAME} 번들을 생성합니다.${RESET}
${MUTED}아이콘, repo 경로, 런처, ad-hoc codesign을 적용합니다.${RESET}
${FAINT}자세한 로그: ${INSTALL_LOG}${RESET}
EOF
)"
echo

mkdir -p "$(dirname "${INSTALL_LOG}")" 2>/dev/null || true
: > "${INSTALL_LOG}" 2>/dev/null || true

if ! spin "앱 번들 생성 중" run_build_app_logged; then
  print_header "오류" "앱 번들 실패"
  fail_ln "app_files/dist/${APP_NAME}을 만들지 못했습니다."
  note "로그: ${INSTALL_LOG}"
  show_log_tail "${INSTALL_LOG}"
  press_any_key "닫으려면 아무 키나"
  exit 1
fi

if [[ ! -d "${DIST_APP}" ]]; then
  print_header "오류" "앱 번들 누락"
  fail_ln "생성된 앱을 찾지 못했습니다."
  note "${DIST_APP}"
  press_any_key "닫으려면 아무 키나"
  exit 1
fi

success "생성 완료: ${DIST_APP}"

print_header "Step 4 / 5" "Applications 복사"
body "$(cat <<EOF
${INK}개인 Applications 폴더에 앱을 복사할 수 있습니다.${RESET}
${MUTED}sudo 없이 ${USER_APPS_DIR}에 설치합니다.${RESET}
EOF
)"
echo

if ask_yes_no "Jelly Dict.app을 ~/Applications에 복사할까요?" "yes"; then
  copy_dist_app_to_user_apps
else
  APP_TO_OPEN="${DIST_APP}"
  warn "~/Applications 복사를 건너뛰었습니다."
fi

finish_with_app "${APP_TO_OPEN}"
