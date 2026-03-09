#!/bin/bash
set -e

REPO="https://raw.githubusercontent.com/scannerintel/scannerintel-node/main"
INSTALL_DIR="/opt/scannerintel-node"
CONFIG_DIR="/etc/scannerintel"
SERVICE_USER="scannerintel"

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
apt-get install -y -qq rtl-sdr sox python3 python3-pip python3-yaml

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
for f in main.py sdr.py chunker.py uploader.py classifier.py config.py logger.py; do
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
echo "Your API key will be generated automatically"
echo "when the node first connects to scannerintel.com."
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

# Channels
echo ""
echo "Add frequencies to monitor. Type 'done' when finished."
echo "  Example: 162.550 fm NOAA Weather Radio"
echo ""

CHANNELS_YAML=""
CH_INDEX=0

while true; do
    read -r -p "Frequency in MHz (or 'done'): " FREQ
    [ "$FREQ" = "done" ] && break
    [ -z "$FREQ" ] && break

    read -r -p "  Modulation (fm/am) [fm]: " MOD
    MOD="${MOD:-fm}"

    read -r -p "  Description: " DESC

    CHANNELS_YAML="${CHANNELS_YAML}
  - index: ${CH_INDEX}
    frequency: ${FREQ}
    modulation: ${MOD}
    description: \"${DESC}\""

    CH_INDEX=$((CH_INDEX + 1))
    echo "  -> Added channel ${CH_INDEX}: ${FREQ} MHz ${MOD}"
    echo ""
done

if [ "$CH_INDEX" -eq 0 ]; then
    echo ""
    echo "WARNING: No channels configured. Add channels to $CONFIG_DIR/config.yml before starting."
    CHANNELS_YAML="
  - index: 0
    frequency: 162.550
    modulation: fm
    description: \"NOAA Weather Radio\""
fi

# Build config.yml
cat > "$CONFIG_DIR/config.yml" << CFGEOF
# ScannerIntel Node Configuration
# API key is generated automatically on first registration.

server:
  url: https://scannerintel.com
CFGEOF

if [ -n "$EMAIL" ]; then
    echo "" >> "$CONFIG_DIR/config.yml"
    echo "email: ${EMAIL}" >> "$CONFIG_DIR/config.yml"
fi

cat >> "$CONFIG_DIR/config.yml" << CFGEOF

node:
  device_index: ${DEVICE_INDEX}
  gain: 40
  chunk_duration: 15
  sample_rate: 22050
  squelch: -30
  bias_tee: true
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

cat >> "$CONFIG_DIR/config.yml" << CFGEOF

channels:${CHANNELS_YAML}
CFGEOF

echo ""
echo "============================================="
echo "         Installation complete!              "
echo "============================================="
echo ""
echo "  Config written to: $CONFIG_DIR/config.yml"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Scan for active frequencies near you:"
echo "     scannerintel-node --scan"
echo ""
echo "  2. Test hardware + registration:"
echo "     scannerintel-node --test"
echo ""
echo "  3. Start the node:"
echo "     sudo systemctl enable --now scannerintel-node"
echo ""
echo "  4. Check logs:"
echo "     journalctl -u scannerintel-node -f"
echo ""
