#!/usr/bin/env bash
# Linux/WSL user-level full installer for Time Library.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LEGACY_INSTALL_ROOT="${HOME}/.local/share/memcore-cloud"
DEFAULT_INSTALL_ROOT="${HOME}/.local/share/time-library"
INSTALL_ROOT="${INSTALL_ROOT:-${DEFAULT_INSTALL_ROOT}}"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
LOG_DIR="${HOME}/.local/state/time-library/logs"
OPENCLAW_CONFIG="${OPENCLAW_CONFIG:-${HOME}/.openclaw/openclaw.json}"
HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
REINSTALL=0
RESET_INSTALL=0
PRESERVE_DATA=1
SKIP_OPENCLAW=0
SKIP_HERMES=0
SKIP_CODEX=0
SKIP_CLAUDE_DESKTOP=0
SKIP_START=0
RUN_SMOKE=1
RUNTIME_PYTHON=""
CODEX_SKILL_STATUS="pending"
CODEX_MCP_STATUS="pending"
CODEX_MCP_GUARD_STATUS="pending"
CLAUDE_CODE_MCP_STATUS="pending"
CLAUDE_CODE_HOOK_STATUS="pending"
CLAUDE_DESKTOP_STATUS="pending"
DIALOG_ENTRY_HOST="${DIALOG_ENTRY_HOST:-127.0.0.1}"
DIALOG_ENTRY_ENDPOINT_URL="${DIALOG_ENTRY_ENDPOINT_URL:-}"
DIALOG_ENTRY_TOKEN="${DIALOG_ENTRY_TOKEN:-}"
FRONT_DOOR_PORT="${FRONT_DOOR_PORT:-9850}"
INTERNAL_P3_PORT="${INTERNAL_P3_PORT:-19300}"
INTERNAL_P4_PORT="${INTERNAL_P4_PORT:-19400}"
INTERNAL_P6_PORT="${INTERNAL_P6_PORT:-19500}"
INTERNAL_RAW_PORT="${INTERNAL_RAW_PORT:-19510}"
INTERNAL_DIALOG_PORT="${INTERNAL_DIALOG_PORT:-19600}"
INSTALL_TRANSACTION_DIR=""
INSTALL_TRANSACTION_ARMED=0
INSTALL_ROOT_EXISTED_BEFORE=0
RUNTIME_VENV_BUILD=""
RUNTIME_VENV_BACKUP=""

usage() {
  cat <<'USAGE'
Usage: bash tools/linux_full_install.sh [options]

Options:
  --install-root PATH     Install root. Default: ~/.local/share/time-library
  --reinstall             Replace app files, preserve local data.
  --reset-install         Remove old install root before installing.
  --no-preserve-data      With --reset-install, do not copy old memory/log/config data back.
  --skip-openclaw         Do not connect OpenClaw during install.
  --skip-hermes           Do not connect Hermes during install.
  --skip-codex            Do not install the Codex skill or register the Codex MCP server.
  --skip-claude-desktop   Do not register the Claude Desktop local MCP bridge.
  --dialog-entry-host HOST
                          Bind the OpenClaw dialog entry proxy. Default: 127.0.0.1.
  --dialog-entry-endpoint-url URL
                          Optional OpenClaw endpoint URL. Empty means read the front-door discovery file.
  --dialog-entry-token TOKEN
                          Optional override; auto-generated when LAN access needs it.
  --no-start              Stage app files only; preserve services and host integrations.
  --no-smoke              Skip start-up checks.
  -h, --help              Show this help.
USAGE
}

log() { printf '[time-library-linux-install] %s\n' "$*"; }
warn() { printf '[time-library-linux-install WARNING] %s\n' "$*" >&2; }
die() { printf '[time-library-linux-install ERROR] %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-root) INSTALL_ROOT="$2"; shift 2 ;;
    --reinstall) REINSTALL=1; shift ;;
    --reset-install) RESET_INSTALL=1; REINSTALL=1; shift ;;
    --no-preserve-data) PRESERVE_DATA=0; shift ;;
    --skip-openclaw) SKIP_OPENCLAW=1; shift ;;
    --skip-hermes) SKIP_HERMES=1; shift ;;
    --skip-codex) SKIP_CODEX=1; shift ;;
    --skip-claude-desktop) SKIP_CLAUDE_DESKTOP=1; shift ;;
    --dialog-entry-host) DIALOG_ENTRY_HOST="$2"; shift 2 ;;
    --dialog-entry-endpoint-url) DIALOG_ENTRY_ENDPOINT_URL="$2"; shift 2 ;;
    --dialog-entry-token) DIALOG_ENTRY_TOKEN="$2"; shift 2 ;;
    --no-start) SKIP_START=1; shift ;;
    --no-smoke) RUN_SMOKE=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "$DIALOG_ENTRY_HOST" ]] || DIALOG_ENTRY_HOST="127.0.0.1"
[[ "$(uname -s)" == "Linux" ]] || die "This installer is Linux-only."
command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v rsync >/dev/null 2>&1 || die "rsync not found"
python3 -m venv --help >/dev/null 2>&1 || die "python3 venv module not available"

if [[ "$INSTALL_ROOT" == "$DEFAULT_INSTALL_ROOT" && ! -d "$INSTALL_ROOT" && -d "$LEGACY_INSTALL_ROOT" ]]; then
  REINSTALL=1
  log "Migrating existing legacy install data from ${LEGACY_INSTALL_ROOT} to ${INSTALL_ROOT}"
fi

find_codex_cli() {
  if command -v codex >/dev/null 2>&1; then
    command -v codex
    return 0
  fi
  local codex_home="${CODEX_HOME:-${HOME}/.codex}"
  local candidates=(
    "${codex_home}/chrome-native-hosts-v2.json"
    "${codex_home}/chrome-native-hosts.json"
    "${HOME}/.codex/chrome-native-hosts-v2.json"
    "${HOME}/.codex/chrome-native-hosts.json"
    "${XDG_CONFIG_HOME:-${HOME}/.config}/OpenAI/Codex/chrome-native-hosts-v2.json"
    "${XDG_CONFIG_HOME:-${HOME}/.config}/OpenAI/Codex/chrome-native-hosts.json"
  )
  python3 - "${candidates[@]}" <<'PY'
import json
import shutil
import sys
import time
from pathlib import Path

for raw_path in sys.argv[1:]:
    path = Path(raw_path).expanduser()
    if not path.is_file():
        continue
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        continue
    if isinstance(data.get("entries"), list):
        entries = data["entries"]
    elif isinstance(data.get("chromeNativeHosts"), list):
        entries = data["chromeNativeHosts"]
    elif isinstance(data, dict):
        entries = [data]
    else:
        entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        paths = entry.get("paths") if isinstance(entry.get("paths"), dict) else {}
        candidate = paths.get("codexCliPath") or entry.get("codexCliPath") or entry.get("path") or ""
        if candidate and Path(candidate).expanduser().is_file():
            print(str(Path(candidate).expanduser()))
            raise SystemExit(0)
raise SystemExit(1)
PY
}

is_wsl() {
  grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null
}

node_name() {
  local name
  name="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo linux-local)"
  if is_wsl; then
    printf '%s-wsl\n' "$name"
  else
    printf '%s\n' "$name"
  fi
}

copy_runtime_data() {
  local from="$1"
  local to="$2"
  for name in memory raw zhiyi experience_lancedb logs backups data state input output config runtime update_staging release .codex_nas_pending .checkpoint .checkpoint_p2.json update_history.jsonl; do
    if [[ -e "${from}/${name}" ]]; then
      mkdir -p "$to"
      rsync -a "${from}/${name}" "${to}/"
    fi
  done
}

backup_program_files() {
  local from="$1"
  local to="$2"
  rsync -a \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude '.playwright-cli/' \
    --exclude '.codex_nas_pending/' \
    --exclude 'logs/' \
    --exclude 'runtime/' \
    --exclude 'memory/' \
    --exclude 'raw/' \
    --exclude 'zhiyi/' \
    --exclude 'experience_lancedb/' \
    --exclude 'backups/' \
    --exclude 'data/' \
    --exclude 'state/' \
    --exclude 'input/' \
    --exclude 'output/' \
    --exclude 'update_staging/' \
    --exclude 'release/' \
    --exclude '.checkpoint' \
    --exclude '.checkpoint_p2.json' \
    --exclude 'update_history.jsonl' \
    --exclude '.DS_Store' \
    --exclude '._*' \
    "$from/" "$to/"
}

restore_program_files() {
  local from="$1"
  local to="$2"
  mkdir -p "$to"
  rsync -a --delete \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude '.playwright-cli/' \
    --exclude '.codex_nas_pending/' \
    --exclude 'logs/' \
    --exclude 'runtime/' \
    --exclude 'memory/' \
    --exclude 'raw/' \
    --exclude 'zhiyi/' \
    --exclude 'experience_lancedb/' \
    --exclude 'backups/' \
    --exclude 'data/' \
    --exclude 'state/' \
    --exclude 'input/' \
    --exclude 'output/' \
    --exclude 'update_staging/' \
    --exclude 'release/' \
    --exclude '.checkpoint' \
    --exclude '.checkpoint_p2.json' \
    --exclude 'update_history.jsonl' \
    --exclude '.DS_Store' \
    --exclude '._*' \
    "$from/" "$to/"
}

begin_install_transaction() {
  if [[ -e "$INSTALL_ROOT" || -L "$INSTALL_ROOT" ]] && [[ ! -d "$INSTALL_ROOT" || -L "$INSTALL_ROOT" ]]; then
    die "Install root exists but is not a real directory: ${INSTALL_ROOT}"
  fi
  INSTALL_TRANSACTION_DIR="$(mktemp -d "${TMPDIR:-/tmp}/time-library-install-transaction.XXXXXX")"
  chmod 700 "$INSTALL_TRANSACTION_DIR"
  [[ -d "$INSTALL_ROOT" ]] && INSTALL_ROOT_EXISTED_BEFORE=1
  local snapshot_args=()
  local unit
  while IFS= read -r unit; do
    snapshot_args+=(--path "${SYSTEMD_USER_DIR}/${unit}")
  done < <(service_names)
  snapshot_args+=(
    --path "$OPENCLAW_CONFIG"
    --path "${HOME}/.openclaw/plugins"
    --path "${HOME}/.openclaw/plugins"
    --path "${HERMES_HOME}/config.yaml"
    --path "${HERMES_HOME}/profiles/default/config.yaml"
    --path "${HERMES_HOME}/plugins/time_library"
    --path "${HERMES_HOME}/skills/time-library"
    --path "${CODEX_HOME:-${HOME}/.codex}/config.toml"
    --path "${CODEX_HOME:-${HOME}/.codex}/skills/time-library"
    --path "${HOME}/.claude.json"
    --path "${HOME}/.claude/settings.json"
    --path "${CLAUDE_CODE_SETTINGS:-${HOME}/.claude/settings.json}"
    --path "${CLAUDE_CONFIG_PATH:-${HOME}/.claude.json}"
    --path "${CLAUDE_DESKTOP_HOME:-${HOME}/.config/Claude}/claude_desktop_config.json"
    --path "${HOME}/.claude/skills/time-library"
    --path "${HOME}/.config/Claude/claude_desktop_config.json"
    --path "${CLAUDE_DESKTOP_HOME:-${HOME}/.config/Claude}/local-agent-mode-sessions/skills-plugin"
  )
  if [[ "$INSTALL_ROOT_EXISTED_BEFORE" == "1" ]]; then
    snapshot_args+=(
      --path "${INSTALL_ROOT}/config"
      --path "${INSTALL_ROOT}/.checkpoint"
      --path "${INSTALL_ROOT}/.checkpoint_p2.json"
    )
    backup_program_files "$INSTALL_ROOT" "${INSTALL_TRANSACTION_DIR}/program"
  fi
  python3 "${SOURCE_ROOT}/tools/install_transaction_snapshot.py" capture \
    --snapshot-root "${INSTALL_TRANSACTION_DIR}/files" "${snapshot_args[@]}" >/dev/null
  : > "${INSTALL_TRANSACTION_DIR}/service-state.tsv"
  if [[ "$SKIP_START" == "0" ]]; then
    while IFS= read -r unit; do
      if service_is_present "$unit" && service_targets_install_root "$unit"; then
        printf '%s\t%s\t%s\n' "$unit" \
          "$(systemctl --user is-enabled "$unit" 2>/dev/null || true)" \
          "$(systemctl --user is-active "$unit" 2>/dev/null || true)" \
          >> "${INSTALL_TRANSACTION_DIR}/service-state.tsv"
      fi
    done < <(service_names)
  fi
  INSTALL_TRANSACTION_ARMED=1
  trap 'finish_install_transaction $?' EXIT
}

rollback_install_transaction() {
  local rollback_failed=0
  set +e
  local unit enabled active
  if [[ "$SKIP_START" == "0" ]]; then
    while IFS= read -r unit; do
      if service_is_present "$unit" && ! systemctl --user stop "$unit" >/dev/null 2>&1; then
        rollback_failed=1
      fi
    done < <(service_names)
  fi
  if [[ -n "$RUNTIME_VENV_BUILD" ]]; then
    rm -rf "$RUNTIME_VENV_BUILD" || rollback_failed=1
  fi
  if [[ -n "$RUNTIME_VENV_BACKUP" && -d "$RUNTIME_VENV_BACKUP" ]]; then
    rm -rf "${INSTALL_ROOT}/.venv" || rollback_failed=1
    mv "$RUNTIME_VENV_BACKUP" "${INSTALL_ROOT}/.venv" || rollback_failed=1
  fi
  if [[ "$INSTALL_ROOT_EXISTED_BEFORE" == "1" ]]; then
    if ! restore_program_files "${INSTALL_TRANSACTION_DIR}/program" "$INSTALL_ROOT"; then
      rollback_failed=1
    fi
  else
    rm -rf "$INSTALL_ROOT" || rollback_failed=1
  fi
  if ! python3 "${SOURCE_ROOT}/tools/install_transaction_snapshot.py" restore \
    --snapshot-root "${INSTALL_TRANSACTION_DIR}/files" >/dev/null; then
    rollback_failed=1
  fi
  if [[ "$SKIP_START" == "0" ]]; then
    if ! systemctl --user daemon-reload >/dev/null 2>&1; then
      rollback_failed=1
    fi
    while IFS=$'\t' read -r unit enabled active; do
      [[ -n "$unit" ]] || continue
      if [[ "$enabled" == "enabled" ]]; then
        systemctl --user enable "$unit" >/dev/null 2>&1 || rollback_failed=1
      else
        systemctl --user disable "$unit" >/dev/null 2>&1 || rollback_failed=1
      fi
      if [[ "$active" == "active" ]]; then
        systemctl --user start "$unit" >/dev/null 2>&1 || rollback_failed=1
      fi
    done < "${INSTALL_TRANSACTION_DIR}/service-state.tsv"
  fi
  set -e
  return "$rollback_failed"
}

finish_install_transaction() {
  local status="$1"
  trap - EXIT
  if [[ "$INSTALL_TRANSACTION_ARMED" == "1" && "$status" != "0" ]]; then
    warn "Install failed; restoring the pre-install program, host configuration, and service state"
    if rollback_install_transaction; then
      rm -rf "$INSTALL_TRANSACTION_DIR"
    else
      warn "ROLLBACK_FAILED; transaction snapshot retained at ${INSTALL_TRANSACTION_DIR}"
      exit 1
    fi
  fi
  if [[ "$INSTALL_TRANSACTION_ARMED" == "0" ]]; then
    [[ -z "$INSTALL_TRANSACTION_DIR" ]] || rm -rf "$INSTALL_TRANSACTION_DIR"
  fi
  exit "$status"
}

commit_install_transaction() {
  INSTALL_TRANSACTION_ARMED=0
  trap - EXIT
  [[ -z "$INSTALL_TRANSACTION_DIR" ]] || rm -rf "$INSTALL_TRANSACTION_DIR"
}

merge_packaged_config() {
  python3 "${SOURCE_ROOT}/tools/install_config_merge.py" \
    "${SOURCE_ROOT}/config" "${INSTALL_ROOT}/config" >/dev/null
}

migrate_legacy_state_paths() {
  local receipt=""
  local status=0
  set +e
  receipt="$(python3 "${SOURCE_ROOT}/tools/install_state_migrate.py" \
    "${INSTALL_ROOT}" "${LEGACY_INSTALL_ROOT}")"
  status=$?
  set -e
  mkdir -p "${INSTALL_ROOT}/logs"
  printf '%s\n' "$receipt" >> "${INSTALL_ROOT}/logs/install_state_migration.jsonl"
  return "$status"
}

dialog_entry_needs_token() {
  if [[ "$DIALOG_ENTRY_HOST" != "127.0.0.1" && "$DIALOG_ENTRY_HOST" != "localhost" && "$DIALOG_ENTRY_HOST" != "::1" ]]; then
    return 0
  fi
  if [[ ! "$DIALOG_ENTRY_ENDPOINT_URL" =~ (127\.0\.0\.1|localhost|\[::1\]) ]]; then
    return 0
  fi
  return 1
}

ensure_dialog_entry_token() {
  dialog_entry_needs_token || return 0
  local token_file="${INSTALL_ROOT}/runtime/dialog_entry_token"
  mkdir -p "$(dirname "$token_file")"
  if [[ -z "$DIALOG_ENTRY_TOKEN" && -f "$token_file" ]]; then
    DIALOG_ENTRY_TOKEN="$(tr -d '\r\n' < "$token_file")"
  fi
  if [[ -z "$DIALOG_ENTRY_TOKEN" ]]; then
    DIALOG_ENTRY_TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
  fi
  printf '%s\n' "$DIALOG_ENTRY_TOKEN" > "$token_file"
  chmod 600 "$token_file" 2>/dev/null || true
}

current_service_names() {
  printf '%s\n' \
    time-library-p0-watcher.service \
    time-library-p3-recall.service \
    time-library-p4-provider.service \
    time-library-p6-console.service \
    time-library-raw-gateway.service \
    time-library-dialog-entry.service \
    time-library-front-door.service \
    time-library-codex-mcp-guard.service
}

legacy_service_names() {
  printf '%s\n' \
    memcore-cloud-p0-watcher.service \
    memcore-cloud-p3-recall.service \
    memcore-cloud-p4-provider.service \
    memcore-cloud-p6-console.service \
    memcore-cloud-raw-gateway.service \
    memcore-cloud-dialog-entry.service
}

service_names() {
  current_service_names
  legacy_service_names
}

stop_user_services() {
  if [[ "$SKIP_START" != "0" ]]; then
    log "Service stop skipped because --no-start preserves the current runtime"
    return 0
  fi
  if command -v systemctl >/dev/null 2>&1 && systemctl --user status >/dev/null 2>&1; then
    while IFS= read -r unit; do
      service_targets_install_root "$unit" || continue
      if systemctl --user is-active --quiet "$unit"; then
        systemctl --user stop "$unit" >/dev/null
      fi
    done < <(service_names)
  fi
}

assert_runtime_quiescent() {
  local root_args=(--root "$INSTALL_ROOT")
  if [[ "$INSTALL_ROOT" == "$DEFAULT_INSTALL_ROOT" ]]; then
    root_args+=(--root "$LEGACY_INSTALL_ROOT")
  fi
  python3 "${SOURCE_ROOT}/tools/install_runtime_quiescence.py" "${root_args[@]}"
}

service_is_present() {
  local unit="$1"
  [[ -f "${SYSTEMD_USER_DIR}/${unit}" ]] && return 0
  local load_state=""
  load_state="$(systemctl --user show "$unit" --property=LoadState --value 2>/dev/null || true)"
  [[ -n "$load_state" && "$load_state" != "not-found" ]]
}

service_targets_install_root() {
  local unit="$1"
  local unit_path="${SYSTEMD_USER_DIR}/${unit}"
  local allowed_roots=("$INSTALL_ROOT")
  if [[ "$INSTALL_ROOT" == "$DEFAULT_INSTALL_ROOT" ]]; then
    allowed_roots+=("$LEGACY_INSTALL_ROOT")
  fi
  local identity_args=()
  local allowed_root
  for allowed_root in "${allowed_roots[@]}"; do
    identity_args+=(--root "$allowed_root")
  done
  local definition=""
  definition="$(systemctl --user show "$unit" --property=ExecStart --value 2>/dev/null || true)"
  printf '%s\n' "$definition" | python3 "${SOURCE_ROOT}/tools/install_runtime_identity.py" \
    systemd --path "$unit_path" "${identity_args[@]}"
}

assert_user_service_ownership_available() {
  [[ "$SKIP_START" == "0" ]] || return 0
  local unit
  while IFS= read -r unit; do
    if service_is_present "$unit" && ! service_targets_install_root "$unit"; then
      die "User service ${unit} belongs to another Time Library install root; use --no-start or stop that installation explicitly"
    fi
  done < <(service_names)
}

stop_stale_runtime_processes() {
  local roots=("$INSTALL_ROOT")
  if [[ "$INSTALL_ROOT" == "$DEFAULT_INSTALL_ROOT" ]]; then
    roots+=("$LEGACY_INSTALL_ROOT")
  fi
  python3 - "$SOURCE_ROOT" "${roots[@]}" <<'PY'
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from tools.install_runtime_identity import argv_targets_install_roots

roots = sys.argv[2:]
matched = []
for proc in Path("/proc").iterdir():
    if not proc.name.isdigit():
        continue
    pid = int(proc.name)
    if pid in {os.getpid(), os.getppid()}:
        continue
    try:
        if proc.stat().st_uid != os.getuid():
            continue
        args = [
            arg.decode("utf-8", errors="replace")
            for arg in (proc / "cmdline").read_bytes().split(b"\0")
            if arg
        ]
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    if not argv_targets_install_roots(args, roots):
        continue
    try:
        os.kill(pid, signal.SIGTERM)
        matched.append(pid)
    except ProcessLookupError:
        pass

deadline = time.monotonic() + 5
while matched and time.monotonic() < deadline:
    alive = []
    for pid in matched:
        try:
            os.kill(pid, 0)
            alive.append(pid)
        except ProcessLookupError:
            pass
    matched = alive
    if matched:
        time.sleep(0.1)
for pid in matched:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
PY
}

install_files() {
  mkdir -p "$(dirname "$INSTALL_ROOT")" "$LOG_DIR"
  local migrated_legacy=0
  if [[ "$INSTALL_ROOT" == "$DEFAULT_INSTALL_ROOT" && ! -d "$INSTALL_ROOT" && -d "$LEGACY_INSTALL_ROOT" ]]; then
    mkdir -p "$INSTALL_ROOT"
    copy_runtime_data "$LEGACY_INSTALL_ROOT" "$INSTALL_ROOT"
    migrated_legacy=1
  fi
  local backup=""
  if [[ -d "$INSTALL_ROOT" && "$REINSTALL" == "1" && "$migrated_legacy" == "0" ]]; then
    if [[ "$RESET_INSTALL" == "1" ]]; then
      if [[ "$PRESERVE_DATA" == "1" ]]; then
        backup="${INSTALL_ROOT}.backup.$(date +%Y%m%d%H%M%S)"
        log "Backing up existing install to ${backup}"
        rsync -a "$INSTALL_ROOT/" "$backup/"
      fi
      rm -rf "$INSTALL_ROOT"
      mkdir -p "$INSTALL_ROOT"
      if [[ -n "$backup" ]]; then
        copy_runtime_data "$backup" "$INSTALL_ROOT"
      fi
    else
      backup="${INSTALL_ROOT}.backup.$(date +%Y%m%d%H%M%S)"
      log "Backing up existing install to ${backup}"
      backup_program_files "$INSTALL_ROOT" "$backup"
    fi
  fi
  mkdir -p "$INSTALL_ROOT"
  rsync -a --delete \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude '.playwright-cli/' \
    --exclude '.codex_nas_pending/' \
    --exclude 'config/' \
    --exclude 'logs/' \
    --exclude 'runtime/' \
    --exclude 'memory/' \
    --exclude 'raw/' \
    --exclude 'zhiyi/' \
    --exclude 'experience_lancedb/' \
    --exclude 'backups/' \
    --exclude 'data/' \
    --exclude 'state/' \
    --exclude 'input/' \
    --exclude 'output/' \
    --exclude 'update_staging/' \
    --exclude 'release/' \
    --exclude '.checkpoint' \
    --exclude '.checkpoint_p2.json' \
    --exclude 'update_history.jsonl' \
    --exclude '.DS_Store' \
    --exclude '._*' \
    "${SOURCE_ROOT}/" "${INSTALL_ROOT}/"
  rm -rf -- "${INSTALL_ROOT}/.playwright-cli"
  merge_packaged_config
  migrate_legacy_state_paths
}

write_config() {
  mkdir -p "${INSTALL_ROOT}/config" "${INSTALL_ROOT}/logs" "${INSTALL_ROOT}/runtime" \
    "${INSTALL_ROOT}/memory" "${INSTALL_ROOT}/zhiyi/case_memory" \
    "${INSTALL_ROOT}/zhiyi/error_memory" "${INSTALL_ROOT}/zhiyi/preference_memory" \
    "${INSTALL_ROOT}/experience_lancedb" "${INSTALL_ROOT}/backups" "${INSTALL_ROOT}/output"

  [[ -f "${INSTALL_ROOT}/config/model_config.json" || ! -f "${INSTALL_ROOT}/config/default_model_config.json" ]] || \
    cp "${INSTALL_ROOT}/config/default_model_config.json" "${INSTALL_ROOT}/config/model_config.json"
  [[ -f "${INSTALL_ROOT}/config/feature_flags.json" || ! -f "${INSTALL_ROOT}/config/default_feature_flags.json" ]] || \
    cp "${INSTALL_ROOT}/config/default_feature_flags.json" "${INSTALL_ROOT}/config/feature_flags.json"
  [[ -f "${INSTALL_ROOT}/config/alias_map.json" || ! -f "${INSTALL_ROOT}/config/default_alias_map.json" ]] || \
    cp "${INSTALL_ROOT}/config/default_alias_map.json" "${INSTALL_ROOT}/config/alias_map.json"
  [[ -f "${INSTALL_ROOT}/config/window_binding_registry.json" || ! -f "${INSTALL_ROOT}/config/default_window_binding_registry.json" ]] || \
    cp "${INSTALL_ROOT}/config/default_window_binding_registry.json" "${INSTALL_ROOT}/config/window_binding_registry.json"

  python3 - "$INSTALL_ROOT" "$(node_name)" "$DIALOG_ENTRY_HOST" "$DIALOG_ENTRY_ENDPOINT_URL" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
node = sys.argv[2]
dialog_entry_host = sys.argv[3]
dialog_entry_endpoint_url = sys.argv[4]

cfg_path = root / "config" / "memcore.json"
cfg = {}
if cfg_path.exists():
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except Exception:
        cfg = {}
cfg["_comment"] = "Time Library user-level Linux config"
cfg["_base_dir"] = str(root)
cfg["version"] = str(cfg.get("version") or "1.0.0")
cfg["paths"] = {
    "memory": "memory",
    "openclaw_agents": "~/.openclaw/agents",
    "openclaw_workspace": "~/.openclaw/workspace",
    "zhiyi": "zhiyi",
    "config_dir": "config",
    "experience_lancedb": "experience_lancedb",
    "checkpoint": ".checkpoint",
    "alias_map": "config/alias_map.json",
    "model_config": "config/model_config.json",
    "lancedb_v2_metadata": "config/lancedb_v2_metadata.json",
    "logs": "logs",
}
cfg["nodes"] = {"current": node, "raw_memory_subpath": f"{node}/openclaw/openclaw_session_jsonl"}
cfg["services"] = {
    "p0_watcher_enabled": True,
    "p0_watcher_resource_profile": cfg.get("services", {}).get("p0_watcher_resource_profile") or "light",
    "p0_watcher_source_default": "all",
    "p0_watcher_interval_milliseconds": int(cfg.get("services", {}).get("p0_watcher_interval_milliseconds") or 5000),
    "front_door_port": 9850,
    "internal_p3_port": 19300,
    "internal_p4_port": 19400,
    "internal_p6_port": 19500,
    "internal_raw_port": 19510,
    "internal_dialog_port": 19600,
    "dialog_entry_host": dialog_entry_host,
    "dialog_entry_endpoint_url": dialog_entry_endpoint_url,
    "dialog_entry_lan_requires_token": True,
}
claude_desktop = cfg.setdefault("integrations", {}).setdefault("claude_desktop", {})
raw_ingest = claude_desktop.setdefault("raw_ingest", {})
raw_ingest.update({
    "enabled": True,
    "authorization": "user_authorized_local_claude_desktop_parser_to_time_library_raw_only",
    "write_target": "memcore_raw_only",
    "platform_write_allowed": False,
    "interval_milliseconds": int(raw_ingest.get("interval_milliseconds") or 5000),
    "limit": int(raw_ingest.get("limit") or 20),
})
cfg.setdefault("integrations", {}).setdefault("hermes", {}).setdefault("model_call", {}).update({
    "hermes_provider": "minimax",
    "hermes_model": "MiniMax-M2.7",
    "source": "memcore-time_library",
})
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

model_cfg_path = root / "config" / "model_config.json"
model_cfg = {}
if model_cfg_path.exists():
    try:
        model_cfg = json.loads(model_cfg_path.read_text(encoding="utf-8-sig"))
    except Exception:
        model_cfg = {}
model_cfg["version"] = str(model_cfg.get("version") or "1.0")
recall = model_cfg.setdefault("recall", {})
recall["mode"] = "substring"
recall.setdefault("substring", {"table": "experiences"})
model_cfg_path.write_text(json.dumps(model_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

flags_path = root / "config" / "feature_flags.json"
flags = {}
if flags_path.exists():
    try:
        flags = json.loads(flags_path.read_text(encoding="utf-8-sig"))
    except Exception:
        flags = {}

passive_flags = {
    "zhiyi_direct": False,
    "zhiyi_inject": False,
    "openclaw_passive_auto_inject": False,
    "openclaw_rpc": False,
    "passthrough": True,
    "audit_log": True,
}
changed_keys = [key for key, value in passive_flags.items() if flags.get(key) != value]
backup_path = None
if changed_keys and flags_path.exists():
    backup_path = flags_path.with_name(flags_path.name + ".time_library-passive-migration." + time.strftime("%Y%m%d%H%M%S"))
    shutil.copy2(flags_path, backup_path)
flags.update(passive_flags)
flags_path.write_text(json.dumps(flags, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
if changed_keys:
    receipt_path = root / "logs" / "passive_delivery_migration.jsonl"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "action": "passive_delivery_migration",
        "source": "linux_full_install",
        "changed_keys": changed_keys,
        "feature_flags_path": str(flags_path),
        "backup_path": str(backup_path) if backup_path else None,
        "note": "Safety migration after OpenClaw direct-answer boundary fix; explicit opt-in must be re-enabled intentionally after install.",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with receipt_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(receipt, ensure_ascii=False) + "\n")
PY
}

install_python_env() {
  log "Preparing Python venv"
  local build_root="${INSTALL_ROOT}/.venv-build.$RANDOM"
  RUNTIME_VENV_BUILD="$build_root"
  rm -rf "$build_root"
  if python3 -m venv "$build_root"; then
    RUNTIME_PYTHON="${build_root}/bin/python"
    "${RUNTIME_PYTHON}" -m pip install --upgrade pip >/dev/null
    if [[ -f "${INSTALL_ROOT}/requirements-core.txt" ]]; then
      "${RUNTIME_PYTHON}" -m pip install -r "${INSTALL_ROOT}/requirements-core.txt"
    fi
    if [[ -d "${INSTALL_ROOT}/.venv" ]]; then
      RUNTIME_VENV_BACKUP="${INSTALL_TRANSACTION_DIR}/old-venv"
      mv "${INSTALL_ROOT}/.venv" "$RUNTIME_VENV_BACKUP"
    fi
    mv "$build_root" "${INSTALL_ROOT}/.venv"
    RUNTIME_PYTHON="${INSTALL_ROOT}/.venv/bin/python"
    RUNTIME_VENV_BUILD=""
  else
    warn "python3 venv failed; trying system python without root"
    rm -rf "$build_root"
    RUNTIME_VENV_BUILD=""
    python3 - <<'PY'
import importlib.util
import sys

required = ["cryptography", "yaml"]
if sys.version_info < (3, 11):
    required.append("tomli")
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit("system python missing packages: " + ", ".join(missing))
PY
    RUNTIME_PYTHON="$(command -v python3)"
  fi
  printf '%s\n' "$RUNTIME_PYTHON" > "${INSTALL_ROOT}/runtime/python_path"
}

write_systemd_service() {
  local unit="$1"
  local log_name="$2"
  shift 2
  mkdir -p "$SYSTEMD_USER_DIR" "$LOG_DIR"
  python3 - "$SYSTEMD_USER_DIR/$unit" "$INSTALL_ROOT" "$LOG_DIR" "$log_name" "$DIALOG_ENTRY_HOST" "$DIALOG_ENTRY_TOKEN" "$@" <<'PY'
import shlex
import sys
from pathlib import Path

unit_path = Path(sys.argv[1])
root = sys.argv[2]
log_dir = sys.argv[3]
log_name = sys.argv[4]
dialog_entry_host = sys.argv[5]
dialog_entry_token = sys.argv[6]
args = sys.argv[7:]
env = {
    "TIME_LIBRARY_ROOT": root,
    "TIME_LIBRARY_INSTALL_ROOT": root,
    "MEMCORE_ROOT": root,
    "MEMCORE_INSTALL_ROOT": root,
    "PYTHONPATH": root,
    "PYTHONIOENCODING": "utf-8",
    "MEMCORE_HERMES_CLI": str(Path.home() / ".local" / "bin" / "hermes"),
    "MEMCORE_DIALOG_ENTRY_HOST": dialog_entry_host,
}
if dialog_entry_token and log_name == "dialog-entry":
    env["MEMCORE_DIALOG_ENTRY_TOKEN"] = dialog_entry_token
lines = [
    "[Unit]",
    f"Description=Time Library {log_name}",
    "",
    "[Service]",
    "Type=simple",
    f"WorkingDirectory={root}",
]
for key, value in env.items():
    lines.append(f'Environment="{key}={value}"')
lines.extend([
    f"ExecStart={shlex.join(args)}",
    "Restart=on-failure",
    "RestartSec=2",
    f"StandardOutput=append:{Path(log_dir) / (log_name + '.out.log')}",
    f"StandardError=append:{Path(log_dir) / (log_name + '.err.log')}",
    "",
    "[Install]",
    "WantedBy=default.target",
    "",
])
unit_path.write_text("\n".join(lines), encoding="utf-8")
PY
}

install_user_services() {
  local py="${RUNTIME_PYTHON:-${INSTALL_ROOT}/.venv/bin/python}"
  write_systemd_service time-library-p0-watcher.service p0-watcher \
    "$py" "${INSTALL_ROOT}/src/memcore-cloud.py" --watch --source all
  write_systemd_service time-library-p3-recall.service p3-recall \
    "$py" "${INSTALL_ROOT}/src/p3_recall.py" serve --port "$INTERNAL_P3_PORT"
  write_systemd_service time-library-p4-provider.service p4-provider \
    "$py" "${INSTALL_ROOT}/src/p4_provider.py" --port "$INTERNAL_P4_PORT"
  write_systemd_service time-library-p6-console.service p6-console \
    "$py" "${INSTALL_ROOT}/src/p6_console.py" --host 127.0.0.1 --port "$INTERNAL_P6_PORT"
  write_systemd_service time-library-raw-gateway.service raw-gateway \
    "$py" "${INSTALL_ROOT}/src/raw_consumption_gateway.py" --port "$INTERNAL_RAW_PORT"
  write_systemd_service time-library-dialog-entry.service dialog-entry \
    "$py" "${INSTALL_ROOT}/src/dialog_entry_proxy.py" --host 127.0.0.1 --port "$INTERNAL_DIALOG_PORT"
  write_systemd_service time-library-front-door.service front-door \
    "$py" "${INSTALL_ROOT}/src/single_port_runtime.py" --host 127.0.0.1 --preferred-port "$FRONT_DOOR_PORT"
  install_codex_mcp_guard_service
}

start_user_services() {
  command -v systemctl >/dev/null 2>&1 || die "systemctl not found for user services"
  if command -v loginctl >/dev/null 2>&1; then
    if loginctl enable-linger "$USER" >/dev/null 2>&1; then
      log "Enabled user lingering for background services"
    else
      warn "Could not enable user lingering; services will start only while the user is logged in"
    fi
  else
    warn "loginctl not found; services will start only while the user is logged in"
  fi
  systemctl --user daemon-reload
  while IFS= read -r unit; do
    systemctl --user disable --now "$unit" >/dev/null 2>&1 || true
  done < <(legacy_service_names)
  while IFS= read -r unit; do
    if [[ "$unit" == "time-library-codex-mcp-guard.service" && ! -f "${SYSTEMD_USER_DIR}/${unit}" ]]; then
      continue
    fi
    systemctl --user enable --now "$unit" >/dev/null
  done < <(current_service_names)
}

install_openclaw_plugin() {
  [[ "$SKIP_OPENCLAW" == "1" ]] && return
  local plugin_src="${INSTALL_ROOT}/system/openclaw/plugins/time-library-native"
  [[ -d "$plugin_src" ]] || { warn "OpenClaw plugin source not found: ${plugin_src}"; return; }
  local openclaw_cmd=""
  openclaw_cmd="$(command -v openclaw 2>/dev/null || true)"
  if [[ -n "$openclaw_cmd" && "$openclaw_cmd" != /mnt/c/* ]]; then
    openclaw plugins install --link "$plugin_src" >/dev/null 2>&1 || true
    openclaw plugins registry --refresh >/dev/null 2>&1 || true
  elif [[ -n "$openclaw_cmd" ]]; then
    warn "Skipping OpenClaw CLI plugin command because openclaw resolves to Windows interop path: ${openclaw_cmd}"
  fi
  if [[ -f "$OPENCLAW_CONFIG" ]]; then
    python3 - "$OPENCLAW_CONFIG" "$plugin_src" "$DIALOG_ENTRY_ENDPOINT_URL" "$DIALOG_ENTRY_TOKEN" "$INSTALL_ROOT" "$LEGACY_INSTALL_ROOT" <<'PY'
import json
import shutil
import sys
import time
from pathlib import Path

cfg_path = Path(sys.argv[1])
plugin_src = sys.argv[2]
endpoint_url = sys.argv[3]
dialog_entry_token = sys.argv[4]
install_root = Path(sys.argv[5]).expanduser().resolve()
legacy_root = Path(sys.argv[6]).expanduser().resolve()
cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
backup = cfg_path.with_name(cfg_path.name + ".time_library-bak." + time.strftime("%Y%m%d%H%M%S"))
shutil.copy2(cfg_path, backup)
plugins = cfg.setdefault("plugins", {})
entries = plugins.setdefault("entries", {})
legacy_entry = "memcore-" + "zhiyi-native"
entries.pop(legacy_entry, None)
entry = entries.setdefault("time-library-native", {})
entry["enabled"] = False
entry["config"] = {
    **(entry.get("config") if isinstance(entry.get("config"), dict) else {}),
    "enabled": False,
    "endpointUrl": endpoint_url,
    "dialogEntryToken": dialog_entry_token,
    "allowedChannels": ["webchat"],
    "enableModelCall": False,
    "forceZhiyiDirect": False,
    "timeoutMs": 120000,
}
load = plugins.setdefault("load", {})
paths = load.setdefault("paths", [])
if isinstance(paths, list):
    stale_paths = {
        (root / "system/openclaw/plugins" / name).resolve()
        for root in (install_root, legacy_root)
        for name in (legacy_entry, "time-library-native")
    }
    current_path = Path(plugin_src).expanduser().resolve()
    paths[:] = [
        path for path in paths
        if not (
            isinstance(path, str)
            and Path(path).expanduser().resolve() in stale_paths
            and Path(path).expanduser().resolve() != current_path
        )
    ]
    if plugin_src not in paths:
        paths.append(plugin_src)
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  else
    warn "OpenClaw config not found: ${OPENCLAW_CONFIG}"
  fi
}

install_hermes_plugin() {
  [[ "$SKIP_HERMES" == "1" ]] && return
  local src="${INSTALL_ROOT}/system/hermes/plugins/time_library"
  [[ -d "$src" ]] || { warn "Hermes plugin source not found: ${src}"; return; }
  mkdir -p "${HERMES_HOME}/plugins"
  rm -rf "${HERMES_HOME}/plugins/time_library"
  rsync -a "$src/" "${HERMES_HOME}/plugins/time_library/"
  local skill_src="${INSTALL_ROOT}/system/skills/time-library"
  local skill_dst="${HERMES_HOME}/skills/time-library"
  if [[ -d "$skill_src" ]]; then
    mkdir -p "${HERMES_HOME}/skills"
    rm -rf "$skill_dst"
    rsync -a "$skill_src/" "$skill_dst/"
    log "Hermes skill installed: ${skill_dst}"
  else
    warn "Hermes skill source not found: ${skill_src}"
  fi

  "${RUNTIME_PYTHON:-$(command -v python3)}" - "$HERMES_HOME" <<'PY'
import shutil
import sys
import time
from pathlib import Path

home = Path(sys.argv[1]).expanduser()
profile_cfg = home / "profiles" / "default" / "config.yaml"
root_cfg = home / "config.yaml"
if profile_cfg.exists():
    cfg_path = profile_cfg
elif root_cfg.exists():
    cfg_path = root_cfg
elif (home / "profiles").exists():
    cfg_path = profile_cfg
else:
    cfg_path = root_cfg
cfg_path.parent.mkdir(parents=True, exist_ok=True)
try:
    import yaml
except Exception:
    yaml = None

if yaml:
    cfg = {}
    if cfg_path.exists():
        backup = cfg_path.with_name(cfg_path.name + ".time_library-bak." + time.strftime("%Y%m%d%H%M%S"))
        shutil.copy2(cfg_path, backup)
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8-sig")) or {}
        if not isinstance(cfg, dict):
            cfg = {}
    memory = cfg.setdefault("memory", {})
    memory["provider"] = "time_library"
    plugins = cfg.setdefault("plugins", {})
    enabled = plugins.setdefault("enabled", [])
    legacy_plugin = "memcore_" + "yifan" + "chen"
    if isinstance(enabled, list):
        enabled[:] = [name for name in enabled if name != legacy_plugin]
        if "time_library" not in enabled:
            enabled.append("time_library")
    plugins.pop(legacy_plugin, None)
    plugins["time_library"] = {
        **(plugins.get("time_library") if isinstance(plugins.get("time_library"), dict) else {}),
        "provider_url": "",
        "memory_scope": "window",
        "computer_name": "",
        "limit": 3,
        "excerpt_chars": 500,
        "context_chars": 2400,
        "timeout_seconds": 5,
        "include_session_id": True,
        "receipt_url": "",
        "enable_receipts": True,
        "enable_queue_prefetch": True,
    }
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
else:
    if cfg_path.exists():
        raise SystemExit("PyYAML is required to migrate an existing Hermes config safely")
    block = """
memory:
  provider: time_library
plugins:
  enabled:
    - time_library
  time_library:
    provider_url: ""
    memory_scope: window
    computer_name: ""
    limit: 3
    excerpt_chars: 500
    context_chars: 2400
    timeout_seconds: 5
    include_session_id: true
    receipt_url: ""
    enable_receipts: true
    enable_queue_prefetch: true
"""
    cfg_path.write_text(block.lstrip(), encoding="utf-8")
PY
}

install_codex_skill() {
  if [[ "$SKIP_CODEX" == "1" ]]; then
    CODEX_SKILL_STATUS="skipped"
    return
  fi
  local skill_src="${INSTALL_ROOT}/system/skills/time-library"
  if [[ ! -d "$skill_src" ]]; then
    warn "Codex skill source not found: ${skill_src}"
    CODEX_SKILL_STATUS="source not found"
    return
  fi
  local codex_home="${CODEX_HOME:-${HOME}/.codex}"
  local skill_dst="${codex_home}/skills/time-library"
  local backup_root="${codex_home}/skills-backups/time-library-$(date +%Y%m%d%H%M%S)"
  mkdir -p "$(dirname "$skill_dst")"
  shopt -s nullglob
  local stale_skill
  for stale_skill in "${codex_home}/skills"/time-library.backup* "${codex_home}/skills"/time-library.backup*; do
    mkdir -p "$backup_root"
    mv "$stale_skill" "$backup_root/"
    log "Moved stale Codex Time Library skill backup out of active skills: ${stale_skill}"
  done
  shopt -u nullglob
  rm -rf "$skill_dst"
  rsync -a "$skill_src/" "$skill_dst/"
  log "Codex skill installed: ${skill_dst}"
  CODEX_SKILL_STATUS="time-library"
}

install_codex_mcp() {
  if [[ "$SKIP_CODEX" == "1" ]]; then
    CODEX_MCP_STATUS="skipped"
    CODEX_MCP_GUARD_STATUS="skipped"
    return
  fi
  local bridge="${INSTALL_ROOT}/tools/codex_mcp_bridge.py"
  local guard="${INSTALL_ROOT}/tools/codex_mcp_config_guard.py"
  local config_path="${CODEX_HOME:-${HOME}/.codex}/config.toml"
  local guard_python="${RUNTIME_PYTHON:-${INSTALL_ROOT}/.venv/bin/python}"
  [[ -x "$guard_python" ]] || guard_python="$(command -v python3)"
  local codex_exe=""
  if [[ ! -f "$config_path" ]] && ! codex_exe="$(find_codex_cli)"; then
    warn "Codex CLI/config not found; skipping Codex MCP registration and guard"
    CODEX_MCP_STATUS="Codex not detected"
    CODEX_MCP_GUARD_STATUS="Codex not detected"
    return
  fi
  if [[ ! -f "$bridge" ]]; then
    warn "Codex MCP bridge not found: ${bridge}"
    CODEX_MCP_STATUS="bridge not found"
    CODEX_MCP_GUARD_STATUS="bridge not found"
    return
  fi
  if [[ ! -f "$guard" ]]; then
    warn "Codex MCP config guard not found: ${guard}"
    CODEX_MCP_STATUS="guard not found"
    CODEX_MCP_GUARD_STATUS="guard not found"
    return
  fi
  if "$guard_python" "$guard" \
    --once \
    --config "$config_path" \
    --install-root "$INSTALL_ROOT" \
    --python-executable "$guard_python" \
    --create-if-missing >/dev/null 2>&1; then
    CODEX_MCP_GUARD_STATUS="installed"
    log "Codex MCP registered with protected relay-preserving guard: time-library via ${bridge}"
    CODEX_MCP_STATUS="time-library (guarded)"
  else
    warn "Codex MCP registration failed; existing host configuration and guard were left unchanged"
    CODEX_MCP_STATUS="registration failed"
    CODEX_MCP_GUARD_STATUS="registration failed"
  fi
}

install_codex_mcp_guard_service() {
  local unit="time-library-codex-mcp-guard.service"
  if [[ "$CODEX_MCP_GUARD_STATUS" != "installed" ]]; then
    # Do not remove an existing guard when this installation cannot refresh
    # the host stanza.  A failed/ skipped registration must retain protection;
    # an explicit uninstall is the only path that removes the service.
    log "Codex MCP config guard unchanged: ${CODEX_MCP_GUARD_STATUS}"
    return 0
  fi
  local py="${RUNTIME_PYTHON:-${INSTALL_ROOT}/.venv/bin/python}"
  local config_path="${CODEX_HOME:-${HOME}/.codex}/config.toml"
  local guard="${INSTALL_ROOT}/tools/codex_mcp_config_guard.py"
  write_systemd_service "$unit" codex-mcp-guard \
    "$py" "$guard" --watch \
    --config "$config_path" \
    --install-root "$INSTALL_ROOT" \
    --python-executable "$py"
}

install_claude_code_preflight_hook() {
  local hook_helper="${INSTALL_ROOT}/tools/install_claude_code_preflight_hook.py"
  local hook_script="${INSTALL_ROOT}/tools/claude_code_preflight_hook.py"
  local settings_path="${CLAUDE_CODE_SETTINGS:-${HOME}/.claude/settings.json}"
  if [[ ! -f "$hook_helper" || ! -f "$hook_script" ]]; then
    warn "Claude Code preflight hook helper not found; skipping"
    CLAUDE_CODE_HOOK_STATUS="helper not found"
    return
  fi
  if [[ ! -d "${HOME}/.claude" && -z "${CLAUDE_CODE_SETTINGS:-}" ]]; then
    CLAUDE_CODE_HOOK_STATUS="Claude Code settings not found"
    return
  fi
  local python_bin="${RUNTIME_PYTHON:-$(command -v python3)}"
  local result
  result="$("$python_bin" "$hook_helper" \
    --settings-path "$settings_path" \
    --hook-script "$hook_script" \
    --python "$python_bin" \
    --json 2>/dev/null || true)"
  local status
  status="$(HOOK_RESULT="$result" "$python_bin" - <<'PY'
import json
import os
try:
    data = json.loads(os.environ.get("HOOK_RESULT") or "{}")
except Exception:
    data = {}
print(f"{'ok' if data.get('ok') else 'fail'}:{data.get('reason') or 'unavailable'}")
PY
)"
  if [[ "$status" == ok:* ]]; then
    log "Claude Code preflight hook installed: ${status#*:}"
    CLAUDE_CODE_HOOK_STATUS="${status#*:}"
  else
    warn "Claude Code preflight hook not installed: ${status#*:}"
    CLAUDE_CODE_HOOK_STATUS="${status#*:}"
  fi
}

install_claude_code_mcp() {
  local claude_cmd
  claude_cmd="$(command -v claude 2>/dev/null || true)"
  if [[ -z "$claude_cmd" ]]; then
    CLAUDE_CODE_MCP_STATUS="Claude Code CLI not found"
    return
  fi
  local bridge="${INSTALL_ROOT}/tools/claude_desktop_mcp_bridge.py"
  local registry_path="${INSTALL_ROOT}/config/window_binding_registry.json"
  local py="${RUNTIME_PYTHON:-${INSTALL_ROOT}/.venv/bin/python}"
  if [[ ! -f "$bridge" || ! -x "$py" ]]; then
    warn "Claude Code MCP bridge or runtime Python not found"
    CLAUDE_CODE_MCP_STATUS="bridge or runtime missing"
    return
  fi
  local claude_config="${CLAUDE_CONFIG_PATH:-${HOME}/.claude.json}"
  if [[ -f "$claude_config" ]]; then
    cp -p "$claude_config" "${claude_config}.bak-time_library-port-discovery-$(date -u +%Y%m%dT%H%M%SZ)"
  fi
  "$claude_cmd" mcp remove time-library -s user >/dev/null 2>&1 || true
  if "$claude_cmd" mcp add -s user time-library \
    -e "PYTHONIOENCODING=utf-8" \
    -e "PYTHONUTF8=1" \
    -e "MEMCORE_ROOT=${INSTALL_ROOT}" \
    -e "MEMCORE_WINDOW_BINDING_REGISTRY=${registry_path}" \
    -- "$py" "$bridge" \
      --consumer claude_code_cli \
      --timeout 30 \
      --window-binding-registry "$registry_path" \
      --binding-key claude_code_cli >/dev/null 2>&1; then
    log "Claude Code MCP migrated to per-request front-door discovery"
    CLAUDE_CODE_MCP_STATUS="time-library (stdio discovery)"
  else
    warn "Claude Code MCP migration failed"
    CLAUDE_CODE_MCP_STATUS="registration failed"
  fi
}

install_claude_desktop_mcp() {
  if [[ "$SKIP_CLAUDE_DESKTOP" == "1" ]]; then
    CLAUDE_DESKTOP_STATUS="skipped"
    return
  fi
  local claude_home="${CLAUDE_DESKTOP_HOME:-${HOME}/.config/Claude}"
  if [[ ! -d "$claude_home" ]]; then
    warn "Claude Desktop home not found; skipping Claude Desktop MCP registration"
    CLAUDE_DESKTOP_STATUS="Claude Desktop not found"
    return
  fi
  local bridge="${INSTALL_ROOT}/tools/claude_desktop_mcp_bridge.py"
  if [[ ! -f "$bridge" ]]; then
    warn "Claude Desktop MCP bridge not found: ${bridge}"
    CLAUDE_DESKTOP_STATUS="bridge not found"
    return
  fi
  local skill_src="${INSTALL_ROOT}/system/skills/time-library"
  local skill_helper="${INSTALL_ROOT}/tools/install_claude_desktop_skill.py"
  python3 - "$claude_home" "$bridge" "$INSTALL_ROOT" <<'PY'
import json
import os
import sys
from pathlib import Path

home = Path(sys.argv[1])
bridge = Path(sys.argv[2])
install_root = Path(sys.argv[3])
registry_path = install_root / "config" / "window_binding_registry.json"
cfg_path = home / "claude_desktop_config.json"
cfg = {}
if cfg_path.exists():
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except Exception:
        backup = cfg_path.with_suffix(cfg_path.suffix + ".invalid-time_library-bak")
        try:
            backup.write_text(cfg_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        except Exception:
            pass
        cfg = {}
servers = cfg.setdefault("mcpServers", {})
servers["time-library"] = {
    "type": "stdio",
    "command": sys.executable,
    "args": [
        str(bridge),
        "--timeout", "30",
        "--window-binding-registry", str(registry_path),
        "--binding-key", "claude_desktop",
    ],
    "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "MEMCORE_ROOT": str(install_root),
        "MEMCORE_WINDOW_BINDING_REGISTRY": str(registry_path),
        "MEMCORE_CLAUDE_DESKTOP_CANONICAL_WINDOW_ID": "",
        "MEMCORE_CLAUDE_DESKTOP_SESSION_ID": "",
    },
}
home.mkdir(parents=True, exist_ok=True)
if cfg_path.exists():
    backup = cfg_path.with_suffix(cfg_path.suffix + ".bak-time_library")
    if not backup.exists():
        backup.write_text(cfg_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
tmp = cfg_path.with_suffix(cfg_path.suffix + ".tmp")
tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(tmp, cfg_path)
print(str(cfg_path))
PY
  if [[ -f "$skill_helper" && -d "$skill_src" ]]; then
    local skill_result
    skill_result="$(python3 "$skill_helper" "$claude_home" "$skill_src" --create --json 2>/dev/null || true)"
    local skill_status
    skill_status="$(SKILL_RESULT="$skill_result" python3 - <<'PY'
import json
import os
import sys

try:
    data = json.loads(os.environ.get("SKILL_RESULT") or "{}")
except Exception:
    data = {}
print(f"{int(data.get('installed_count') or 0)}:{data.get('reason') or 'unavailable'}")
PY
)"
    if [[ "$skill_status" == 0:* ]]; then
      log "Claude Desktop skill not updated: ${skill_status#*:}"
    else
      log "Claude Desktop skill updated: time-library"
    fi
  fi
  log "Claude Desktop MCP registered: time-library via ${bridge}"
  "${RUNTIME_PYTHON:-$(command -v python3)}" "${INSTALL_ROOT}/tools/refresh_claude_desktop_mcp_bridges.py" \
    --install-root "$INSTALL_ROOT" \
    --install-root "$LEGACY_INSTALL_ROOT" >/dev/null 2>&1 || true
  CLAUDE_DESKTOP_STATUS="time-library"
}

smoke_check() {
  local name="$1"
  local url="$2"
  local max_wait="${3:-75}"
  python3 - "$name" "$url" "$max_wait" <<'PY'
import sys
import time
import urllib.request

name, url, max_wait_raw = sys.argv[1], sys.argv[2], sys.argv[3]
max_wait = float(max_wait_raw)
deadline = time.monotonic() + max_wait
attempt = 0
last_error = None

while True:
    attempt += 1
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            body = resp.read(500).decode("utf-8", errors="replace")
        print(f"{name}: ok after {attempt} attempt(s) {body[:160]}")
        raise SystemExit(0)
    except Exception as exc:
        last_error = exc
        if time.monotonic() >= deadline:
            print(f"{name}: fail after {attempt} attempt(s) over {max_wait_raw}s {last_error}")
            raise SystemExit(1)
        time.sleep(2)
PY
}

health_acceptance_smoke() {
  "${RUNTIME_PYTHON:-$(command -v python3)}" - "$INSTALL_ROOT" <<'PY'
import json
import sys
import time
import urllib.request

root = sys.argv[1]
sys.path.insert(0, root)
from src.port_discovery import front_door_url

required = ("p0raw", "p0watcher", "p2zhiyi", "p2sourceRef", "p3recall", "p4provider")
deadline = time.monotonic() + 240
last = {}
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(front_door_url("/api/health", root), timeout=8) as response:
            last = json.loads(response.read().decode("utf-8"))
        failed = {name: (last.get(name) or {}).get("status") for name in required if (last.get(name) or {}).get("status") != "passed"}
        if not failed:
            print("front-door semantic health: passed")
            raise SystemExit(0)
    except Exception as exc:
        last = {"error": f"{type(exc).__name__}: {exc}"}
    time.sleep(2)
print(json.dumps({"front_door_semantic_health_failed": last}, ensure_ascii=False))
raise SystemExit(1)
PY
}

capability_smoke() {
  python3 - "$INSTALL_ROOT" <<'PY'
import json
import sys
import urllib.request

sys.path.insert(0, sys.argv[1])
from src.port_discovery import front_door_url

body = {
    "jsonrpc": "2.0",
    "id": "unix-install-smoke",
    "method": "tools/call",
    "params": {
            "name": "time_library_recall",
        "arguments": {
            "query": "capability check",
            "mode": "capability_check",
            "consumer": "unix-install-smoke",
            "request_id": "unix-install-smoke-capability",
        },
    },
}
request = urllib.request.Request(
    front_door_url("/mcp", sys.argv[1]),
    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=8) as resp:
        data = json.loads(resp.read().decode("utf-8"))
except Exception as exc:
    print(f"capability_check: fail {exc}")
    raise SystemExit(1)

if data.get("error"):
    print(f"capability_check: fail {json.dumps(data['error'], ensure_ascii=False)}")
    raise SystemExit(1)

result = data.get("result") or {}
payload = result.get("structuredContent")
if not payload:
    content = result.get("content") or []
    if content:
        try:
            payload = json.loads(content[0].get("text") or "{}")
        except Exception:
            payload = None
if not payload:
    print("capability_check: fail missing structured payload")
    raise SystemExit(1)

problems = []
if payload.get("mode") != "capability_check":
    problems.append("mode")
if payload.get("service") != "raw_consumption_gateway":
    problems.append("service")
if payload.get("server") != "time-library":
    problems.append("server")
if payload.get("read_only") is not True:
    problems.append("read_only")
if payload.get("recall_performed") is not False:
    problems.append("recall_performed")
if payload.get("raw_excerpt_returned") is not False:
    problems.append("raw_excerpt_returned")
mcp_tools = set(payload.get("mcp_tools") or [])
if not mcp_tools.intersection({"time_library_recall", "zhiyi_recall"}):
    problems.append("mcp_tools")
if problems:
    print(f"capability_check: fail unexpected fields {','.join(problems)}")
    raise SystemExit(1)

print(f"capability_check: ok version {payload.get('version')}")
PY
}

run_smoke() {
  health_acceptance_smoke
  capability_smoke
}

log "Source: ${SOURCE_ROOT}"
log "Install root: ${INSTALL_ROOT}"
if [[ "$SKIP_START" == "0" ]]; then
  assert_user_service_ownership_available
fi
begin_install_transaction
if [[ "$SKIP_START" == "0" ]]; then
  stop_user_services
  stop_stale_runtime_processes
  assert_runtime_quiescent
fi
install_files
ensure_dialog_entry_token
write_config
install_python_env
if [[ "$SKIP_START" == "0" ]]; then
  install_openclaw_plugin
  install_hermes_plugin
  install_codex_skill
  install_codex_mcp
  install_claude_code_mcp
  install_claude_code_preflight_hook
  install_claude_desktop_mcp
  install_user_services
  start_user_services
else
  log "Host integrations and systemd user definitions preserved by --no-start staging mode"
  CODEX_SKILL_STATUS="skipped (--no-start)"
  CODEX_MCP_STATUS="skipped (--no-start)"
  CODEX_MCP_GUARD_STATUS="skipped (--no-start)"
  CLAUDE_CODE_MCP_STATUS="skipped (--no-start)"
  CLAUDE_CODE_HOOK_STATUS="skipped (--no-start)"
  CLAUDE_DESKTOP_STATUS="skipped (--no-start)"
fi
if [[ "$RUN_SMOKE" == "1" && "$SKIP_START" == "0" ]]; then
  run_smoke
fi

cat <<EOF

Time Library Linux full install complete.
Install root: ${INSTALL_ROOT}
Console: front-door discovery file (preferred port ${FRONT_DOOR_PORT})
Internal services: private loopback components; clients must read runtime/front_door_port
Logs: ${LOG_DIR}
OpenClaw plugin: $([[ "$SKIP_START" == "1" || "$SKIP_OPENCLAW" == "1" ]] && echo skipped || echo time-library-native)
Hermes memory provider: $([[ "$SKIP_START" == "1" || "$SKIP_HERMES" == "1" ]] && echo skipped || echo time_library)
Hermes skill: $([[ "$SKIP_START" == "1" || "$SKIP_HERMES" == "1" ]] && echo skipped || echo time-library)
Codex skill: ${CODEX_SKILL_STATUS}
Codex MCP: ${CODEX_MCP_STATUS}
Codex MCP config guard: ${CODEX_MCP_GUARD_STATUS}
Claude Code MCP: ${CLAUDE_CODE_MCP_STATUS}
Claude Code preflight hook: ${CLAUDE_CODE_HOOK_STATUS}
Claude Desktop MCP: ${CLAUDE_DESKTOP_STATUS}
EOF
commit_install_transaction
