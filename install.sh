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
DEVICE_COUNT=$(rtl_test -t 2>&1 | grep -c "^  [0-9]" || echo "0")

if [ "$DEVICE_COUNT" -eq 0 ]; then
    echo "WARNING: No RTL-SDR devices detected."
    echo "  Make sure your SDR dongle is plugged in."
    echo "  You can configure the device_index manually in /etc/scannerintel/config.yml"
fi

rtl_test -t 2>&1 | grep "^  [0-9]" || true

# Create install directory
echo ""
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

# Create config if it doesn't exist
if [ ! -f "$CONFIG_DIR/config.yml" ]; then
    curl -sSL "$REPO/config.example.yml" -o "$CONFIG_DIR/config.yml"
    echo ""
    echo "-> Config file created at $CONFIG_DIR/config.yml"
    echo "  Edit this file to add your API key and frequencies."
fi

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

echo ""
echo "============================================="
echo "         Installation complete!              "
echo "============================================="
echo ""
echo "  Next steps:"
echo ""
echo "  1. Edit your config:"
echo "     sudo nano /etc/scannerintel/config.yml"
echo ""
echo "  2. Add your API key from:"
echo "     https://scannerintel.com/contribute"
echo ""
echo "  3. Scan for active frequencies near you:"
echo "     scannerintel-node --scan"
echo ""
echo "  4. Start the node:"
echo "     sudo systemctl enable --now scannerintel-node"
echo ""
echo "  5. Check logs:"
echo "     journalctl -u scannerintel-node -f"
echo ""
