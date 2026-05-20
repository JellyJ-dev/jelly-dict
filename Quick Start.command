#!/usr/bin/env bash
set -uo pipefail
# Note: -e intentionally omitted — arithmetic comparisons like ((x < y)) return
# exit code 1 when false, which would otherwise abort the script.

# Re-exec under a newer bash (4+) if available, so we get fractional read
# timeouts for snappy arrow-key handling. macOS ships bash 3.2.
if [[ -z "${JELLY_QS_REEXEC:-}" && "${BASH_VERSINFO[0]:-0}" -lt 4 ]]; then
  for _cand in /opt/homebrew/bin/bash /usr/local/bin/bash /opt/local/bin/bash; do
    if [[ -x "${_cand}" ]]; then
      export JELLY_QS_REEXEC=1
      exec "${_cand}" "$0" "$@"
    fi
  done
fi

# ESC-sequence read timeout — fractional on bash 4+, integer on bash 3.2.
if [[ "${BASH_VERSINFO[0]:-0}" -ge 4 ]]; then
  ESC_READ_TIMEOUT=0.05
else
  ESC_READ_TIMEOUT=1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
JELLY_DICT_VERSION="0.0.4"

# ─────────────────────────────────────────────────────────────────────────────
# Theme
# ─────────────────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  RESET=$'\033[0m'
  BOLD=$'\033[1m'
  DIM=$'\033[2m'
  ITALIC=$'\033[3m'

  # Warm Claude-Code-inspired palette
  ACCENT=$'\033[38;5;209m'      # warm orange
  ACCENT_SOFT=$'\033[38;5;215m' # soft peach
  CREAM=$'\033[38;5;223m'       # cream
  MUTED=$'\033[38;5;245m'       # gentle grey
  FAINT=$'\033[38;5;240m'       # very dim
  GREEN=$'\033[38;5;108m'       # sage
  RED=$'\033[38;5;203m'         # rose
  INK=$'\033[38;5;253m'         # near-white text

  HIDE_CURSOR=$'\033[?25l'
  SHOW_CURSOR=$'\033[?25h'
  ALT_SCREEN_ON=$'\033[?1049h'
  ALT_SCREEN_OFF=$'\033[?1049l'
else
  RESET=""; BOLD=""; DIM=""; ITALIC=""
  ACCENT=""; ACCENT_SOFT=""; CREAM=""; MUTED=""; FAINT=""; GREEN=""; RED=""; INK=""
  HIDE_CURSOR=""; SHOW_CURSOR=""; ALT_SCREEN_ON=""; ALT_SCREEN_OFF=""
fi

# ─────────────────────────────────────────────────────────────────────────────
# Terminal helpers
# ─────────────────────────────────────────────────────────────────────────────
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

# Repeat a single character N times.
repeat_char() {
  local ch="$1" n="$2"
  local out=""
  while ((n-- > 0)); do out+="${ch}"; done
  printf '%s' "${out}"
}

# Strip ANSI escapes for width math.
strip_ansi() {
  printf '%s' "$1" | LC_ALL=C sed $'s/\033\\[[0-9;?]*[A-Za-z]//g'
}

# True display width — handles multi-byte UTF-8 and East Asian Wide (CJK).
# Falls back to character count if Python is unavailable.
if command -v python3 >/dev/null 2>&1; then
  vlen() {
    python3 -c '
import sys, unicodedata
s = sys.argv[1] if len(sys.argv) > 1 else ""
w = 0
for c in s:
    if unicodedata.category(c).startswith("M"):
        continue
    ea = unicodedata.east_asian_width(c)
    w += 2 if ea in ("W", "F") else 1
print(w)
' "$1"
  }
else
  vlen() { printf '%s' "$1" | awk '{print length($0)}'; }
fi

print_centered() {
  local text="$1" cols="${2:-$(term_cols)}"
  local plain pad
  plain="$(strip_ansi "${text}")"
  local w; w="$(vlen "${plain}")"
  pad=$(( (cols - w) / 2 ))
  ((pad < 0)) && pad=0
  printf '%*s%s\n' "${pad}" "" "${text}"
}

cleanup_tty() {
  printf '%s%s' "${SHOW_CURSOR}" "${RESET}"
  stty echo 2>/dev/null || true
  stty icanon 2>/dev/null || true
}
trap cleanup_tty EXIT INT TERM

close_terminal_window() {
  # Best-effort. May silently fail if:
  #   - terminal is not Terminal.app (iTerm2, VS Code, ...)
  #   - macOS Automation permission for Terminal → Terminal is not granted
  #   - the user's Terminal profile is set to "Don't close the window when
  #     the shell exits", in which case the window stays open showing
  #     "[Process completed]" and the user can close it manually.
  if ! command -v osascript >/dev/null 2>&1; then
    return
  fi
  case "${TERM_PROGRAM:-}" in
    Apple_Terminal)
      # Try targeted "close front window" first; if that's blocked, fall back
      # to a Cmd+W keystroke through System Events.
      (
        sleep 0.3
        osascript -e 'tell application "Terminal" to close front window' \
          >/dev/null 2>&1 \
        || osascript -e 'tell application "System Events" to keystroke "w" using {command down}' \
          >/dev/null 2>&1
      ) &
      ;;
    iTerm.app)
      ( sleep 0.3; osascript -e 'tell application "iTerm" to close current window' >/dev/null 2>&1 ) &
      ;;
  esac
}

# ─────────────────────────────────────────────────────────────────────────────
# Brand mark
# ─────────────────────────────────────────────────────────────────────────────
# Wordmark rendered with FIGlet font "ANSI Shadow" — a widely used
# community FIGlet font distributed as part of the standard FIGlet font
# collection. FIGlet font output is conventionally treated as freely
# usable per http://www.jave.de/figlet/figfont.txt.
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

# Decorative "A Z dict" badge.
brand_badge_lines() {
  cat <<'BADGE'
╭───────╮
│  A Z  │
│ dict  │
╰───────╯
BADGE
}

# ─────────────────────────────────────────────────────────────────────────────
# Frame / header
# ─────────────────────────────────────────────────────────────────────────────
INNER_PAD=2

# Draws a top/bottom border with a centered title chip.
draw_border() {
  local pos="$1" title="${2:-}" cols
  cols="$(term_cols)"
  local width=$(( cols - 2 ))
  ((width < 30)) && width=30

  local left right
  case "${pos}" in
    top)    left="╭"; right="╮"; bar="─" ;;
    mid)    left="├"; right="┤"; bar="─" ;;
    bottom) left="╰"; right="╯"; bar="─" ;;
  esac

  if [[ -n "${title}" ]]; then
    local chip=" ${title} "
    local chip_w; chip_w="$(vlen "${chip}")"
    local left_bar=$(( (width - chip_w) / 2 ))
    local right_bar=$(( width - chip_w - left_bar ))
    ((left_bar < 2)) && left_bar=2
    ((right_bar < 2)) && right_bar=2
    printf '%s%s%s%s%s%s%s%s%s\n' \
      "${ACCENT}" "${left}" \
      "$(repeat_char "${bar}" "${left_bar}")" \
      "${RESET}${BOLD}${CREAM}${chip}${RESET}${ACCENT}" \
      "$(repeat_char "${bar}" "${right_bar}")" \
      "${right}" "${RESET}" "" ""
  else
    printf '%s%s%s%s%s\n' \
      "${ACCENT}" "${left}" \
      "$(repeat_char "${bar}" "${width}")" \
      "${right}" "${RESET}"
  fi
}

# Print a content line wrapped inside the frame.
frame_line() {
  local text="${1:-}" cols
  cols="$(term_cols)"
  local width=$(( cols - 2 ))
  ((width < 30)) && width=30
  local plain; plain="$(strip_ansi "${text}")"
  local w; w="$(vlen "${plain}")"
  local pad=$(( width - w ))
  ((pad < 0)) && pad=0
  printf '%s│%s%s%s%s│%s\n' \
    "${ACCENT}" "${RESET}" "${text}" "$(repeat_char ' ' "${pad}")" "${ACCENT}" "${RESET}"
}

frame_blank() { frame_line ""; }

# Print a centered line inside the frame.
frame_centered() {
  local text="$1" cols
  cols="$(term_cols)"
  local width=$(( cols - 2 ))
  ((width < 30)) && width=30
  local plain; plain="$(strip_ansi "${text}")"
  local w; w="$(vlen "${plain}")"
  local pad_left=$(( (width - w) / 2 ))
  local pad_right=$(( width - w - pad_left ))
  ((pad_left < 0)) && pad_left=0
  ((pad_right < 0)) && pad_right=0
  printf '%s│%s%s%s%s%s│%s\n' \
    "${ACCENT}" "$(repeat_char ' ' "${pad_left}")" \
    "${text}" "$(repeat_char ' ' "${pad_right}")" \
    "${ACCENT}" "" "${RESET}"
}

# Hero header: brand mark + tagline. Step chip is rendered separately, outside
# the frame, to keep the box short enough for an 80×24 terminal.
print_header() {
  local step_label="${1:-}"
  local step_caption="${2:-}"
  local force_mode="${3:-}"
  local cols rows
  cols="$(term_cols)"
  rows="$(term_rows)"
  clear_screen

  # Pick a layout based on available rows, unless a caller forces one.
  #   tiny: very small terminal, single-line title only
  #   compact: skip the wordmark, keep a small chip header
  #   normal: full wordmark
  local mode="normal"
  if   (( rows < 16 || cols < 50 )); then mode="tiny"
  elif (( rows < 22 ));               then mode="compact"
  fi
  [[ -n "${force_mode}" ]] && mode="${force_mode}"

  if [[ "${mode}" == "tiny" ]]; then
    printf '%s%s✦ jelly dict%s  %s· Quick Start · v%s%s\n\n' \
      "${BOLD}" "${ACCENT}" "${RESET}" "${MUTED}" "${JELLY_DICT_VERSION}" "${RESET}"
    if [[ -n "${step_label}" ]]; then
      printf '%s●%s %s%s%s   %s%s%s\n\n' \
        "${ACCENT}" "${RESET}" "${BOLD}${INK}" "${step_label}" "${RESET}" \
        "${MUTED}" "${step_caption}" "${RESET}"
    fi
    return
  fi

  if [[ "${mode}" == "compact" ]]; then
    draw_border top "jelly dict  ·  Quick Start  ·  v${JELLY_DICT_VERSION}"
    frame_blank
    draw_border bottom
    if [[ -n "${step_label}" ]]; then
      printf '\n  %s●%s %s%s%s   %s%s%s\n' \
        "${ACCENT}" "${RESET}" "${BOLD}${INK}" "${step_label}" "${RESET}" \
        "${MUTED}" "${step_caption}" "${RESET}"
    fi
    printf '\n'
    return
  fi

  draw_border top "jelly dict  ·  Quick Start  ·  v${JELLY_DICT_VERSION}"
  frame_blank

  # Show tagline only when the terminal has plenty of vertical room.
  local show_tagline=0
  (( rows >= 30 )) && show_tagline=1

  # Render the wordmark as a single block so the italic slant stays intact.
  # Each line keeps its original leading whitespace; we only add a constant
  # left pad to center the WIDEST line within the frame.
  local -a _logo_arr
  local _logo_max=0 _line _w
  while IFS= read -r _line; do
    _logo_arr+=("${_line}")
    _w="$(vlen "${_line}")"
    (( _w > _logo_max )) && _logo_max=$_w
  done < <(brand_logo_lines)
  local _inner=$(( cols - 2 ))
  local _logo_lead=$(( (_inner - _logo_max) / 2 ))
  (( _logo_lead < 0 )) && _logo_lead=0
  local _pad_str; _pad_str="$(repeat_char ' ' "${_logo_lead}")"
  for _line in "${_logo_arr[@]}"; do
    frame_line "${_pad_str}${CREAM}${_line}${RESET}"
  done

  frame_blank
  if (( show_tagline )); then
    frame_centered "${MUTED}local dictionary workspace  ·  Excel · OCR · TTS · Anki${RESET}"
    frame_blank
  fi
  draw_border bottom

  if [[ -n "${step_label}" ]]; then
    if [[ -n "${step_caption}" ]]; then
      printf '\n  %s●%s %s%s%s   %s%s%s\n' \
        "${ACCENT}" "${RESET}" "${BOLD}${INK}" "${step_label}" "${RESET}" \
        "${MUTED}" "${step_caption}" "${RESET}"
    else
      printf '\n  %s●%s %s%s%s\n' \
        "${ACCENT}" "${RESET}" "${BOLD}${INK}" "${step_label}" "${RESET}"
    fi
  fi
  printf '\n'
}

# ─────────────────────────────────────────────────────────────────────────────
# Body printing helpers (between header and prompt)
# ─────────────────────────────────────────────────────────────────────────────
body() {
  local cols; cols="$(term_cols)"
  local pad=2
  while IFS= read -r line; do
    printf '%*s%s\n' "${pad}" "" "${line}"
  done <<<"$1"
}

note()    { printf '  %s%s%s\n' "${MUTED}" "$1" "${RESET}"; }
success() { printf '  %s✓%s %s\n' "${GREEN}" "${RESET}" "$1"; }
warn()    { printf '  %s!%s %s\n' "${ACCENT}" "${RESET}" "$1"; }
fail_ln() { printf '  %s✗%s %s\n' "${RED}" "${RESET}" "$1"; }

# ─────────────────────────────────────────────────────────────────────────────
# Interactive selectors (arrow-key driven, like Claude Code)
# ─────────────────────────────────────────────────────────────────────────────

# Read a single keystroke; return a tag describing the key.
# Tags: up, down, left, right, enter, esc, char:<X>, q, y, n
read_key() {
  local k k2 k3
  IFS= read -rsn1 k || return 1
  if [[ "${k}" == $'\x1b' ]]; then
    # Possibly escape sequence; read 2 more chars with tiny timeout.
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
    "") printf 'enter' ;;
    $'\n'|$'\r') printf 'enter' ;;
    " ") printf 'enter' ;;
    q|Q) printf 'q' ;;
    y|Y) printf 'y' ;;
    n|N) printf 'n' ;;
    *) printf 'char:%s' "${k}" ;;
  esac
}

# ask_choice <prompt> <default-index 0..N-1> <option1> <option2> ...
# Renders interactive horizontal pills. Result is returned via globals so
# callers don't need command substitution (which would hide the TTY).
#   CHOICE_INDEX → 0..N-1
#   CHOICE_TEXT  → selected option string
# Return code: 0 normal, 130 if cancelled (ESC/q).
ask_choice() {
  local prompt="$1" default_idx="$2"; shift 2
  local options=("$@")
  local count=${#options[@]}
  local idx=$default_idx
  CHOICE_INDEX=$idx
  CHOICE_TEXT="${options[$idx]}"

  if [[ ! -t 0 ]]; then
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

    local key; key="$(read_key)"
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
  printf '%s' "${SHOW_CURSOR}"
  printf '\n'
  CHOICE_INDEX=$idx
  CHOICE_TEXT="${options[$idx]}"
  return 0
}

# ask_yes_no <prompt> <default yes|no>
# Returns 0 for yes, 1 for no. Arrow-key driven.
ask_yes_no() {
  local prompt="$1" default="$2"
  local default_idx=1
  [[ "${default}" == "yes" ]] && default_idx=0

  if [[ ! -t 0 || ! -t 1 ]]; then
    [[ "${default}" == "yes" ]]
    return
  fi

  ask_choice "${prompt}" "${default_idx}" "예  Yes" "아니오  No"
  local rc=$?
  (( rc == 130 )) && return 1
  (( CHOICE_INDEX == 0 ))
}

# Vertical selector with per-option hints.
#   $1: prompt, $2: default index
#   remaining args: "label::hint" pairs.
# Sets CHOICE_INDEX. Returns 130 if cancelled.
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

  if [[ ! -t 0 ]]; then return 0; fi

  printf '  %s%s%s\n' "${BOLD}${INK}" "${prompt}" "${RESET}"
  printf '  %s↑/↓ 로 이동, Enter로 선택, q 로 취소%s\n' "${MUTED}" "${RESET}"

  printf '%s' "${HIDE_CURSOR}"
  stty -echo -icanon 2>/dev/null || true

  local rendered=0 i
  while true; do
    if (( rendered )); then
      local up=$(( count * 2 + 1 ))
      printf '\033[%dA' "${up}"
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

    local key; key="$(read_key)"
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
  printf '%s' "${SHOW_CURSOR}"
  printf '\n'
  CHOICE_INDEX=$idx
  return 0
}

# ask_install_mode — sets INSTALL_MODE_CHOICE to "venv" or "local".
ask_install_mode() {
  INSTALL_MODE_CHOICE="venv"
  if [[ ! -t 0 ]]; then
    return 0
  fi

  printf '  %s%s%s\n' "${BOLD}${INK}" "설치 위치를 선택하세요" "${RESET}"
  printf '  %s↑/↓ 로 이동, Enter로 선택%s\n\n' "${MUTED}" "${RESET}"

  local options=("전용 가상환경 (권장)" "현재 로컬 Python")
  local hints=("이 앱 폴더 안 .venv 에만 설치합니다" "현재 사용 중인 Python에 직접 설치합니다")
  local idx=0
  printf '%s' "${HIDE_CURSOR}"
  stty -echo -icanon 2>/dev/null || true

  local rendered=0
  while true; do
    if (( rendered )); then
      # 1 spacer + 2 options × (label + hint) = 5 lines to redraw
      printf '\033[5A'
    fi
    rendered=1

    local i
    printf '\033[2K\n'
    for ((i=0; i<${#options[@]}; i++)); do
      if (( i == idx )); then
        printf '\033[2K  %s❯ %s%s%s\n' "${ACCENT}" "${CREAM}${BOLD}" "${options[i]}" "${RESET}"
        printf '\033[2K      %s%s%s\n' "${MUTED}" "${hints[i]}" "${RESET}"
      else
        printf '\033[2K  %s  %s%s\n' "${FAINT}" "${options[i]}" "${RESET}"
        printf '\033[2K      %s%s%s\n' "${FAINT}" "${hints[i]}" "${RESET}"
      fi
    done

    local key; key="$(read_key)"
    case "${key}" in
      up|left)    (( idx > 0 )) && idx=$(( idx - 1 )) ;;
      down|right) (( idx < ${#options[@]} - 1 )) && idx=$(( idx + 1 )) ;;
      char:1)     idx=0; break ;;
      char:2)     idx=1; break ;;
      enter)      break ;;
      q|esc)      stty echo icanon 2>/dev/null || true
                  printf '%s' "${SHOW_CURSOR}"
                  return 130 ;;
    esac
  done

  stty echo icanon 2>/dev/null || true
  printf '%s' "${SHOW_CURSOR}"
  printf '\n'
  if (( idx == 0 )); then INSTALL_MODE_CHOICE="venv"; else INSTALL_MODE_CHOICE="local"; fi
  return 0
}

# Press-any-key prompt (non-blocking-feeling close).
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

# Spinner that runs while a command executes.
# spin <label> <cmd...>
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

# ─────────────────────────────────────────────────────────────────────────────
# Resolve support files
# ─────────────────────────────────────────────────────────────────────────────
SUPPORT_DIR="${SCRIPT_DIR}"
if [[ ! -x "${SUPPORT_DIR}/scripts/quickstart.sh" && -x "${SCRIPT_DIR}/app_files/scripts/quickstart.sh" ]]; then
  SUPPORT_DIR="${SCRIPT_DIR}/app_files"
fi

if [[ ! -x "${SUPPORT_DIR}/scripts/quickstart.sh" || ! -x "${SUPPORT_DIR}/scripts/run.sh" ]]; then
  print_header "오류" "Setup files not found"
  body "$(printf 'jelly dict 실행 파일을 찾지 못했습니다.\n현재 위치: %s\n\n다운로드한 폴더 구조가 깨졌을 수 있습니다.' "${SCRIPT_DIR}")"
  press_any_key "닫으려면 아무 키나"
  exit 1
fi

LOG_DIR="${SUPPORT_DIR}/jelly_dict/.jelly_dict/logs"
QUICKSTART_LOG="${LOG_DIR}/quickstart.log"
mkdir -p "${LOG_DIR}"

# ─────────────────────────────────────────────────────────────────────────────
# Steps
# ─────────────────────────────────────────────────────────────────────────────
accept_license_or_exit() {
  print_header "Step 1 / 3" "라이선스 확인"
  body "$(cat <<EOF
${INK}jelly dict는 ${BOLD}MIT License${RESET}${INK}로 제공됩니다.${RESET}
${MUTED}외부 패키지와 선택 TTS 음성은 각자의 라이선스/약관을 따릅니다.${RESET}
${MUTED}설치·실행·생성물 사용 책임은 관련 라이선스와 약관에 따라 사용자에게 있습니다.${RESET}

${FAINT}자세한 내용 → app_files/THIRD_PARTY_NOTICES.md${RESET}
EOF
)"
  echo
  if ! ask_yes_no "위 내용을 확인했고 동의합니까?" "no"; then
    # Clear & redraw so the decline message doesn't stack on top of the
    # license body + selector (which already fills 23/24 rows).
    print_header "취소" "라이선스 미동의" "compact"
    warn "동의하지 않아 설치/실행을 중단합니다."
    press_any_key "닫으려면 아무 키나"
    exit 1
  fi
}

run_environment_check() {
  : > "${QUICKSTART_LOG}"
  print_header "Step 2 / 3" "환경 점검"
  body "$(cat <<EOF
${INK}macOS · Python · 가상환경 · 패키지 상태를 확인합니다.${RESET}
${FAINT}자세한 로그: ${QUICKSTART_LOG}${RESET}
EOF
)"
  echo
  spin "환경 점검 중" "${SUPPORT_DIR}/scripts/quickstart.sh" --check >> "${QUICKSTART_LOG}" 2>&1
}

run_app_detached() {
  print_header "Step 3 / 3" "앱 실행"
  body "${INK}jelly dict 를 여는 중입니다.${RESET}
${MUTED}이 창은 자동으로 닫힙니다. 안 닫히면 직접 닫아도 됩니다.${RESET}"
  echo
  "${SUPPORT_DIR}/scripts/run.sh" --detach
  close_terminal_window
  exit 0
}

show_log_tail() {
  local path="$1"
  if [[ -f "${path}" ]]; then
    echo
    note "마지막 로그:"
    tail -n 24 "${path}" | sed "s/^/    ${FAINT}/; s/$/${RESET}/"
  fi
}

# Compact size helper for an existing path (empty string if absent).
size_of() {
  local p="$1"
  if [[ -e "$p" ]]; then
    du -sh "$p" 2>/dev/null | awk '{print $1}'
  else
    printf '없음'
  fi
}

# Interactive cleanup flow. Each stage clears and re-renders to keep the
# screen within 80×24 — no scrolling at any point.
#
# Return codes:
#   0 — cleanup performed (Stage 3 reached)
#   1 — user cancelled at Stage 1 or Stage 2
run_cleanup_flow() {
  local app_dir="${SUPPORT_DIR}/jelly_dict"
  local venv_dir="${app_dir}/.venv"
  local runtime_dir="${app_dir}/.jelly_dict"
  local user_data_dir="${HOME}/Documents/jelly-dict"
  local playwright_cache="${HOME}/Library/Caches/ms-playwright"

  # ── Stage 1: tier selection ─────────────────────────────────────────────
  print_header "환경 정리" "" "compact"
  body "${MUTED}현재 점유: venv $(size_of "${venv_dir}") · data $(size_of "${runtime_dir}") · playwright $(size_of "${playwright_cache}") · 단어장 $(size_of "${user_data_dir}")${RESET}"
  echo
  ask_vertical_choice "어디까지 정리할까요?" 0 \
    "샌드박스만 (안전 · 권장)::가상환경 + 설치 마커. 재설치로 복구 가능" \
    "런타임 데이터까지::위 + 설정·캐시·로그·OCR/TTS 임시파일" \
    "Playwright 캐시까지::위 + ~/Library/Caches/ms-playwright" \
    "전체 (사용자 단어장 포함)::위 + ~/Documents/jelly-dict (주의: 본인 데이터)"
  local rc=$?
  if (( rc == 130 )); then
    return 1
  fi

  local cleanup_args scope
  case "${CHOICE_INDEX}" in
    0) cleanup_args=(--sandbox);             scope="가상환경 + 설치 마커" ;;
    1) cleanup_args=(--data);                scope="가상환경 + 런타임 데이터" ;;
    2) cleanup_args=(--data --playwright);   scope="가상환경 + 런타임 데이터 + Playwright 캐시" ;;
    3) cleanup_args=(--all);                 scope="전체 (사용자 단어장 포함)" ;;
  esac

  # ── Stage 2: confirmation (clear + redraw — no scroll) ─────────────────
  print_header "환경 정리 · 확인" "" "compact"
  body "${INK}선택:${RESET} ${CREAM}${scope}${RESET}"
  if (( CHOICE_INDEX == 3 )); then
    echo
    warn "${BOLD}~/Documents/jelly-dict 안의 vocab.xlsx · Anki 파일이 모두 사라집니다.${RESET}"
    warn "되돌릴 수 없습니다."
  fi
  echo
  if ! ask_yes_no "정말 진행할까요?" "no"; then
    return 1
  fi

  # ── Stage 3: execute + result (clear + redraw) ─────────────────────────
  print_header "환경 정리 · 진행" "" "compact"
  echo
  local cleanup_log="${SUPPORT_DIR}/jelly_dict/.jelly_dict/logs/cleanup.log"
  mkdir -p "$(dirname "${cleanup_log}")" 2>/dev/null || true
  : > "${cleanup_log}" 2>/dev/null || true
  # Wrap the cleanup invocation so its stdout/stderr can be redirected to a
  # log without also hiding the spinner animation that spin() prints.
  _qs_cleanup_invoke() {
    "${SUPPORT_DIR}/scripts/cleanup.sh" "$@" >> "${cleanup_log}" 2>&1
  }
  local exec_rc=0
  spin "정리 중" _qs_cleanup_invoke "${cleanup_args[@]}" || exec_rc=$?

  print_header "환경 정리 · 완료" "" "compact"
  if (( exec_rc == 0 )); then
    success "${scope} 를 정리했습니다."
  else
    fail_ln "정리 중 오류 발생 (rc=${exec_rc})"
    note "로그: ${cleanup_log}"
  fi
  echo
  body "${MUTED}남은 점유: venv $(size_of "${venv_dir}") · data $(size_of "${runtime_dir}") · playwright $(size_of "${playwright_cache}") · 단어장 $(size_of "${user_data_dir}")${RESET}"
  echo
  return 0
}

# ─────────────────────────────────────────────────────────────────────────────
# Flow
# ─────────────────────────────────────────────────────────────────────────────
accept_license_or_exit

if run_environment_check; then
  while true; do
    print_header "Step 2 / 3" "준비 완료"
    body "${GREEN}✓${RESET} ${INK}환경이 정상적으로 보입니다.${RESET}
${MUTED}오류가 나서 재설치하고 싶다면 '환경 정리' 를 선택하세요.${RESET}"
    echo

    ask_choice "지금 어떻게 할까요?" 0 \
      "바로 실행" "환경 정리·재설치" "닫기"
    rc=$?
    if (( rc == 130 )); then
      print_header "닫기" "" "compact"
      note "취소했습니다."
      press_any_key "닫으려면 아무 키나"
      exit 0
    fi

    case "${CHOICE_INDEX}" in
      0) run_app_detached ;;
      1)
        if run_cleanup_flow; then
          # Cleanup performed — offer immediate reinstall.
          echo
          if ask_yes_no "지금 다시 설치할까요?" "yes"; then
            break    # fall through to install flow below
          else
            print_header "닫기" "" "compact"
            note "다음에 Quick Start.command 를 다시 실행하면 설치를 진행할 수 있습니다."
            press_any_key "닫으려면 아무 키나"
            exit 0
          fi
        fi
        # Cancelled → loop back to the env-OK 3-way menu.
        ;;
      2)
        print_header "닫기" "" "compact"
        note "필요할 때 다시 실행하세요."
        press_any_key "닫으려면 아무 키나"
        exit 0
        ;;
    esac
  done
fi

print_header "Step 2 / 3" "설치 필요"
body "${INK}설치 또는 업데이트가 필요합니다.${RESET}
${FAINT}자세한 진단 로그: ${QUICKSTART_LOG}${RESET}"
echo

if ask_yes_no "의존성을 설치/업데이트할까요?" "yes"; then
  # Each subsequent prompt redraws with a compact header so screens never
  # stack on top of each other (80×24 has no room for the full wordmark
  # plus a body plus a multi-line vertical selector).
  print_header "Step 2 / 3" "설치 위치" "compact"
  ask_install_mode
  install_mode="${INSTALL_MODE_CHOICE}"
  args=(--mode "${install_mode}" --run)

  print_header "Step 2 / 3" "선택 기능 (TTS)" "compact"
  body "${INK}TTS(음성 합성) 기능도 함께 설치하시겠어요?${RESET}
${MUTED}나중에 다시 실행해도 추가할 수 있습니다.${RESET}"
  echo
  if ask_yes_no "TTS 기능도 설치할까요?" "no"; then
    args=(--mode "${install_mode}" --tts --run)

    if ! command -v ffmpeg >/dev/null 2>&1; then
      if command -v brew >/dev/null 2>&1; then
        print_header "Step 2 / 3" "ffmpeg" "compact"
        body "${INK}TTS mp3 처리를 위해 ffmpeg 가 필요합니다.${RESET}"
        echo
        if ask_yes_no "Homebrew 로 ffmpeg 를 설치할까요?" "yes"; then
          print_header "Step 2 / 3" "ffmpeg 설치" "compact"
          echo
          spin "ffmpeg 설치" brew install ffmpeg || warn "ffmpeg 설치 실패 — 나중에 수동으로 설치해 주세요"
        fi
      else
        print_header "Step 2 / 3" "ffmpeg 경고" "compact"
        warn "Homebrew 가 없어 ffmpeg 는 자동 설치하지 못했습니다."
        note "TTS 를 쓸 거면 나중에 ffmpeg 를 따로 설치하세요."
        echo
        press_any_key "계속하려면 아무 키나"
      fi
    fi
  fi

  print_header "Step 3 / 3" "설치 진행" "compact"
  body "${INK}필요한 패키지를 설치하고 앱을 준비합니다.${RESET}
${MUTED}시간이 조금 걸릴 수 있습니다.${RESET}
${FAINT}자세한 로그: ${QUICKSTART_LOG}${RESET}"
  echo
  if spin "패키지 설치 중" "${SUPPORT_DIR}/scripts/quickstart.sh" --accept-license --detach "${args[@]}"; then
    print_header "Step 3 / 3" "준비 완료"
    body "${GREEN}✓${RESET} ${INK}jelly dict 를 여는 중입니다.${RESET}
${MUTED}이 창은 자동으로 닫힙니다. 안 닫히면 직접 닫아도 됩니다.${RESET}"
    close_terminal_window
    exit 0
  fi

  print_header "오류" "설치 실패"
  body "${RED}✗${RESET} ${INK}설치를 완료하지 못했습니다.${RESET}
${MUTED}로그 파일: ${QUICKSTART_LOG}${RESET}"
  show_log_tail "${QUICKSTART_LOG}"
  press_any_key "닫으려면 아무 키나"
  exit 1
else
  run_app_detached
fi

press_any_key "닫으려면 아무 키나"
