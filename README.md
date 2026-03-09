# ScannerIntel Node

Capture radio audio and contribute to the ScannerIntel network.
Earn free premium access for as long as your node is active.

## Quick Install

```bash
curl -sSL https://scannerintel.com/install | sudo bash
```

## Requirements

- Raspberry Pi (any model) or any Linux machine
- RTL-SDR dongle (RTL-SDR Blog V3/V4 recommended)
- Antenna appropriate for your target frequencies

## Manual Setup

```bash
# Install dependencies
sudo apt install rtl-sdr sox python3 python3-pip
pip3 install pyyaml requests

# Clone repo
git clone https://github.com/scannerintel/scannerintel-node
cd scannerintel-node

# Configure
cp config.example.yml config.yml
nano config.yml  # add your API key and frequencies

# Scan for active frequencies near you
python3 node/main.py --scan

# Test your setup
python3 node/main.py --test

# Run
python3 node/main.py
```

## Configuration

See `config.example.yml` for all options.

Key settings:
- `server.api_key` -- get this from scannerintel.com/contribute
- `node.device_index` -- RTL-SDR device index (run `rtl_test` to find yours)
- `node.gain` -- SDR gain in dB (40 is a good starting point)
- `node.squelch` -- silence threshold (-30 dBm works for most locations)
- `node.bias_tee` -- enable bias tee for active antennas (default true for V4)
- `channels` -- list of frequencies to monitor

## Running as a Service

```bash
sudo systemctl enable --now scannerintel-node
journalctl -u scannerintel-node -f
```

## License

MIT
