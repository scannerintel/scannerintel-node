#!/bin/bash
set -e

REPO="https://raw.githubusercontent.com/scannerintel/scannerintel-node/main"
INSTALL_DIR="/opt/scannerintel-node"
CONFIG_DIR="/etc/scannerintel"
SERVICE_USER="scannerintel"
API_URL="https://scannerintel.com"
LOG="/tmp/scannerintel-install.log"

> "$LOG"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        echo "  Error details:"
        echo "  ─────────────────────────────────────"
        tail -20 "$LOG" | sed 's/^/  /'
        echo "  ─────────────────────────────────────"
        echo ""
        echo "  Full log: $LOG"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

echo ""
echo "╔═══════════════════════════════════════╗"
echo "║    ScannerIntel Node Installer        ║"
echo "║  https://scannerintel.com/contribute  ║"
echo "╚═══════════════════════════════════════╝"
echo ""

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "  ✗  Please run as root: sudo bash install.sh"
    exit 1
fi

# Check architecture
ARCH=$(uname -m)
DISTRO=$(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '"')
echo "  Platform: ${DISTRO} (${ARCH})"
echo ""

# ---------------------------------------------------------------------------
# Installation steps
# ---------------------------------------------------------------------------

# 1. System dependencies (without ffmpeg — we install a static binary)
(
    apt-get update -qq >> "$LOG" 2>&1
    apt-get install -y -qq rtl-sdr python3 python3-pip python3-yaml curl jq bc xz-utils >> "$LOG" 2>&1
    pip3 install requests --quiet --break-system-packages >> "$LOG" 2>&1 || \
        apt-get install -y -qq python3-requests >> "$LOG" 2>&1
) &
spinner "Installing dependencies..."

# 2. Static ffmpeg binary
(
    case "$ARCH" in
        aarch64) FFMPEG_ARCH="arm64" ;;
        x86_64)  FFMPEG_ARCH="amd64" ;;
        armv7l)  FFMPEG_ARCH="armhf" ;;
        *)       FFMPEG_ARCH="amd64" ;;
    esac

    FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-${FFMPEG_ARCH}-static.tar.xz"
    FFMPEG_TMP="/tmp/ffmpeg-static.tar.xz"

    curl -sSL "$FFMPEG_URL" -o "$FFMPEG_TMP" >> "$LOG" 2>&1
    mkdir -p /tmp/ffmpeg-extract >> "$LOG" 2>&1
    tar -xf "$FFMPEG_TMP" -C /tmp/ffmpeg-extract --strip-components=1 >> "$LOG" 2>&1
    cp /tmp/ffmpeg-extract/ffmpeg /usr/local/bin/ffmpeg >> "$LOG" 2>&1
    chmod +x /usr/local/bin/ffmpeg >> "$LOG" 2>&1
    rm -rf /tmp/ffmpeg-extract "$FFMPEG_TMP" >> "$LOG" 2>&1

    # Verify
    /usr/local/bin/ffmpeg -version >> "$LOG" 2>&1
) &
spinner "Installing ffmpeg (static binary)..."

# 3. Detect RTL-SDR
RTL_OUTPUT=$(rtl_test -t 2>&1 || true)
RTL_DEVICES=$(echo "$RTL_OUTPUT" | grep -E "^\s+[0-9]" || true)
if [ -n "$RTL_DEVICES" ]; then
    printf "  ✓  Detecting RTL-SDR hardware...\n"
    echo "$RTL_DEVICES" | sed 's/^/     /'
else
    printf "  ⚠  No RTL-SDR devices detected (check USB connection)\n"
fi

# 4. Download node files
(
    mkdir -p "$INSTALL_DIR" >> "$LOG" 2>&1
    mkdir -p "$CONFIG_DIR" >> "$LOG" 2>&1
    for f in main.py sdr.py chunker.py uploader.py streamer.py calibrate.py web_control.py classifier.py config.py logger.py; do
        curl -sSL "$REPO/node/$f" -o "$INSTALL_DIR/$f" >> "$LOG" 2>&1
    done
    # Also grab update.sh
    curl -sSL "$REPO/update.sh" -o "$INSTALL_DIR/update.sh" >> "$LOG" 2>&1
    chmod +x "$INSTALL_DIR/update.sh" >> "$LOG" 2>&1
) &
spinner "Downloading node software..."

# 5. Create wrapper script
(
    cat > /usr/local/bin/scannerintel-node << 'WRAPPER'
#!/bin/bash
exec python3 /opt/scannerintel-node/main.py "$@"
WRAPPER
    chmod +x /usr/local/bin/scannerintel-node
) >> "$LOG" 2>&1

# 6. Service user
(
    if ! id "$SERVICE_USER" &>/dev/null; then
        useradd -r -s /bin/false -G plugdev "$SERVICE_USER" 2>/dev/null || \
        useradd -r -s /bin/false "$SERVICE_USER"
    fi
    usermod -aG plugdev "$SERVICE_USER" 2>/dev/null || true
) >> "$LOG" 2>&1 &
spinner "Setting up service user..."

# 7. Systemd service
(
    curl -sSL "$REPO/scannerintel-node.service" \
        -o /etc/systemd/system/scannerintel-node.service >> "$LOG" 2>&1
    systemctl daemon-reload >> "$LOG" 2>&1
) &
spinner "Installing systemd service..."

# ---------------------------------------------------------------------------
# Interactive config setup
# ---------------------------------------------------------------------------

echo ""
echo "─────────────────────────────────────────"
echo "  Node Setup"
echo "─────────────────────────────────────────"
echo ""
echo "  The server assigns your monitoring frequency"
echo "  automatically based on coverage gaps near you."
echo ""

# SDR device index
read -r -p "  SDR device index [0]: " DEVICE_INDEX
DEVICE_INDEX="${DEVICE_INDEX:-0}"

# Email (optional)
echo ""
echo "  Optional: link your email for free premium access."
read -r -p "  Email address (Enter to skip): " EMAIL

# Location description (optional)
echo ""
read -r -p "  Location description (Enter to skip): " LOCATION_DESC

# Latitude / Longitude (optional)
echo ""
echo "  Optional: coordinates for the coverage map."
read -r -p "  Latitude (Enter to skip): " LAT
read -r -p "  Longitude (Enter to skip): " LON

echo ""

# Build config.yml
(
    cat > "$CONFIG_DIR/config.yml" << CFGEOF
# ScannerIntel Node Configuration
# Frequency is assigned automatically by the server.
# Gain and squelch are set by auto-calibration on first startup.

server:
  url: $API_URL
CFGEOF

    if [ -n "$EMAIL" ]; then
        echo "" >> "$CONFIG_DIR/config.yml"
        echo "email: ${EMAIL}" >> "$CONFIG_DIR/config.yml"
    fi

    cat >> "$CONFIG_DIR/config.yml" << CFGEOF

node:
  device_index: ${DEVICE_INDEX}
  gain: 49
  sample_rate: 48000
  bias_tee: false
  location:
CFGEOF

    if [ -n "$LAT" ] && [ -n "$LON" ]; then
        echo "    lat: ${LAT}" >> "$CONFIG_DIR/config.yml"
        echo "    lon: ${LON}" >> "$CONFIG_DIR/config.yml"
    else
        echo "    lat: null" >> "$CONFIG_DIR/config.yml"
        echo "    lon: null" >> "$CONFIG_DIR/config.yml"
    fi

    if [ -n "$LOCATION_DESC" ]; then
        echo "    description: \"${LOCATION_DESC}\"" >> "$CONFIG_DIR/config.yml"
    else
        echo "    description: null" >> "$CONFIG_DIR/config.yml"
    fi
) &
spinner "Writing configuration..."

# ---------------------------------------------------------------------------
# Register with server
# ---------------------------------------------------------------------------

# Build hardware fingerprint the same way the Python client does
CPU_SERIAL=$(cat /proc/cpuinfo 2>/dev/null | grep "^Serial" | awk -F: '{print $2}' | tr -d ' ' || true)
MAC_ADDR=$(cat /sys/class/net/eth0/address 2>/dev/null || true)

if [ -n "$CPU_SERIAL" ] || [ -n "$MAC_ADDR" ]; then
    FP_INPUT=""
    [ -n "$CPU_SERIAL" ] && FP_INPUT="${CPU_SERIAL}"
    [ -n "$MAC_ADDR" ] && FP_INPUT="${FP_INPUT:+${FP_INPUT}|}${MAC_ADDR}"
    HW_FINGERPRINT=$(echo -n "$FP_INPUT" | sha256sum | awk '{print $1}')
else
    FP_INPUT="$(hostname)|$(uname -m)"
    HW_FINGERPRINT=$(echo -n "$FP_INPUT" | sha256sum | awk '{print $1}')
fi

# Build registration JSON
REG_JSON="{\"hardware_fingerprint\":\"${HW_FINGERPRINT}\",\"software_version\":\"1.0.0\",\"platform\":\"linux_${ARCH}\"}"

if [ -n "$EMAIL" ]; then
    REG_JSON=$(echo "$REG_JSON" | jq --arg e "$EMAIL" '. + {email: $e}')
fi
if [ -n "$LAT" ] && [ -n "$LON" ]; then
    REG_JSON=$(echo "$REG_JSON" | jq --argjson lat "$LAT" --argjson lon "$LON" '. + {latitude: $lat, longitude: $lon}')
fi
if [ -n "$LOCATION_DESC" ]; then
    REG_JSON=$(echo "$REG_JSON" | jq --arg d "$LOCATION_DESC" '. + {location_description: $d}')
fi

(
    curl -sS -X POST \
        -H "Content-Type: application/json" \
        -d "$REG_JSON" \
        "${API_URL}/api/v1/nodes/register" \
        -o /tmp/scannerintel-reg.json >> "$LOG" 2>&1
) &
spinner "Registering with ScannerIntel..."

# Parse response
REG_RESP=$(cat /tmp/scannerintel-reg.json 2>/dev/null || echo "{}")
rm -f /tmp/scannerintel-reg.json

NODE_ID=$(echo "$REG_RESP" | jq -r '.device_id // empty' 2>/dev/null || true)
FACILITY_NAME=$(echo "$REG_RESP" | jq -r '.assigned_facility.facility_name // empty' 2>/dev/null || true)
FACILITY_FREQ=$(echo "$REG_RESP" | jq -r '.assigned_facility.frequency_hz // empty' 2>/dev/null || true)
FACILITY_MOD=$(echo "$REG_RESP" | jq -r '.assigned_facility.modulation // "am"' 2>/dev/null || true)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "╔═══════════════════════════════════════╗"
echo "║    Installation Complete! 🎉           ║"
echo "╚═══════════════════════════════════════╝"
echo ""

if [ -n "$NODE_ID" ] && [ "$NODE_ID" != "null" ]; then
    echo "  Node ID:   ${NODE_ID}"
else
    echo "  Node ID:   (will be assigned on first start)"
fi

if [ -n "$FACILITY_FREQ" ] && [ "$FACILITY_FREQ" != "null" ]; then
    FREQ_MHZ=$(echo "scale=3; $FACILITY_FREQ / 1000000" | bc)
    MOD_UPPER=$(echo "$FACILITY_MOD" | tr '[:lower:]' '[:upper:]')
    if [ -n "$FACILITY_NAME" ] && [ "$FACILITY_NAME" != "null" ]; then
        echo "  Assigned:  ${FACILITY_NAME}  ${FREQ_MHZ} MHz ${MOD_UPPER}"
    else
        echo "  Assigned:  ${FREQ_MHZ} MHz ${MOD_UPPER}"
    fi
    echo "  Status:    Calibrating on first start..."
else
    echo "  Assigned:  No coverage gaps in your area right now"
    echo "  Status:    Waiting (visit scannerintel.com/contribute)"
fi

echo ""
echo "  Start:     sudo systemctl enable --now scannerintel-node"
echo "  Logs:      journalctl -u scannerintel-node -f"
echo "  Update:    sudo bash $INSTALL_DIR/update.sh"
echo ""
echo "  Thank you for contributing to ScannerIntel!"
echo ""
