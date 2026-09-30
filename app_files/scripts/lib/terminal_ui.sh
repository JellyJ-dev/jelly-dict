#!/usr/bin/env bash

# Terminal-only presentation primitives shared by the installer and updater.
# The caller owns all wording, colors, command labels, and orchestration state.

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
    printf '%s%s✦ jelly dict%s  %s· %s · v%s%s\n\n' \
      "${BOLD}" "${ACCENT}" "${RESET}" "${MUTED}" "${COMMAND_LABEL}" "${JELLY_DICT_VERSION}" "${RESET}"
    [[ -n "${step_label}" ]] && printf '%s●%s %s%s%s   %s%s%s\n\n' \
      "${ACCENT}" "${RESET}" "${BOLD}${INK}" "${step_label}" "${RESET}" "${MUTED}" "${step_caption}" "${RESET}"
    return
  fi

  draw_border top "jelly dict  ·  ${COMMAND_LABEL}  ·  v${JELLY_DICT_VERSION}"
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

horizontal_choice_line() {
  local idx="$1"
  shift
  local options=("$@")
  local count=${#options[@]}
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

    horizontal_choice_line "${idx}" "${options[@]}"

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
