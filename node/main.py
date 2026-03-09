#!/usr/bin/env python3
"""
ScannerIntel Node Client
Captures radio audio and sends it to the ScannerIntel contributor network.
https://scannerintel.com/contribute
"""

import sys
import os
import time
import signal
import hashlib
import platform
import argparse
import subprocess
from typing import Optional

# Allow imports from the node package directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config, Config
from sdr import SDRDevice
from chunker import Chunker
from uploader import Uploader
from logger import get_logger

log = get_logger('main')

BANNER = """
╔═══════════════════════════════════════╗
║       ScannerIntel Node v1.0.0        ║
║   https://scannerintel.com/contribute ║
╚═══════════════════════════════════════╝
"""


def get_hardware_fingerprint() -> str:
    """Generate a stable hardware fingerprint from CPU serial and MAC address."""
    components = []

    # CPU serial (Raspberry Pi specific)
    try:
        with open('/proc/cpuinfo') as f:
            for line in f:
                if line.startswith('Serial'):
                    components.append(line.split(':')[1].strip())
                    break
    except Exception:
        pass

    # MAC address of first non-loopback interface
    try:
        result = subprocess.run(
            ['cat', '/sys/class/net/eth0/address'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            components.append(result.stdout.strip())
    except Exception:
        pass

    # Fallback: use hostname + platform
    if not components:
        components.append(platform.node())
        components.append(platform.machine())

    fingerprint = '|'.join(components)
    return hashlib.sha256(fingerprint.encode()).hexdigest()


def run_scan(device_index: int, gain: float):
    """Run a quick frequency scan and print strongest signals."""
    import tempfile
    import csv

    print("\nScanning for strong signals near you...")
    print("This will take about 20 seconds.\n")

    bands = [
        ("Aviation VHF (118-137 MHz)", "118M:137M:25k"),
        ("VHF Public Safety (154-174 MHz)", "154M:174M:25k"),
    ]

    for band_name, freq_range in bands:
        fd, scan_path = tempfile.mkstemp(suffix='.csv')
        os.close(fd)

        try:
            subprocess.run(
                [
                    'rtl_power', '-d', str(device_index),
                    '-f', freq_range,
                    '-g', str(gain),
                    '-i', '10', '-1', scan_path,
                ],
                timeout=15, capture_output=True,
            )

            data = []
            with open(scan_path) as f:
                for row in csv.reader(f):
                    try:
                        freq_start = float(row[2])
                        freq_step = float(row[4])
                        powers = [float(x) for x in row[6:]]
                        for i, p in enumerate(powers):
                            data.append((freq_start + i * freq_step, p))
                    except Exception:
                        pass

            data.sort(key=lambda x: -x[1])
            print(f"Top signals -- {band_name}:")
            for freq, power in data[:8]:
                print(f"  {freq / 1e6:.3f} MHz  {power:.1f} dBm")
            print()

        finally:
            if os.path.exists(scan_path):
                os.unlink(scan_path)


def main():
    print(BANNER)

    parser = argparse.ArgumentParser(description='ScannerIntel Node Client')
    parser.add_argument('--config', help='Path to config.yml')
    parser.add_argument('--scan', action='store_true',
                        help='Scan for strong signals and exit')
    parser.add_argument('--test', action='store_true',
                        help='Test hardware and config, then exit')
    args = parser.parse_args()

    # Load config
    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        # Allow --scan without a valid API key
        if args.scan:
            print("No config file found. Using defaults for scan mode.")
            run_scan(device_index=0, gain=40)
            sys.exit(0)
        print(f"ERROR: {e}")
        sys.exit(1)
    except ValueError as e:
        if args.scan:
            # Try to load config partially for scan mode
            print(f"Config warning: {e}")
            print("Using defaults for scan mode.\n")
            run_scan(device_index=0, gain=40)
            sys.exit(0)
        print(f"CONFIG ERROR: {e}")
        sys.exit(1)

    # Scan mode
    if args.scan:
        run_scan(config.node.device_index, config.node.gain)
        sys.exit(0)

    # Initialize SDR
    log.info("Initializing SDR hardware",
             device_index=config.node.device_index)
    try:
        sdr = SDRDevice(
            device_index=config.node.device_index,
            gain=config.node.gain,
            sample_rate=config.node.sample_rate,
            bias_tee=config.node.bias_tee,
        )
    except RuntimeError as e:
        log.error("SDR initialization failed", error=str(e))
        sys.exit(1)

    devices = sdr.detect_devices()
    log.info("Detected SDR devices", devices=devices)

    # Initialize uploader and register node
    uploader = Uploader(
        server_url=config.server.url,
        api_key=config.server.api_key,
    )

    fingerprint = get_hardware_fingerprint()
    channels_payload = [
        {'channel_index': ch.index, 'frequency_hz': int(ch.frequency * 1e6)}
        for ch in config.channels if ch.enabled
    ]

    log.info("Registering node with ScannerIntel")
    try:
        state = uploader.register(
            hardware_fingerprint=fingerprint,
            channels=channels_payload,
            email=config.email,
            lat=config.node.location.lat,
            lon=config.node.location.lon,
            description=config.node.location.description,
        )
        log.info("Node registered", device_id=state.device_id)
    except Exception as e:
        log.error("Registration failed", error=str(e))
        sys.exit(1)

    # Test mode -- exit after registration
    if args.test:
        log.info("Test mode -- hardware and registration OK")
        sys.exit(0)

    # Print startup summary
    enabled_channels = [ch for ch in config.channels if ch.enabled]
    print(f"\nNode active -- {state.device_id}")
    print(f"  Monitoring {len(enabled_channels)} channel(s):")
    for ch in enabled_channels:
        print(f"    {ch.frequency:.3f} MHz  {ch.modulation.upper()}  "
              f"{ch.description}")
    print(f"\n  Earn free premium: {config.server.url}/link")
    print(f"  Press Ctrl+C to stop\n")

    # Graceful shutdown
    running = True

    def handle_signal(sig, frame):
        nonlocal running
        log.info("Shutting down gracefully")
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Main channel cycling loop
    chunker = Chunker(sdr=sdr, node_config=config.node)
    channel_index = 0
    stats = {'uploaded': 0, 'skipped_silence': 0, 'failed': 0}

    log.info("Starting channel cycling loop",
             channels=len(enabled_channels),
             chunk_duration=config.node.chunk_duration)

    while running:
        channel = enabled_channels[channel_index % len(enabled_channels)]

        try:
            chunk = chunker.capture(channel)

            if chunk.is_silence:
                stats['skipped_silence'] += 1
                log.debug("Silence detected, skipping upload",
                          channel=channel.index,
                          frequency=channel.frequency,
                          power_db=chunk.signal_power_db)
            else:
                success = uploader.upload_chunk(chunk)
                if success:
                    stats['uploaded'] += 1
                    log.info("Chunk uploaded",
                             channel=channel.index,
                             frequency=channel.frequency,
                             power_db=f"{chunk.signal_power_db:.1f}",
                             duration_ms=chunk.duration_ms)
                else:
                    stats['failed'] += 1
                    log.warning("Upload failed, will retry next cycle",
                                channel=channel.index,
                                frequency=channel.frequency)

        except Exception as e:
            log.error("Unexpected error in capture/upload cycle",
                      channel=channel.index,
                      error=str(e))
            time.sleep(2)

        channel_index += 1

        # Log stats every 100 chunks
        total = stats['uploaded'] + stats['skipped_silence']
        if total % 100 == 0 and total > 0:
            log.info("Stats",
                     uploaded=stats['uploaded'],
                     skipped_silence=stats['skipped_silence'],
                     failed=stats['failed'])

    log.info("Node stopped", **stats)


if __name__ == '__main__':
    main()
