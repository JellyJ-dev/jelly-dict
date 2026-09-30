#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
export JELLY_DICT_COMMAND_ROLE=update
exec "${SCRIPT_DIR}/Install jelly dict.command" "$@"
