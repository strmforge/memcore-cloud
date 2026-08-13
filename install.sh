#!/usr/bin/env bash
# Time Library one-command installer for macOS, Linux, and WSL.
set -euo pipefail

REPO="${TIME_LIBRARY_REPO:-${MEMCORE_REPO:-strmforge/time-library}}"
VERSION="${TIME_LIBRARY_VERSION:-${MEMCORE_VERSION:-${VERSION:-2026.8.13}}}"
RELEASE_TAG="${TIME_LIBRARY_RELEASE_TAG:-${MEMCORE_RELEASE_TAG:-v${VERSION}}}"
ARCHIVE_URL="${TIME_LIBRARY_ARCHIVE_URL:-${MEMCORE_ARCHIVE_URL:-https://github.com/${REPO}/releases/download/${RELEASE_TAG}/time-library-${VERSION}.zip}}"
ARCHIVE_SHA256_URL="${TIME_LIBRARY_ARCHIVE_SHA256_URL:-${MEMCORE_ARCHIVE_SHA256_URL:-${ARCHIVE_URL}.sha256}}"
ARCHIVE_SHA256="${TIME_LIBRARY_ARCHIVE_SHA256:-${MEMCORE_ARCHIVE_SHA256:-}}"
SKIP_CHECKSUM="${TIME_LIBRARY_SKIP_CHECKSUM:-${MEMCORE_SKIP_CHECKSUM:-0}}"

info() { printf '[time-library] %s\n' "$*"; }
die() { printf '[time-library] %s\n' "$*" >&2; exit 1; }

run_from_tree() {
  local root="$1"
  shift

  case "$(uname -s)" in
    Darwin)
      [[ -f "${root}/tools/macos_full_install.sh" ]] || return 1
      exec bash "${root}/tools/macos_full_install.sh" "$@"
      ;;
    Linux)
      [[ -f "${root}/tools/linux_full_install.sh" ]] || return 1
      exec bash "${root}/tools/linux_full_install.sh" "$@"
      ;;
    *)
      die "Unsupported OS: $(uname -s)"
      ;;
  esac
}

download() {
  local url="$1"
  local out="$2"

  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$out"
  elif command -v python3 >/dev/null 2>&1; then
    python3 - "$url" "$out" <<'PY'
import sys
from urllib.request import urlopen

with urlopen(sys.argv[1], timeout=60) as response:
    data = response.read()
with open(sys.argv[2], "wb") as fh:
    fh.write(data)
PY
  else
    die "curl or python3 is required"
  fi
}

sha256_file() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print tolower($1)}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print tolower($1)}'
  elif command -v python3 >/dev/null 2>&1; then
    python3 - "$path" <<'PY'
import hashlib
import sys

h = hashlib.sha256()
with open(sys.argv[1], "rb") as fh:
    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
  else
    die "sha256sum, shasum, or python3 is required for checksum verification"
  fi
}

normalize_sha256() {
  printf '%s' "$1" | tr -d '\r' | awk '{print tolower($1); exit}'
}

verify_archive_checksum() {
  local zip_path="$1"
  local expected="$ARCHIVE_SHA256"
  local checksum_path="${zip_path}.sha256"
  local actual

  case "$(printf '%s' "$SKIP_CHECKSUM" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes)
      info "Skipping archive checksum verification because TIME_LIBRARY_SKIP_CHECKSUM=${SKIP_CHECKSUM}"
      return 0
      ;;
  esac

  if [[ -z "$expected" ]]; then
    info "Downloading archive checksum..."
    download "$ARCHIVE_SHA256_URL" "$checksum_path"
    expected="$(cat "$checksum_path")"
  fi
  expected="$(normalize_sha256 "$expected")"
  if [[ ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
    die "Invalid SHA256 checksum value"
  fi

  actual="$(sha256_file "$zip_path")"
  if [[ "$actual" != "$expected" ]]; then
    die "Archive checksum mismatch: expected ${expected}, got ${actual}"
  fi
  info "Archive checksum verified."
}

extract_zip() {
  local zip_path="$1"
  local out_dir="$2"

  if command -v unzip >/dev/null 2>&1; then
    unzip -qo "$zip_path" -d "$out_dir"
  elif command -v python3 >/dev/null 2>&1; then
    python3 -m zipfile -e "$zip_path" "$out_dir"
  else
    die "unzip or python3 is required"
  fi
}

script_path="${BASH_SOURCE[0]:-$0}"
if [[ -f "$script_path" ]]; then
  script_dir="$(cd "$(dirname "$script_path")" && pwd)"
  run_from_tree "$script_dir" "$@" || true
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

zip_path="${tmp_dir}/time-library-${VERSION}.zip"
extract_dir="${tmp_dir}/extracted"

info "Downloading Time Library ${VERSION} from ${ARCHIVE_URL}..."
download "$ARCHIVE_URL" "$zip_path"
verify_archive_checksum "$zip_path"
extract_zip "$zip_path" "$extract_dir"

inner="$(find "$extract_dir" -mindepth 1 -maxdepth 1 -type d | head -1)"
[[ -n "$inner" ]] || die "Downloaded archive is empty"

run_from_tree "$inner" "$@" || die "Installer files were not found"
