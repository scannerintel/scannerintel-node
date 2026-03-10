#!/bin/bash
set -e

REPO="https://raw.githubusercontent.com/scannerintel/scannerintel-node/main"
INSTALL_DIR="/opt/scannerintel-node"
LOG="/tmp/scannerintel-update.log"

> "$LOG"

spinner() {
    local pid=$!
    local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local i=0
    while kill -0 "$pid" 2>/dev/null; do
        printf "\r  ${spin:$i:1}  %s" "$1"
        i=$(( (i+1) % 10 ))
        sleep 0.1
    done
    wait "$pid"
    local exit_code=$?
    if [ $exit_code -eq 0 ]; then
        printf "\r  ✓  %s\n" "$1"
    else
        printf "\r  ✗  %s FAILED\n" "$1"
        echo ""
        tail -20 "$LOG" | sed 's/^/  /'
        echo ""
        echo "  Full log: $LOG"
        exit 1
    fi
}

echo ""
echo "╔═══════════════════════════════════════╗"
echo "║    ScannerIntel Node Updater          ║"
echo "╚═══════════════════════════════════════╝"
echo ""

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "  ✗  Please run as root: sudo bash update.sh"
    exit 1
fi

# Read current version before updating
OLD_VERSION="unknown"
if [ -f "$INSTALL_DIR/main.py" ]; then
    OLD_VERSION=$(grep -oP "Node v\K[0-9.]+" "$INSTALL_DIR/main.py" 2>/dev/null || echo "unknown")
fi

# Download node files
(
    for f in main.py uploader.py streamer.py calibrate.py config.py logger.py; do
        curl -sSL "$REPO/node/$f" -o "$INSTALL_DIR/$f" >> "$LOG" 2>&1
    done
) &
spinner "Downloading latest node files..."

# Download root files
(
    curl -sSL "$REPO/install.sh" -o "$INSTALL_DIR/install.sh" >> "$LOG" 2>&1
    curl -sSL "$REPO/update.sh" -o "$INSTALL_DIR/update.sh" >> "$LOG" 2>&1
    curl -sSL "$REPO/requirements.txt" -o "$INSTALL_DIR/requirements.txt" >> "$LOG" 2>&1
    curl -sSL "$REPO/scannerintel-node.service" \
        -o /etc/systemd/system/scannerintel-node.service >> "$LOG" 2>&1
    systemctl daemon-reload >> "$LOG" 2>&1
) &
spinner "Updating service files..."

# Install any new Python dependencies
(
    pip3 install -r "$INSTALL_DIR/requirements.txt" --quiet --break-system-packages >> "$LOG" 2>&1 || true
) &
spinner "Checking dependencies..."

# Read new version
NEW_VERSION="unknown"
if [ -f "$INSTALL_DIR/main.py" ]; then
    NEW_VERSION=$(grep -oP "Node v\K[0-9.]+" "$INSTALL_DIR/main.py" 2>/dev/null || echo "unknown")
fi

# Restart service if running
echo ""
if systemctl is-active --quiet scannerintel-node 2>/dev/null; then
    (
        systemctl restart scannerintel-node >> "$LOG" 2>&1
    ) &
    spinner "Restarting service..."
else
    printf "  ─  Service not running (start with: sudo systemctl start scannerintel-node)\n"
fi

echo ""
echo "  Updated: v${OLD_VERSION} → v${NEW_VERSION}"
echo ""
echo "  Config preserved: /etc/scannerintel/config.yml"
echo "  Logs: journalctl -u scannerintel-node -f"
echo ""
