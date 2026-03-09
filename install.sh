#!/bin/bash
set -e

REPO="https://raw.githubusercontent.com/scannerintel/scannerintel-node/main"
INSTALL_DIR="/opt/scannerintel-node"
CONFIG_DIR="/etc/scannerintel"
SERVICE_USER="scannerintel"
API_URL="https://scannerintel.com"

echo ""
echo "╔═══════════════════════════════════════╗"
echo "║    ScannerIntel Node Installer        ║"
echo "║  https://scannerintel.com/contribute  ║"
echo "╚═══════════════════════════════════════╝"
echo ""

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Please run as root (sudo bash install.sh)"
    exit 1
fi

# Check architecture
ARCH=$(uname -m)
echo "Detected: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '"') ($ARCH)"

# Install dependencies
echo ""
echo "-> Installing dependencies..."
apt-get update -qq
apt-get install -y -qq rtl-sdr ffmpeg python3 python3-pip python3-yaml curl jq

# Install Python requests if not available via apt
pip3 install requests --quiet --break-system-packages 2>/dev/null || \
apt-get install -y -qq python3-requests

# Detect RTL-SDR devices
echo ""
echo "-> Detecting RTL-SDR hardware..."
echo ""
RTL_OUTPUT=$(rtl_test -t 2>&1 || true)
echo "$RTL_OUTPUT" | grep -E "^\s+[0-9]" || echo "  (no devices detected)"
echo ""

# Create install directory
echo "-> Installing node client to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"

# Download node files
for f in main.py sdr.py chunker.py uploader.py streamer.py classifier.py config.py logger.py; do
    curl -sSL "$REPO/node/$f" -o "$INSTALL_DIR/$f"
done

# Create wrapper script
cat > /usr/local/bin/scannerintel-node << 'EOF'
#!/bin/bash
exec python3 /opt/scannerintel-node/main.py "$@"
EOF
chmod +x /usr/local/bin/scannerintel-node

# Create service user
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -s /bin/false -G plugdev "$SERVICE_USER" 2>/dev/null || \
    useradd -r -s /bin/false "$SERVICE_USER"
fi

# Add user to plugdev for USB access
usermod -aG plugdev "$SERVICE_USER" 2>/dev/null || true

# Install systemd service
curl -sSL "$REPO/scannerintel-node.service" \
    -o /etc/systemd/system/scannerintel-node.service
systemctl daemon-reload

# ---------------------------------------------------------------------------
# Interactive config setup
# ---------------------------------------------------------------------------
echo ""
echo "============================================="
echo "         Node Setup                          "
echo "============================================="
echo ""
echo "The server assigns your monitoring frequency"
echo "automatically based on coverage gaps near you."
echo ""

# SDR device index
read -r -p "SDR device index [0]: " DEVICE_INDEX
DEVICE_INDEX="${DEVICE_INDEX:-0}"

# Email (optional)
echo ""
echo "Optional: link your email for free premium access."
read -r -p "Email address (press Enter to skip): " EMAIL

# Location description (optional)
echo ""
read -r -p "Location description, e.g. \"Rooftop antenna, Northern Kentucky\" (press Enter to skip): " LOCATION_DESC

# Latitude / Longitude (optional)
echo ""
echo "Optional: coordinates for the coverage map."
read -r -p "Latitude (press Enter to skip): " LAT
read -r -p "Longitude (press Enter to skip): " LON

# Build config.yml
cat > "$CONFIG_DIR/config.yml" << CFGEOF
# ScannerIntel Node Configuration
# Frequency is assigned automatically by the server.

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

echo ""
echo "-> Config written to $CONFIG_DIR/config.yml"

# ---------------------------------------------------------------------------
# Register with server to show assigned facility
# ---------------------------------------------------------------------------
echo ""
echo "-> Registering with ScannerIntel..."

# Build hardware fingerprint the same way the Python client does
HW_FINGERPRINT=""
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

REG_RESP=$(curl -sS -X POST \
    -H "Content-Type: application/json" \
    -d "$REG_JSON" \
    "${API_URL}/api/v1/nodes/register" 2>&1) || true

# Parse response
FACILITY_NAME=$(echo "$REG_RESP" | jq -r '.assigned_facility.name // empty' 2>/dev/null || true)
FACILITY_FREQ=$(echo "$REG_RESP" | jq -r '.assigned_facility.frequency_hz // empty' 2>/dev/null || true)
FACILITY_MOD=$(echo "$REG_RESP" | jq -r '.assigned_facility.modulation // empty' 2>/dev/null || true)

echo ""
if [ -n "$FACILITY_FREQ" ] && [ "$FACILITY_FREQ" != "null" ]; then
    FREQ_MHZ=$(echo "scale=3; $FACILITY_FREQ / 1000000" | bc)
    MOD_UPPER=$(echo "$FACILITY_MOD" | tr '[:lower:]' '[:upper:]')
    if [ -n "$FACILITY_NAME" ] && [ "$FACILITY_NAME" != "null" ]; then
        echo "  You've been assigned: $FACILITY_NAME $FREQ_MHZ MHz $MOD_UPPER"
    else
        echo "  You've been assigned: $FREQ_MHZ MHz $MOD_UPPER"
    fi
else
    echo "  No coverage gaps in your area right now."
    echo "  Check back later or visit scannerintel.com/contribute"
fi

echo ""
echo "============================================="
echo "         Installation complete!              "
echo "============================================="
echo ""
echo "  Next steps:"
echo ""
echo "  1. Test hardware + registration:"
echo "     scannerintel-node --test"
echo ""
echo "  2. Start the node:"
echo "     sudo systemctl enable --now scannerintel-node"
echo ""
echo "  3. Check logs:"
echo "     journalctl -u scannerintel-node -f"
echo ""
