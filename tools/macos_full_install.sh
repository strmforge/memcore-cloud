#!/usr/bin/env bash
# macOS user-level full installer for Time Library.
#
# This installs from the current folder into the user's Application Support
# directory, starts local background services, and connects OpenClaw and Hermes
# when they are available.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LEGACY_INSTALL_ROOT="${HOME}/Library/Application Support/memcore-cloud"
DEFAULT_INSTALL_ROOT="${HOME}/Library/Application Support/time-library"
INSTALL_ROOT="${INSTALL_ROOT:-${DEFAULT_INSTALL_ROOT}}"
LAUNCH_AGENT_DIR="${HOME}/Library/LaunchAgents"
LOG_DIR="${HOME}/Library/Logs/time-library"
STATE_DIR="${HOME}/Library/Application Support/time-library-state"
OPENCLAW_CONFIG="${OPENCLAW_CONFIG:-${HOME}/.openclaw/openclaw.json}"
HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
HERMES_AGENT_DIR="${HERMES_AGENT_DIR:-${HERMES_HOME}/hermes-agent}"
REINSTALL=0
RESET_INSTALL=0
PRESERVE_DATA=1
SKIP_OPENCLAW=0
SKIP_HERMES=0
SKIP_CODEX=0
SKIP_CLAUDE_DESKTOP=0
SKIP_START=0
RUN_SMOKE=1
CODEX_SKILL_STATUS="pending"
CODEX_MCP_STATUS="pending"
CODEX_MCP_GUARD_STATUS="pending"
CLAUDE_CODE_MCP_STATUS="pending"
CLAUDE_CODE_HOOK_STATUS="pending"
CLAUDE_DESKTOP_STATUS="pending"
MENU_BAR_STATUS="pending"
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
Usage: bash tools/macos_full_install.sh [options]

Options:
  --install-root PATH     Install root. Default: ~/Library/Application Support/time-library
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

log() { printf '[time-library-macos-install] %s\n' "$*"; }
warn() { printf '[time-library-macos-install WARNING] %s\n' "$*" >&2; }
die() { printf '[time-library-macos-install ERROR] %s\n' "$*" >&2; exit 1; }

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
if [[ "$(uname -s)" != "Darwin" ]]; then
  die "This installer is macOS-only. Use the platform-specific installer on other systems."
fi

command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v rsync >/dev/null 2>&1 || die "rsync not found"

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
    "${HOME}/Library/Application Support/OpenAI/Codex/chrome-native-hosts-v2.json"
    "${HOME}/Library/Application Support/OpenAI/Codex/chrome-native-hosts.json"
    "${HOME}/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.openai.codexextension.json"
  )
  python3 - "${candidates[@]}" <<'PY'
import json
import sys
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
    "$from/" "$to/"
}

transaction_launchagent_labels() {
  printf '%s\n' \
    com.memcorecloud.p0-watcher \
    com.memcorecloud.p3-recall \
    com.memcorecloud.p4-provider \
    com.memcorecloud.p6-console \
    com.memcorecloud.raw-gateway \
    com.memcorecloud.dialog-entry \
    com.memcorecloud.front-door \
    com.memcorecloud.codex-mcp-guard \
    com.memcorecloud.menu-bar \
    ai.memcore.memcore-cloud
}

begin_install_transaction() {
  if [[ -e "$INSTALL_ROOT" || -L "$INSTALL_ROOT" ]] && [[ ! -d "$INSTALL_ROOT" || -L "$INSTALL_ROOT" ]]; then
    die "Install root exists but is not a real directory: ${INSTALL_ROOT}"
  fi
  INSTALL_TRANSACTION_DIR="$(mktemp -d "${TMPDIR:-/tmp}/time-library-install-transaction.XXXXXX")"
  chmod 700 "$INSTALL_TRANSACTION_DIR"
  [[ -d "$INSTALL_ROOT" ]] && INSTALL_ROOT_EXISTED_BEFORE=1
  local snapshot_args=()
  local label
  while IFS= read -r label; do
    snapshot_args+=(--path "${LAUNCH_AGENT_DIR}/${label}.plist")
  done < <(transaction_launchagent_labels)
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
    --path "${CLAUDE_DESKTOP_HOME:-${HOME}/Library/Application Support/Claude}/claude_desktop_config.json"
    --path "${HOME}/.claude/skills/time-library"
    --path "${HOME}/Library/Application Support/Claude/claude_desktop_config.json"
    --path "${CLAUDE_DESKTOP_HOME:-${HOME}/Library/Application Support/Claude}/local-agent-mode-sessions/skills-plugin"
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
  : > "${INSTALL_TRANSACTION_DIR}/active-labels.txt"
  if [[ "$SKIP_START" == "0" ]]; then
    while IFS= read -r label; do
      if launchctl print "gui/${UID}/${label}" >/dev/null 2>&1; then
        printf '%s\n' "$label" >> "${INSTALL_TRANSACTION_DIR}/active-labels.txt"
      fi
    done < <(transaction_launchagent_labels)
  fi
  INSTALL_TRANSACTION_ARMED=1
  trap 'finish_install_transaction $?' EXIT
}

rollback_install_transaction() {
  local rollback_failed=0
  set +e
  local label plist
  if [[ "$SKIP_START" == "0" ]]; then
    while IFS= read -r label; do
      launchctl bootout "gui/${UID}/${label}" >/dev/null 2>&1 || rollback_failed=1
      launchctl remove "$label" >/dev/null 2>&1 || rollback_failed=1
    done < <(transaction_launchagent_labels)
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
    while IFS= read -r label; do
      [[ -n "$label" ]] || continue
      plist="${LAUNCH_AGENT_DIR}/${label}.plist"
      [[ -f "$plist" ]] || continue
      if ! launchctl bootstrap "gui/${UID}" "$plist" >/dev/null 2>&1 &&
        ! launchctl load -w "$plist" >/dev/null 2>&1; then
        rollback_failed=1
      fi
      launchctl kickstart -k "gui/${UID}/${label}" >/dev/null 2>&1 || rollback_failed=1
    done < "${INSTALL_TRANSACTION_DIR}/active-labels.txt"
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

launchagent_is_present() {
  local label="$1"
  launchctl print "gui/${UID}/${label}" >/dev/null 2>&1 && return 0
  [[ -f "${LAUNCH_AGENT_DIR}/${label}.plist" ]]
}

launchagent_targets_install_root() {
  local label="$1"
  local plist="${LAUNCH_AGENT_DIR}/${label}.plist"
  local allowed_roots=("$INSTALL_ROOT")
  if [[ "$INSTALL_ROOT" == "$DEFAULT_INSTALL_ROOT" ]]; then
    allowed_roots+=("$LEGACY_INSTALL_ROOT")
  fi
  local identity_args=()
  local allowed_root
  for allowed_root in "${allowed_roots[@]}"; do
    identity_args+=(--root "$allowed_root")
  done
  local loaded=""
  loaded="$(launchctl print "gui/${UID}/${label}" 2>/dev/null || true)"
  if [[ -n "$loaded" ]]; then
    printf '%s\n' "$loaded" | python3 "${SOURCE_ROOT}/tools/install_runtime_identity.py" \
      launchctl "${identity_args[@]}"
    return $?
  fi
  if [[ -f "$plist" ]] && python3 "${SOURCE_ROOT}/tools/install_runtime_identity.py" \
    plist --path "$plist" "${identity_args[@]}"; then
    return 0
  fi
  return 1
}

assert_launchagent_ownership_available() {
  [[ "$SKIP_START" == "0" ]] || return 0
  local label
  for label in "$@"; do
    if launchagent_is_present "$label" && ! launchagent_targets_install_root "$label"; then
      die "LaunchAgent ${label} belongs to another Time Library install root; use --no-start or stop that installation explicitly"
    fi
  done
}

stop_old_launchagents() {
  if [[ "$SKIP_START" != "0" ]]; then
    log "Service stop skipped because --no-start preserves the current runtime"
    return 0
  fi
  local labels=(
    com.memcorecloud.p0-watcher
    com.memcorecloud.p3-recall
    com.memcorecloud.p4-provider
    com.memcorecloud.p6-console
    com.memcorecloud.raw-gateway
    com.memcorecloud.dialog-entry
    com.memcorecloud.front-door
    com.memcorecloud.codex-mcp-guard
    com.memcorecloud.menu-bar
    ai.memcore.memcore-cloud
  )
  for label in "${labels[@]}"; do
    if ! launchagent_targets_install_root "$label"; then
      continue
    fi
    launchctl bootout "gui/${UID}/${label}" >/dev/null 2>&1 || true
    launchctl remove "$label" >/dev/null 2>&1 || true
  done
  # launchd bootout does not always reap an older detached copy. Terminate only
  # known Time Library entrypoints under this install root; never use a broad
  # process-name kill because the host may run unrelated Python services.
  local process_roots=("$INSTALL_ROOT")
  if [[ "$INSTALL_ROOT" == "$DEFAULT_INSTALL_ROOT" ]]; then
    process_roots+=("$LEGACY_INSTALL_ROOT")
  fi
  python3 - "$SOURCE_ROOT" "${process_roots[@]}" <<'PY'
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, sys.argv[1])
from tools.install_runtime_identity import macos_ps_command_targets_install_roots

roots = sys.argv[2:]
rows = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True).splitlines()
targets = []
for row in rows:
    raw_pid, _, command = row.strip().partition(" ")
    try:
        pid = int(raw_pid)
    except ValueError:
        continue
    if pid == os.getpid():
        continue
    if macos_ps_command_targets_install_roots(command, roots):
        targets.append((pid, command))
for pid, _command in targets:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
time.sleep(0.4)
for pid, command in targets:
    try:
        current = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True).strip()
    except subprocess.CalledProcessError:
        continue
    if macos_ps_command_targets_install_roots(current, roots):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
PY
}

assert_runtime_quiescent() {
  local root_args=(--root "$INSTALL_ROOT")
  if [[ "$INSTALL_ROOT" == "$DEFAULT_INSTALL_ROOT" ]]; then
    root_args+=(--root "$LEGACY_INSTALL_ROOT")
  fi
  python3 "${SOURCE_ROOT}/tools/install_runtime_quiescence.py" "${root_args[@]}"
}

install_files() {
  mkdir -p "$(dirname "$INSTALL_ROOT")" "$LOG_DIR" "$STATE_DIR"
  local backup=""
  local migrated_legacy=0
  if [[ "$INSTALL_ROOT" == "$DEFAULT_INSTALL_ROOT" && ! -d "$INSTALL_ROOT" && -d "$LEGACY_INSTALL_ROOT" ]]; then
    mkdir -p "$INSTALL_ROOT"
    copy_runtime_data "$LEGACY_INSTALL_ROOT" "$INSTALL_ROOT"
    migrated_legacy=1
  fi
  if [[ -d "$INSTALL_ROOT" && "$REINSTALL" == "1" && "$migrated_legacy" == "0" ]]; then
    backup="${INSTALL_ROOT}.backup.$(date +%Y%m%d%H%M%S)"
    log "Backing up existing install to ${backup}"
    if [[ "$RESET_INSTALL" == "1" ]]; then
      rsync -a "$INSTALL_ROOT/" "$backup/"
      rm -rf "$INSTALL_ROOT"
      mkdir -p "$INSTALL_ROOT"
      if [[ "$PRESERVE_DATA" == "1" ]]; then
        copy_runtime_data "$backup" "$INSTALL_ROOT"
      fi
    else
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
    "${SOURCE_ROOT}/" "${INSTALL_ROOT}/"
  rm -rf -- "${INSTALL_ROOT}/.playwright-cli"
  merge_packaged_config
  migrate_legacy_state_paths
}

write_config() {
  mkdir -p "${INSTALL_ROOT}/config" "${INSTALL_ROOT}/logs" "${INSTALL_ROOT}/memory" \
    "${INSTALL_ROOT}/zhiyi/case_memory" "${INSTALL_ROOT}/zhiyi/error_memory" \
    "${INSTALL_ROOT}/zhiyi/preference_memory" "${INSTALL_ROOT}/experience_lancedb" \
    "${INSTALL_ROOT}/backups" "${INSTALL_ROOT}/output"

  if [[ ! -f "${INSTALL_ROOT}/config/model_config.json" && -f "${INSTALL_ROOT}/config/default_model_config.json" ]]; then
    cp "${INSTALL_ROOT}/config/default_model_config.json" "${INSTALL_ROOT}/config/model_config.json"
  fi
  if [[ ! -f "${INSTALL_ROOT}/config/feature_flags.json" && -f "${INSTALL_ROOT}/config/default_feature_flags.json" ]]; then
    cp "${INSTALL_ROOT}/config/default_feature_flags.json" "${INSTALL_ROOT}/config/feature_flags.json"
  fi
  if [[ ! -f "${INSTALL_ROOT}/config/alias_map.json" && -f "${INSTALL_ROOT}/config/default_alias_map.json" ]]; then
    cp "${INSTALL_ROOT}/config/default_alias_map.json" "${INSTALL_ROOT}/config/alias_map.json"
  fi
  if [[ ! -f "${INSTALL_ROOT}/config/window_binding_registry.json" && -f "${INSTALL_ROOT}/config/default_window_binding_registry.json" ]]; then
    cp "${INSTALL_ROOT}/config/default_window_binding_registry.json" "${INSTALL_ROOT}/config/window_binding_registry.json"
  fi

  python3 - "$INSTALL_ROOT" "$DIALOG_ENTRY_HOST" "$DIALOG_ENTRY_ENDPOINT_URL" "$FRONT_DOOR_PORT" "$INTERNAL_P3_PORT" "$INTERNAL_P4_PORT" "$INTERNAL_P6_PORT" "$INTERNAL_RAW_PORT" "$INTERNAL_DIALOG_PORT" <<'PY'
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

root = Path(sys.argv[1])
dialog_entry_host = sys.argv[2]
dialog_entry_endpoint_url = sys.argv[3]
front_door_port = int(sys.argv[4])
internal_ports = {
    "p3": int(sys.argv[5]),
    "p4": int(sys.argv[6]),
    "p6": int(sys.argv[7]),
    "raw": int(sys.argv[8]),
    "dialog": int(sys.argv[9]),
}
cfg_path = root / "config" / "memcore.json"
cfg = {}
if cfg_path.exists():
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except Exception:
        cfg = {}
cfg.setdefault("_comment", "Time Library user-level macOS config")
cfg["_base_dir"] = str(root)
cfg["version"] = str(cfg.get("version") or "1.0.0")
paths = cfg.setdefault("paths", {})
paths.update({
    "memory": "memory",
    "openclaw_agents": "${OPENCLAW_AGENTS_DIR:-~/.openclaw/agents}",
    "openclaw_workspace": "${OPENCLAW_WORKSPACE_DIR:-~/.openclaw/workspace}",
    "zhiyi": "zhiyi",
    "config_dir": "config",
    "experience_lancedb": "experience_lancedb",
    "checkpoint": ".checkpoint",
    "alias_map": "config/alias_map.json",
    "model_config": "config/model_config.json",
    "lancedb_v2_metadata": "config/lancedb_v2_metadata.json",
    "logs": "logs",
})
cfg["nodes"] = {
    "current": os.uname().nodename.split(".")[0] or "local-macos",
    "raw_memory_subpath": f"{os.uname().nodename.split('.')[0] or 'local-macos'}/openclaw/openclaw_session_jsonl",
}
services = cfg.setdefault("services", {})
services.update({
    "p0_watcher_enabled": True,
    "p0_watcher_resource_profile": services.get("p0_watcher_resource_profile") or "light",
    "p0_watcher_source_default": "all",
    "p0_watcher_interval_milliseconds": int(services.get("p0_watcher_interval_milliseconds") or 5000),
    "front_door_port": front_door_port,
    "internal_p3_port": internal_ports["p3"],
    "internal_p4_port": internal_ports["p4"],
    "internal_p6_port": internal_ports["p6"],
    "internal_raw_port": internal_ports["raw"],
    "internal_dialog_port": internal_ports["dialog"],
    "dialog_entry_host": dialog_entry_host,
    "dialog_entry_endpoint_url": dialog_entry_endpoint_url,
    "dialog_entry_lan_requires_token": True,
})
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
model_call = cfg.setdefault("integrations", {}).setdefault("hermes", {}).setdefault("model_call", {})
if not model_call.get("hermes_provider") and not model_call.get("provider"):
    hermes = shutil.which("hermes")
    if hermes:
        try:
            auth_list = subprocess.run(
                [hermes, "auth", "list"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if "custom:minimax" in (auth_list.stdout or ""):
                model_call["hermes_provider"] = "custom:minimax"
                model_call.setdefault("hermes_model", "minimax-m2.7")
                model_call.setdefault("source", "memcore-time_library")
        except Exception:
            pass
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

model_cfg_path = root / "config" / "model_config.json"
model_cfg = {}
if model_cfg_path.exists():
    try:
        model_cfg = json.loads(model_cfg_path.read_text(encoding="utf-8-sig"))
    except Exception:
        model_cfg = {}
model_cfg.setdefault("version", "1.0")
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
        "source": "macos_full_install",
        "changed_keys": changed_keys,
        "feature_flags_path": str(flags_path),
        "backup_path": str(backup_path) if backup_path else None,
        "note": "Safety migration after OpenClaw direct-answer boundary fix; explicit opt-in must be re-enabled intentionally after install.",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with receipt_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(receipt, ensure_ascii=False) + "\n")

current_node = cfg.get("nodes", {}).get("current") or (os.uname().nodename.split(".")[0] or "local-macos")

def normalize_zhiyi_node_refs():
    zhiyi_root = root / "zhiyi"
    changed_files = []
    for subtype in ("preference_memory", "case_memory", "error_memory"):
        path = zhiyi_root / subtype / f"{subtype}.jsonl"
        if not path.exists():
            continue
        changed = False
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                out.append(line)
                continue
            sr_raw = rec.get("source_refs")
            try:
                sr = json.loads(sr_raw) if isinstance(sr_raw, str) else (sr_raw if isinstance(sr_raw, dict) else {})
            except Exception:
                sr = {}
            source_path = str(sr.get("source_path") or "")
            normalized_source_path = source_path.replace("\\", "/")
            if (
                f"/memory/openclaw/{current_node}/" in normalized_source_path
                or f"/memory/{current_node}/openclaw/openclaw_session_jsonl/" in normalized_source_path
            ):
                if rec.get("computer_id") != current_node:
                    rec["computer_id"] = current_node
                    changed = True
                if sr.get("computer_name") != current_node:
                    sr["computer_name"] = current_node
                    rec["source_refs"] = json.dumps(sr, ensure_ascii=False)
                    changed = True
            out.append(json.dumps(rec, ensure_ascii=False) if changed else line)
        if changed:
            path.write_text("\n".join(out) + "\n", encoding="utf-8")
            changed_files.append(str(path))
    if changed_files:
        print("normalized zhiyi node refs:", ", ".join(changed_files))

normalize_zhiyi_node_refs()
PY
}

install_python_env() {
  log "Preparing Python venv"
  local build_root="${INSTALL_ROOT}/.venv-build.$RANDOM"
  RUNTIME_VENV_BUILD="$build_root"
  rm -rf "$build_root"
  python3 -m venv "$build_root"
  "${build_root}/bin/python" -m pip install --upgrade pip >/dev/null
  if [[ -f "${INSTALL_ROOT}/requirements-core.txt" ]]; then
    "${build_root}/bin/python" -m pip install -r "${INSTALL_ROOT}/requirements-core.txt"
  fi
  "${build_root}/bin/python" - <<'PY'
import importlib.util
missing = [name for name in ("cryptography", "yaml") if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit("missing python packages: " + ", ".join(missing))
PY
  if [[ -d "${INSTALL_ROOT}/.venv" ]]; then
    RUNTIME_VENV_BACKUP="${INSTALL_TRANSACTION_DIR}/old-venv"
    mv "${INSTALL_ROOT}/.venv" "$RUNTIME_VENV_BACKUP"
  fi
  mv "$build_root" "${INSTALL_ROOT}/.venv"
  RUNTIME_VENV_BUILD=""
}

write_launch_agent() {
  local label="$1"
  local log_name="$2"
  shift 2
  local plist="${LAUNCH_AGENT_DIR}/${label}.plist"
  mkdir -p "$LAUNCH_AGENT_DIR" "$LOG_DIR"
  python3 - "$plist" "$label" "$INSTALL_ROOT" "$LOG_DIR" "$log_name" "$DIALOG_ENTRY_HOST" "$DIALOG_ENTRY_TOKEN" "$@" <<'PY'
import plistlib
import sys
from pathlib import Path

plist_path = Path(sys.argv[1])
label = sys.argv[2]
install_root = sys.argv[3]
log_dir = sys.argv[4]
log_name = sys.argv[5]
dialog_entry_host = sys.argv[6]
dialog_entry_token = sys.argv[7]
args = sys.argv[8:]
env = {
    "TIME_LIBRARY_ROOT": install_root,
    "TIME_LIBRARY_INSTALL_ROOT": install_root,
    "MEMCORE_ROOT": install_root,
    "MEMCORE_INSTALL_ROOT": install_root,
    "PYTHONPATH": install_root,
    "PYTHONIOENCODING": "utf-8",
    "MEMCORE_HERMES_CLI": str(Path.home() / ".local" / "bin" / "hermes"),
    "MEMCORE_DIALOG_ENTRY_HOST": dialog_entry_host,
}
if dialog_entry_token and log_name == "dialog-entry":
    env["MEMCORE_DIALOG_ENTRY_TOKEN"] = dialog_entry_token
data = {
    "Label": label,
    "ProgramArguments": args,
    "WorkingDirectory": install_root,
    "EnvironmentVariables": env,
    "RunAtLoad": True,
    "KeepAlive": {"SuccessfulExit": False},
    "StandardOutPath": str(Path(log_dir) / f"{log_name}.out.log"),
    "StandardErrorPath": str(Path(log_dir) / f"{log_name}.err.log"),
}
if label == "com.memcorecloud.p3-recall":
    data["ProcessType"] = "Interactive"
else:
    data["ProcessType"] = "Background"
    data["LowPriorityIO"] = True
plist_path.write_bytes(plistlib.dumps(data, sort_keys=False))
PY
  plutil -lint "$plist" >/dev/null
}

build_menu_bar_helper() {
  local src="${INSTALL_ROOT}/tools/macos_menu_bar.swift"
  local out="${INSTALL_ROOT}/runtime/memcore-menu-bar"
  local build_log="${LOG_DIR}/menu-bar-build.err.log"
  local swiftc_candidates=()
  if command -v swiftc >/dev/null 2>&1; then
    swiftc_candidates+=("$(command -v swiftc)")
  fi
  if [[ -x "/usr/bin/swiftc" ]]; then
    swiftc_candidates+=("/usr/bin/swiftc")
  fi
  if command -v xcrun >/dev/null 2>&1; then
    local xcrun_swiftc
    xcrun_swiftc="$(xcrun --find swiftc 2>/dev/null || true)"
    if [[ -n "$xcrun_swiftc" ]]; then
      swiftc_candidates+=("$xcrun_swiftc")
    fi
  fi
  if [[ "${#swiftc_candidates[@]}" -eq 0 ]]; then
    warn "swiftc not found; macOS menu bar icon will not be installed"
    return 1
  fi
  if [[ ! -f "$src" ]]; then
    warn "macOS menu bar source not found: ${src}"
    return 1
  fi
  mkdir -p "${INSTALL_ROOT}/runtime" "$LOG_DIR"
  rm -f "$out"
  : > "$build_log"
  local swiftc_bin
  local tried=()
  for swiftc_bin in "${swiftc_candidates[@]}"; do
    local already_tried=0
    local tried_bin
    for tried_bin in "${tried[@]:-}"; do
      if [[ "$tried_bin" == "$swiftc_bin" ]]; then
        already_tried=1
        break
      fi
    done
    if [[ "$already_tried" == "1" ]]; then
      continue
    fi
    tried+=("$swiftc_bin")
    {
      printf 'compiler: %s\n' "$swiftc_bin"
      "$swiftc_bin" -framework AppKit "$src" -o "$out"
    } >>"$build_log" 2>&1 && break
    rm -f "$out"
  done
  if [[ ! -x "$out" ]]; then
    warn "macOS menu bar helper failed to build; see ${build_log}"
    return 1
  fi
  chmod +x "$out"
}

write_menu_bar_launch_agent() {
  local binary="${INSTALL_ROOT}/runtime/memcore-menu-bar"
  [[ -x "$binary" ]] || return 1
  local label="com.memcorecloud.menu-bar"
  local log_name="menu-bar"
  local plist="${LAUNCH_AGENT_DIR}/${label}.plist"
  mkdir -p "$LAUNCH_AGENT_DIR" "$LOG_DIR"
  python3 - "$plist" "$label" "$INSTALL_ROOT" "$LOG_DIR" "$log_name" "$binary" "$INSTALL_ROOT" <<'PY'
import plistlib
import sys
from pathlib import Path

plist_path = Path(sys.argv[1])
label = sys.argv[2]
install_root = sys.argv[3]
log_dir = sys.argv[4]
log_name = sys.argv[5]
binary = sys.argv[6]
args = sys.argv[6:]
env = {
    "TIME_LIBRARY_ROOT": install_root,
    "TIME_LIBRARY_INSTALL_ROOT": install_root,
    "MEMCORE_ROOT": install_root,
    "MEMCORE_INSTALL_ROOT": install_root,
}
data = {
    "Label": label,
    "ProgramArguments": args,
    "WorkingDirectory": install_root,
    "EnvironmentVariables": env,
    "RunAtLoad": True,
    "KeepAlive": {"SuccessfulExit": False},
    "ProcessType": "Interactive",
    "StandardOutPath": str(Path(log_dir) / f"{log_name}.out.log"),
    "StandardErrorPath": str(Path(log_dir) / f"{log_name}.err.log"),
}
plist_path.write_bytes(plistlib.dumps(data, sort_keys=False))
PY
  plutil -lint "$plist" >/dev/null
}

install_launchagents() {
  local py="${INSTALL_ROOT}/.venv/bin/python"
  write_launch_agent com.memcorecloud.p0-watcher p0-watcher \
    "$py" "${INSTALL_ROOT}/src/memcore-cloud.py" --watch --source all
  write_launch_agent com.memcorecloud.p3-recall p3-recall \
    "$py" "${INSTALL_ROOT}/src/p3_recall.py" serve --port "$INTERNAL_P3_PORT"
  write_launch_agent com.memcorecloud.p4-provider p4-provider \
    "$py" "${INSTALL_ROOT}/src/p4_provider.py" --port "$INTERNAL_P4_PORT"
  write_launch_agent com.memcorecloud.p6-console p6-console \
    "$py" "${INSTALL_ROOT}/src/p6_console.py" --host 127.0.0.1 --port "$INTERNAL_P6_PORT"
  write_launch_agent com.memcorecloud.raw-gateway raw-gateway \
    "$py" "${INSTALL_ROOT}/src/raw_consumption_gateway.py" --port "$INTERNAL_RAW_PORT"
  write_launch_agent com.memcorecloud.dialog-entry dialog-entry \
    "$py" "${INSTALL_ROOT}/src/dialog_entry_proxy.py" --host 127.0.0.1 --port "$INTERNAL_DIALOG_PORT"
  write_launch_agent com.memcorecloud.front-door front-door \
    "$py" "${INSTALL_ROOT}/src/single_port_runtime.py" --host 127.0.0.1 --preferred-port "$FRONT_DOOR_PORT"
  install_codex_mcp_guard_launchagent
  if build_menu_bar_helper; then
    if write_menu_bar_launch_agent; then
      MENU_BAR_STATUS="installed"
    else
      MENU_BAR_STATUS="not_installed"
      warn "macOS menu bar LaunchAgent was not installed"
    fi
  else
    MENU_BAR_STATUS="not_installed"
    rm -f "${LAUNCH_AGENT_DIR}/com.memcorecloud.menu-bar.plist"
  fi
}

start_launchagents() {
  local labels=(
    com.memcorecloud.p0-watcher
    com.memcorecloud.p3-recall
    com.memcorecloud.p4-provider
    com.memcorecloud.p6-console
    com.memcorecloud.raw-gateway
    com.memcorecloud.dialog-entry
    com.memcorecloud.front-door
    com.memcorecloud.codex-mcp-guard
    com.memcorecloud.menu-bar
  )
  for label in "${labels[@]}"; do
    local plist="${LAUNCH_AGENT_DIR}/${label}.plist"
    [[ -f "$plist" ]] || continue
    launchctl bootstrap "gui/${UID}" "$plist" >/dev/null 2>&1 || launchctl load -w "$plist" >/dev/null 2>&1 || true
    launchctl kickstart -k "gui/${UID}/${label}" >/dev/null 2>&1 || true
  done
}

install_openclaw_plugin() {
  [[ "$SKIP_OPENCLAW" == "1" ]] && return
  local plugin_src="${INSTALL_ROOT}/system/openclaw/plugins/time-library-native"
  [[ -d "$plugin_src" ]] || { warn "OpenClaw plugin source not found: ${plugin_src}"; return; }
  if command -v openclaw >/dev/null 2>&1; then
    openclaw plugins install --link "$plugin_src" >/dev/null 2>&1 || true
    openclaw plugins registry --refresh >/dev/null 2>&1 || true
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
backup = cfg_path.with_name(cfg_path.name + f".time_library-bak.{time.strftime('%Y%m%d%H%M%S')}")
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
print(str(backup))
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

  "${INSTALL_ROOT}/.venv/bin/python" - "$HERMES_HOME" <<'PY'
import json
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
backup = None
try:
    import yaml
except Exception:
    yaml = None

if yaml:
    cfg = {}
    if cfg_path.exists():
        backup = cfg_path.with_name(cfg_path.name + f".time_library-bak.{time.strftime('%Y%m%d%H%M%S')}")
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
print(str(backup) if backup else "")
PY

  if [[ -x "${HERMES_HOME}/hermes-agent/venv/bin/python" ]]; then
    "${HERMES_HOME}/hermes-agent/venv/bin/python" - <<'PY' || true
import os
import sys
from pathlib import Path
home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()
agent = home / "hermes-agent"
sys.path.insert(0, str(agent))
from plugins.memory import load_memory_provider
p = load_memory_provider("time_library")
raise SystemExit(0 if p and p.is_available() else 1)
PY
  fi
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

install_codex_mcp_guard_launchagent() {
  if [[ "$CODEX_MCP_GUARD_STATUS" != "installed" ]]; then
    # A failed or skipped registration must not remove an already working
    # guard.  The install transaction can roll back a failed upgrade; on a
    # successful upgrade, keeping the owned plist preserves protection while
    # the host configuration is repaired separately.
    log "Codex MCP config guard unchanged: ${CODEX_MCP_GUARD_STATUS}"
    return 0
  fi
  local py="${RUNTIME_PYTHON:-${INSTALL_ROOT}/.venv/bin/python}"
  local config_path="${CODEX_HOME:-${HOME}/.codex}/config.toml"
  local guard="${INSTALL_ROOT}/tools/codex_mcp_config_guard.py"
  write_launch_agent com.memcorecloud.codex-mcp-guard codex-mcp-guard \
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
  local result
  result="$(python3 "$hook_helper" \
    --settings-path "$settings_path" \
    --hook-script "$hook_script" \
    --python "$(command -v python3)" \
    --json 2>/dev/null || true)"
  local status
  status="$(HOOK_RESULT="$result" python3 - <<'PY'
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
  local py="${INSTALL_ROOT}/.venv/bin/python"
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
  local claude_home="${CLAUDE_DESKTOP_HOME:-${HOME}/Library/Application Support/Claude}"
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
  python3 "${INSTALL_ROOT}/tools/refresh_claude_desktop_mcp_bridges.py" \
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
  python3 - "$INSTALL_ROOT" <<'PY'
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
SERVICE_LABELS=(
  com.memcorecloud.p0-watcher
  com.memcorecloud.p3-recall
  com.memcorecloud.p4-provider
  com.memcorecloud.p6-console
  com.memcorecloud.raw-gateway
  com.memcorecloud.dialog-entry
  com.memcorecloud.front-door
  com.memcorecloud.codex-mcp-guard
  com.memcorecloud.menu-bar
  ai.memcore.memcore-cloud
)
if [[ "$SKIP_START" == "0" ]]; then
  assert_launchagent_ownership_available "${SERVICE_LABELS[@]}"
fi
begin_install_transaction
if [[ "$SKIP_START" == "0" ]]; then
  stop_old_launchagents
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
  install_launchagents
  start_launchagents
else
  log "Host integrations and LaunchAgent definitions preserved by --no-start staging mode"
  CODEX_SKILL_STATUS="skipped (--no-start)"
  CODEX_MCP_STATUS="skipped (--no-start)"
  CODEX_MCP_GUARD_STATUS="skipped (--no-start)"
  CLAUDE_CODE_MCP_STATUS="skipped (--no-start)"
  CLAUDE_CODE_HOOK_STATUS="skipped (--no-start)"
  CLAUDE_DESKTOP_STATUS="skipped (--no-start)"
  MENU_BAR_STATUS="skipped (--no-start)"
fi
if [[ "$RUN_SMOKE" == "1" && "$SKIP_START" == "0" ]]; then
  run_smoke
fi

cat <<EOF

Time Library macOS full install complete.
Install root: ${INSTALL_ROOT}
Console: front-door discovery file (preferred port ${FRONT_DOOR_PORT})
Internal services: private loopback components; clients must read runtime/front_door_port
Menu bar: ${MENU_BAR_STATUS}
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
