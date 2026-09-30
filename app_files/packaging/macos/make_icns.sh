#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd -P)"
ASSETS_DIR="${REPO_ROOT}/app_files/assets"
SOURCE_PNG="${ASSETS_DIR}/app-icon-1024.png"
ICONSET_DIR="${ASSETS_DIR}/app-icon.iconset"
OUTPUT_ICNS="${ASSETS_DIR}/app-icon.icns"

if [[ ! -f "${SOURCE_PNG}" ]]; then
  echo "Icon PNG not found: ${SOURCE_PNG}" >&2
  exit 1
fi

if ! command -v sips >/dev/null 2>&1; then
  echo "sips is required to resize PNG icon files on macOS." >&2
  exit 1
fi

if ! command -v iconutil >/dev/null 2>&1; then
  echo "iconutil is required to create .icns files on macOS." >&2
  exit 1
fi

rm -rf "${ICONSET_DIR}"
mkdir -p "${ICONSET_DIR}"

make_icon() {
  local size="$1"
  local scale="$2"
  local pixels=$((size * scale))
  local suffix=""

  if [[ "${scale}" -eq 2 ]]; then
    suffix="@2x"
  fi

  sips -z "${pixels}" "${pixels}" "${SOURCE_PNG}" \
    --out "${ICONSET_DIR}/icon_${size}x${size}${suffix}.png" >/dev/null
}

make_icon 16 1
make_icon 16 2
make_icon 32 1
make_icon 32 2
make_icon 128 1
make_icon 128 2
make_icon 256 1
make_icon 256 2
make_icon 512 1
make_icon 512 2

if ! iconutil -c icns "${ICONSET_DIR}" -o "${OUTPUT_ICNS}"; then
  echo "iconutil rejected the iconset; writing .icns directly from PNG chunks." >&2
  python3 - "${ICONSET_DIR}" "${OUTPUT_ICNS}" <<'PY'
import struct
import sys
from pathlib import Path

iconset = Path(sys.argv[1])
output = Path(sys.argv[2])
entries = [
    ("icp4", "icon_16x16.png"),
    ("icp5", "icon_32x32.png"),
    ("icp6", "icon_32x32@2x.png"),
    ("ic07", "icon_128x128.png"),
    ("ic08", "icon_256x256.png"),
    ("ic09", "icon_512x512.png"),
    ("ic10", "icon_512x512@2x.png"),
]

chunks = []
for chunk_type, filename in entries:
    data = (iconset / filename).read_bytes()
    chunks.append(chunk_type.encode("ascii") + struct.pack(">I", len(data) + 8) + data)

payload = b"".join(chunks)
output.write_bytes(b"icns" + struct.pack(">I", len(payload) + 8) + payload)
PY
fi
rm -rf "${ICONSET_DIR}"

echo "Created ${OUTPUT_ICNS}"
