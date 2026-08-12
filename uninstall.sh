#!/usr/bin/env bash
# ============================================================
# Time Library Uninstaller (macOS / Linux)
# Usage:
#   bash ~/Library/Application\ Support/time-library/uninstall.sh
#   ~/.local/share/time-library/uninstall.sh
#   curl -fsSL ... | sudo bash (Linux)
# ============================================================
# This removes ONLY the software and registered services.
# User data (memory/, raw/, zhiyi/, xingce/, experience_lancedb/, config/) is preserved.
set -e

info() { echo "[time-library] $*"; }
warn() { echo "[time-library WARNING] $*"; }
error() { echo "[time-library ERROR] $*" >&2; exit 1; }

OS=""
case "$(uname -s)" in
    Linux*)  OS="linux" ;;
    Darwin*) OS="darwin" ;;
    *)       error "Unsupported OS: $(uname -s)" ;;
esac

# Determine install directory. New installs use time-library; old memcore-cloud
# roots stay as legacy fallback so existing users can still uninstall safely.
INSTALL_DIR="${TIME_LIBRARY_INSTALL_DIR:-${TIME_LIBRARY_ROOT:-${INSTALL_DIR:-${MEMCORE_INSTALL_DIR:-${MEMCORE_ROOT:-}}}}}"
if [[ "$OS" == "linux" ]]; then
    NEW_LINUX_INSTALL_DIR="${HOME}/.local/share/time-library"
    LEGACY_LINUX_INSTALL_DIR="${HOME}/.local/share/memcore-cloud"
    LEGACY_OPT_INSTALL_DIR="/opt/memcore-cloud"
    if [[ -z "${INSTALL_DIR:-}" ]]; then
        if [[ -d "$NEW_LINUX_INSTALL_DIR" || ! -d "$LEGACY_LINUX_INSTALL_DIR" ]]; then
            INSTALL_DIR="$NEW_LINUX_INSTALL_DIR"
        elif [[ -d "$LEGACY_LINUX_INSTALL_DIR" ]]; then
            INSTALL_DIR="$LEGACY_LINUX_INSTALL_DIR"
        else
            INSTALL_DIR="$LEGACY_OPT_INSTALL_DIR"
        fi
    fi
else
    NEW_MAC_INSTALL_DIR="${HOME}/Library/Application Support/time-library"
    LEGACY_MAC_INSTALL_DIR="${HOME}/Library/Application Support/memcore-cloud"
    OLD_MAC_INSTALL_DIR="${HOME}/Library/Application Support/MemcoreCloud"
    if [[ -z "${INSTALL_DIR:-}" ]]; then
        if [[ -d "$NEW_MAC_INSTALL_DIR" || ( ! -d "$LEGACY_MAC_INSTALL_DIR" && ! -d "$OLD_MAC_INSTALL_DIR" ) ]]; then
            INSTALL_DIR="$NEW_MAC_INSTALL_DIR"
        elif [[ -d "$LEGACY_MAC_INSTALL_DIR" ]]; then
            INSTALL_DIR="$LEGACY_MAC_INSTALL_DIR"
        else
            INSTALL_DIR="$OLD_MAC_INSTALL_DIR"
        fi
    fi
fi

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir) INSTALL_DIR="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: ~/.local/share/time-library/uninstall.sh"
            echo "       bash ~/Library/Application\\ Support/time-library/uninstall.sh"
            echo "       curl -fsSL ... | sudo bash"
            echo "Options: --dir PATH    Installation directory"
            exit 0 ;;
        *) error "Unknown option: $1" ;;
    esac
done

echo ""
echo "=============================================="
echo " Time Library Uninstaller"
echo "=============================================="
echo ""
info "Installation directory: ${INSTALL_DIR}"
echo ""
echo "This will:"
echo "  1. Stop Time Library services"
if [[ "$OS" == "linux" ]]; then
    echo "  2. Remove Time Library systemd services"
elif [[ "$OS" == "darwin" ]]; then
    echo "  2. Remove Time Library LaunchAgents, including the menu bar icon"
fi
echo "  3. Remove software files from ${INSTALL_DIR}"
echo ""
echo "The following user data will be PRESERVED (not deleted):"
echo "  - memory/"
echo "  - raw/"
echo "  - zhiyi/"
echo "  - xingce/"
echo "  - experience_lancedb/"
echo "  - config/"
echo "  - logs/"
echo "  - backups/"
echo ""
echo "Remove software only? [Y/n]"
read -r confirm
case "$confirm" in
    [nN]*) echo "Aborted."; exit 0 ;;
esac

# ─── Stop services ────────────────────────────────────────
info "Stopping Time Library services..."
pkill -f "p6_console" 2>/dev/null || true

# ─── Stop & unregister service ────────────────────────────
if [[ "$OS" == "linux" ]]; then
    service_units=(
        time-library-p0-watcher.service
        time-library-p3-recall.service
        time-library-p4-provider.service
        time-library-p6-console.service
        time-library-raw-gateway.service
        time-library-dialog-entry.service
        time-library-codex-mcp-guard.service
        memcore-cloud-p0-watcher.service
        memcore-cloud-p3-recall.service
        memcore-cloud-p4-provider.service
        memcore-cloud-p6-console.service
        memcore-cloud-raw-gateway.service
        memcore-cloud-dialog-entry.service
        memcore-cloud-console.service
    )
    if command -v systemctl >/dev/null 2>&1; then
        if systemctl --user status >/dev/null 2>&1; then
            for unit in "${service_units[@]}"; do
                systemctl --user stop "$unit" 2>/dev/null || true
                systemctl --user disable "$unit" 2>/dev/null || true
                rm -f "${HOME}/.config/systemd/user/${unit}" 2>/dev/null || true
            done
            systemctl --user daemon-reload 2>/dev/null || true
        fi
        for unit in "${service_units[@]}"; do
            systemctl stop "$unit" 2>/dev/null || true
            systemctl disable "$unit" 2>/dev/null || true
            rm -f "/etc/systemd/system/${unit}" 2>/dev/null || true
        done
        systemctl daemon-reload 2>/dev/null || true
    fi
elif [[ "$OS" == "darwin" ]]; then
    labels=(
        com.memcorecloud.p0-watcher
        com.memcorecloud.p3-recall
        com.memcorecloud.p4-provider
        com.memcorecloud.p6-console
        com.memcorecloud.raw-gateway
        com.memcorecloud.dialog-entry
        com.memcorecloud.codex-mcp-guard
        com.memcorecloud.menu-bar
        com.memcorecloud.console
        ai.memcore.memcore-cloud
    )
    for label in "${labels[@]}"; do
        PLIST_PATH="${HOME}/Library/LaunchAgents/${label}.plist"
        if launchctl print "gui/$(id -u)/${label}" &>/dev/null 2>&1; then
            info "Unloading LaunchAgent: ${label}"
            launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || \
            launchctl unload "$PLIST_PATH" 2>/dev/null || true
        fi
        if [[ -f "$PLIST_PATH" ]]; then
            info "Removing LaunchAgent plist: ${label}"
            rm -f "$PLIST_PATH"
        fi
    done
fi

# ─── Remove software (preserve user data) ─────────────────
if [[ -d "$INSTALL_DIR" ]]; then
    info "Removing software from ${INSTALL_DIR} (preserving user data)..."
    # Remove files and dirs that are part of the software, not user data
    for item in src web tools scripts docs packaging system tests runtime config/default_*.json \
                .venv VERSION README.md README.zh-CN.md LICENSE CHANGELOG.md \
                install.sh uninstall.sh requirements.txt requirements-core.txt \
                requirements-vector.txt requirements-dev.txt *.py \
                PACKAGING.md CURRENT_BASELINE.md CURRENT_STATE.md "AGENTS"".md" \
                update_staging; do
        rm -rf "${INSTALL_DIR:?}/${item}" 2>/dev/null || true
    done
    # Remove configs that can be regenerated (keep memcore.json -- user config)
    for f in alias_map.json model_config.json feature_flags.json \
             window_binding_registry.json init_state.json; do
        rm -f "${INSTALL_DIR}/config/${f}" 2>/dev/null || true
    done
    info "Software has been removed."
else
    warn "Installation directory does not exist: ${INSTALL_DIR}"
fi

echo ""
echo "=============================================="
echo " Uninstallation complete!"
echo "=============================================="
echo ""
echo "Software removed. Your data has been preserved at:"
echo "  ${INSTALL_DIR}/memory/"
echo "  ${INSTALL_DIR}/zhiyi/"
echo "  ${INSTALL_DIR}/experience_lancedb/"
echo "  ${INSTALL_DIR}/config/"
echo "  ${INSTALL_DIR}/logs/"
echo ""
echo "To fully remove all data including user data, run:"
echo "  rm -rf '${INSTALL_DIR}'"
echo ""
