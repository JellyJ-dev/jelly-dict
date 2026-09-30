#!/usr/bin/env bash

# Installer/update orchestration. The entrypoint owns paths, visual tokens, and
# command role; this module owns state transitions and side effects.

# One stage table drives the labels used by both install and update flows.
# Update intentionally shares step 4 for bundle creation and Applications copy
# to preserve the existing terminal contract.
FLOW_STAGE_TABLE=$'install|start|1\ninstall|environment|2\ninstall|bundle|3\ninstall|copy|4\ninstall|finish|5\nupdate|start|1\nupdate|source|2\nupdate|environment|3\nupdate|bundle|4\nupdate|copy|4\nupdate|finish|5'

flow_stage_number() {
  local requested_state="$1"
  local role state number
  while IFS='|' read -r role state number; do
    if [[ "${role}" == "${COMMAND_ROLE}" && "${state}" == "${requested_state}" ]]; then
      printf '%s' "${number}"
      return 0
    fi
  done <<< "${FLOW_STAGE_TABLE}"
  return 1
}

flow_step_label() {
  printf 'Step %s / 5' "$(flow_stage_number "$1")"
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

run_with_timeout() {
  local timeout_seconds="$1"
  shift
  if [[ ! "${timeout_seconds}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'Invalid timeout: %s\n' "${timeout_seconds}" >&2
    return 2
  fi

  local restore_monitor=0
  if [[ "$-" != *m* ]]; then
    set -m
    restore_monitor=1
  fi
  "$@" &
  local pid=$!
  if (( restore_monitor )); then
    set +m
  fi
  local elapsed_tenths=0
  while kill -0 "${pid}" 2>/dev/null; do
    if (( elapsed_tenths >= timeout_seconds * 10 )); then
      kill -TERM -- "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
      local attempt
      for attempt in 1 2 3 4 5 6 7 8 9 10; do
        kill -0 "${pid}" 2>/dev/null || break
        sleep 0.1
      done
      if kill -0 "${pid}" 2>/dev/null; then
        kill -KILL -- "-${pid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
      fi
      wait "${pid}" 2>/dev/null || true
      printf 'Command timed out after %ss: %s\n' "${timeout_seconds}" "$1" >&2
      return 124
    fi
    sleep 0.1
    elapsed_tenths=$(( elapsed_tenths + 1 ))
  done
  wait "${pid}"
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
  run_with_timeout "${QUICKSTART_CHECK_TIMEOUT_SECONDS}" "${QUICKSTART_SCRIPT}" --check >> "${QUICKSTART_LOG}" 2>&1
}

run_quickstart_install_logged() {
  run_with_timeout "${QUICKSTART_INSTALL_TIMEOUT_SECONDS}" "${QUICKSTART_SCRIPT}" --accept-license "$@" >> "${QUICKSTART_LOG}" 2>&1
}

run_build_app_logged() {
  run_with_timeout "${APP_BUILD_TIMEOUT_SECONDS}" "${BUILD_APP_SCRIPT}" >> "${INSTALL_LOG}" 2>&1
}

run_build_app_update_logged() {
  run_with_timeout "${APP_BUILD_TIMEOUT_SECONDS}" "${BUILD_APP_SCRIPT}" >> "${UPDATE_LOG}" 2>&1
}

run_git_pull_logged() {
  {
    echo
    echo "## source update"
    date -u '+%Y-%m-%dT%H:%M:%SZ'
    printf '$ git -C %q pull --ff-only\n' "${SCRIPT_DIR}"
    run_with_timeout "${GIT_PULL_TIMEOUT_SECONDS}" git -C "${SCRIPT_DIR}" pull --ff-only
  } >> "${UPDATE_LOG}" 2>&1
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

  print_header "$(flow_step_label start)" "중단된 설치 발견" "compact"
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

  print_header "$(flow_step_label start)" "설치 정리" "compact"
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

accept_license_or_exit() {
  local notice
  if [[ -f "${LICENSE_NOTICE_FILE}" ]]; then
    notice="$(cat "${LICENSE_NOTICE_FILE}")"
  else
    notice="jelly dict는 MIT License 조건으로 제공됩니다.
외부 패키지와 선택 TTS 음성은 각각의 라이선스/약관을 따릅니다.
이 앱의 설치, 실행, 생성물 사용으로 발생하는 책임은 관련 라이선스와 약관에 따라 사용자에게 있습니다.

자세한 내용은 app_files/THIRD_PARTY_NOTICES.md를 확인하세요."
  fi

  print_header "$(flow_step_label start)" "라이선스 확인"
  body "$(cat <<EOF
${INK}${notice}${RESET}
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
    print_header "$(flow_step_label environment)" "복구 필요"
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
  print_header "$(flow_step_label copy)" "Applications 복사"
  body "$(cat <<EOF
${INK}생성된 앱을 개인 Applications 폴더에 ${COMMAND_NOUN}합니다.${RESET}
${MUTED}${USER_APPS_DIR}${RESET}
EOF
)"
  echo

  mkdir -p "${USER_APPS_DIR}"
  rm -rf "${USER_APP}"
  if cp -R "${DIST_APP}" "${USER_APP}"; then
    APP_TO_OPEN="${USER_APP}"
    success "${COMMAND_DONE_LABEL}: ${USER_APP}"
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
  print_header "$(flow_step_label finish)" "${COMMAND_DONE_LABEL}"
  body "$(cat <<EOF
${GREEN}Jelly Dict.app 준비가 끝났습니다.${RESET}

${INK}실행 앱:${RESET}
${MUTED}${app_path}${RESET}

${FAINT}repo 위치를 옮기면 이 ${COMMAND_LABEL}를 다시 실행해야 합니다.${RESET}
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
  print_header "$(flow_step_label environment)" "설치 필요"
  body "$(cat <<EOF
${INK}의존성 설치 또는 복구가 필요합니다.${RESET}
${FAINT}자세한 로그: ${QUICKSTART_LOG}${RESET}
EOF
)"
  echo
  if ! ask_yes_no "의존성을 설치/업데이트할까요?" "yes"; then
    return 1
  fi

  print_header "$(flow_step_label environment)" "설치 위치" "compact"
  if ! ask_install_mode; then
    return 1
  fi
  local install_mode="${INSTALL_MODE_CHOICE}"
  local -a args=(--mode "${install_mode}")

  print_header "$(flow_step_label environment)" "선택 기능 (TTS)" "compact"
  body "$(cat <<EOF
${INK}TTS(음성 합성) 기능도 함께 설치하시겠어요?${RESET}
${MUTED}나중에 다시 실행해도 추가할 수 있습니다.${RESET}
EOF
)"
  echo
  if ask_yes_no "TTS 기능도 설치할까요?" "no"; then
    args=(--mode "${install_mode}" --tts)
  fi

  print_header "$(flow_step_label environment)" "설치 진행" "compact"
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

repo_is_git_worktree() {
  command -v git >/dev/null 2>&1 || return 1
  git -C "${SCRIPT_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1
}

repo_has_local_changes() {
  [[ -n "$(git -C "${SCRIPT_DIR}" status --porcelain 2>/dev/null)" ]]
}

repo_status_preview() {
  git -C "${SCRIPT_DIR}" status --short 2>/dev/null | head -n 10
}

saved_update_install_mode() {
  local mode=""
  if [[ -f "${APP_DIR}/.install_mode" ]]; then
    mode="$(tr -d '[:space:]' < "${APP_DIR}/.install_mode" 2>/dev/null || true)"
  fi
  if [[ "${mode}" != "venv" && "${mode}" != "local" ]]; then
    mode="venv"
  fi
  printf '%s\n' "${mode}"
}

run_bundle_build_stage() {
  local build_log build_runner bundle_verb
  if [[ "${COMMAND_ROLE}" == "update" ]]; then
    build_log="${UPDATE_LOG}"
    build_runner="run_build_app_update_logged"
    bundle_verb="다시 생성"
  else
    build_log="${INSTALL_LOG}"
    build_runner="run_build_app_logged"
    bundle_verb="생성"
  fi

  print_header "$(flow_step_label bundle)" "앱 번들 생성"
  body "$(cat <<EOF
${INK}app_files/dist/${APP_NAME} 번들을 ${bundle_verb}합니다.${RESET}
${MUTED}아이콘, repo 경로, 런처, ad-hoc codesign을 적용합니다.${RESET}
${FAINT}자세한 로그: ${build_log}${RESET}
EOF
)"
  echo

  mkdir -p "$(dirname "${build_log}")" 2>/dev/null || true
  if [[ "${COMMAND_ROLE}" == "install" ]]; then
    : > "${build_log}" 2>/dev/null || true
  fi

  if ! spin "앱 번들 생성 중" "${build_runner}"; then
    print_header "오류" "앱 번들 실패"
    fail_ln "app_files/dist/${APP_NAME}을 만들지 못했습니다."
    note "로그: ${build_log}"
    show_log_tail "${build_log}"
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
}

offer_application_copy_stage() {
  if [[ "${COMMAND_ROLE}" == "update" && -d "${USER_APP}" ]]; then
    copy_dist_app_to_user_apps
    return
  fi

  print_header "$(flow_step_label copy)" "Applications 복사"
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
}

run_delivery_flow() {
  run_bundle_build_stage
  offer_application_copy_stage
  finish_with_app "${APP_TO_OPEN}"
}

run_update_flow() {
  require_file "${QUICKSTART_SCRIPT}" "setup script"
  require_file "${BUILD_APP_SCRIPT}" "App builder"

  print_header "$(flow_step_label start)" "업데이트 시작"
  body "$(cat <<EOF
${INK}Jelly Dict.app을 최신 코드와 런타임 상태로 갱신합니다.${RESET}
${MUTED}${SCRIPT_DIR}${RESET}

${FAINT}git 배포본이면 원격 변경을 가져온 뒤 환경과 앱 번들을 다시 만듭니다.${RESET}
EOF
)"
  echo

  if ! ask_yes_no "Jelly Dict.app 업데이트를 시작할까요?" "yes"; then
    print_header "취소" "업데이트 중단" "compact"
    note "업데이트를 시작하지 않았습니다."
    press_any_key "닫으려면 아무 키나"
    exit 0
  fi

  mkdir -p "$(dirname "${UPDATE_LOG}")" 2>/dev/null || true
  : > "${UPDATE_LOG}" 2>/dev/null || true

  if repo_is_git_worktree; then
    if repo_has_local_changes; then
      local status_preview
      status_preview="$(repo_status_preview)"
      print_header "오류" "로컬 변경 있음"
      fail_ln "로컬 변경이 있어 자동 업데이트를 중단합니다."
      body "$(cat <<EOF
${MUTED}업데이트가 사용자 변경을 덮지 않도록 여기서 멈춥니다.${RESET}

${FAINT}${status_preview}${RESET}
EOF
)"
      press_any_key "닫으려면 아무 키나"
      exit 1
    fi

    print_header "$(flow_step_label source)" "소스 업데이트"
    body "$(cat <<EOF
${INK}git pull --ff-only로 최신 소스를 가져옵니다.${RESET}
${FAINT}자세한 로그: ${UPDATE_LOG}${RESET}
EOF
)"
    echo
    if ! spin "최신 소스 확인 중" run_git_pull_logged; then
      print_header "오류" "소스 업데이트 실패"
      fail_ln "원격 소스를 가져오지 못했습니다."
      note "로그: ${UPDATE_LOG}"
      show_log_tail "${UPDATE_LOG}"
      press_any_key "닫으려면 아무 키나"
      exit 1
    fi
    success "소스 업데이트 완료"
  else
    print_header "$(flow_step_label source)" "소스 확인"
    body "$(cat <<EOF
${INK}이 폴더는 git 작업 폴더가 아닙니다.${RESET}
${MUTED}원격 소스 pull은 건너뛰고 현재 파일로 앱을 다시 만듭니다.${RESET}
EOF
)"
    echo
    if ! ask_yes_no "로컬 앱 재빌드를 계속할까요?" "yes"; then
      print_header "취소" "업데이트 중단" "compact"
      note "로컬 재빌드를 시작하지 않았습니다."
      press_any_key "닫으려면 아무 키나"
      exit 0
    fi
  fi

  local install_mode
  install_mode="$(saved_update_install_mode)"

  print_header "$(flow_step_label environment)" "환경 업데이트"
  body "$(cat <<EOF
${INK}Python 패키지와 Playwright WebKit 상태를 갱신합니다.${RESET}
${MUTED}설치 방식: ${install_mode}${RESET}
${FAINT}자세한 로그: ${QUICKSTART_LOG}${RESET}
EOF
)"
  echo

  mkdir -p "$(dirname "${QUICKSTART_LOG}")" 2>/dev/null || true
  : > "${QUICKSTART_LOG}" 2>/dev/null || true
  if ! install_progress "패키지 업데이트 중" "${QUICKSTART_LOG}" run_quickstart_install_logged --mode "${install_mode}"; then
    print_header "오류" "환경 업데이트 실패"
    fail_ln "의존성 업데이트를 완료하지 못했습니다."
    note "로그: ${QUICKSTART_LOG}"
    show_log_tail "${QUICKSTART_LOG}"
    press_any_key "닫으려면 아무 키나"
    exit 1
  fi

  run_delivery_flow
}


jelly_run_installer() {
  require_file "${QUICKSTART_SCRIPT}" "setup script"
  require_file "${BUILD_APP_SCRIPT}" "App builder"

if [[ "${COMMAND_ROLE}" == "update" ]]; then
  run_update_flow
fi

accept_license_or_exit
handle_interrupted_install_if_needed

EXISTING_KIND="$(existing_app_kind)"
EXISTING_APP="$(existing_app_path)"
if [[ "${EXISTING_KIND}" == "user" ]]; then
  print_header "$(flow_step_label start)" "기존 앱 발견"
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
  print_header "$(flow_step_label start)" "생성된 앱 발견"
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
  print_header "$(flow_step_label start)" "설치 시작"
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

print_header "$(flow_step_label environment)" "환경 점검"
body "$(cat <<EOF
${INK}macOS · Python · 가상환경 · 패키지 상태를 확인합니다.${RESET}
${FAINT}자세한 로그: ${QUICKSTART_LOG}${RESET}
EOF
)"
echo

mkdir -p "$(dirname "${QUICKSTART_LOG}")" 2>/dev/null || true
if spin "환경 점검 중" run_quickstart_check_logged; then
  while true; do
    print_header "$(flow_step_label environment)" "준비 완료"
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

run_delivery_flow
}
