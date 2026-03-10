#!/usr/bin/env python3
"""
ScannerIntel Node Client
Captures radio audio and sends it to the ScannerIntel contributor network.
https://scannerintel.com/contribute
"""

import sys
import os
import hashlib
import platform
import argparse
import time
from typing import Optional

# Allow imports from the node package directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config, Config
from uploader import Uploader
from streamer import Streamer
from calibrate import Calibrator
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
        net_dir = '/sys/class/net'
        for iface in sorted(os.listdir(net_dir)):
            if iface == 'lo':
                continue
            addr_path = os.path.join(net_dir, iface, 'address')
            with open(addr_path) as f:
                mac = f.read().strip()
            if mac and mac != '00:00:00:00:00:00':
                components.append(mac)
                break
    except Exception:
        pass

    # Fallback: use hostname + platform
    if not components:
        components.append(platform.node())
        components.append(platform.machine())

    fingerprint = '|'.join(components)
    return hashlib.sha256(fingerprint.encode()).hexdigest()


def main():
    print(BANNER)

    parser = argparse.ArgumentParser(description='ScannerIntel Node Client')
    parser.add_argument('--config', help='Path to config.yml')
    parser.add_argument('--test', action='store_true',
                        help='Test hardware and registration, then exit')
    parser.add_argument('--calibrate', action='store_true',
                        help='Force recalibration of gain and squelch, then exit')
    args = parser.parse_args()

    # Load config
    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"CONFIG ERROR: {e}")
        sys.exit(1)

    # Initialize uploader and register node
    uploader = Uploader(server_url=config.server.url)

    fingerprint = get_hardware_fingerprint()

    log.info("Registering node with ScannerIntel")
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            state = uploader.register(
                hardware_fingerprint=fingerprint,
                email=config.email,
                lat=config.node.location.lat,
                lon=config.node.location.lon,
                description=config.node.location.description,
            )
            log.info("Node registered", device_id=state.device_id)
            break
        except Exception as e:
            if attempt == max_retries:
                log.error("Registration failed after retries", error=str(e))
                sys.exit(1)
            delay = min(2 ** attempt, 60)
            log.warning("Registration failed, retrying",
                        attempt=attempt, delay=delay, error=str(e))
            time.sleep(delay)

    # Check if server assigned a facility
    if not state.facility:
        print("\nNo coverage gaps in your area right now.")
        print("Check back later or visit https://scannerintel.com/contribute")
        sys.exit(0)

    facility = state.facility
    freq_mhz = facility.frequency_hz / 1e6
    facility_label = facility.name or f"{freq_mhz:.3f} MHz"

    print(f"\nAssigned: {facility_label} {freq_mhz:.3f} MHz "
          f"{facility.modulation.upper()}")

    # Calibration
    calibrator = Calibrator(
        device_index=config.node.device_index,
        frequency_hz=facility.frequency_hz,
        modulation=facility.modulation,
        bias_tee=config.node.bias_tee,
    )

    if args.calibrate:
        calibrator.run()
        sys.exit(0)

    # Load existing calibration or run it
    cal = Calibrator.load_calibration()
    if cal:
        gain, squelch = cal
        log.info("Using saved calibration",
                 gain=gain, squelch=f"{squelch:.1f}")
    else:
        log.info("No calibration data found, running calibration")
        gain, squelch = calibrator.run()

    # Test mode -- exit after registration + calibration
    if args.test:
        log.info("Test mode -- registration and calibration OK",
                 facility=facility_label,
                 frequency_mhz=f"{freq_mhz:.3f}",
                 modulation=facility.modulation,
                 gain=gain,
                 squelch=f"{squelch:.1f}")
        sys.exit(0)

    print(f"\n  Streaming to: {config.server.url}")
    print(f"  Gain: {gain}  Squelch: {squelch:.1f} dBm")
    print(f"  Press Ctrl+C to stop\n")

    # Start streaming
    streamer = Streamer(
        stream_key=facility.stream_key,
        frequency_hz=facility.frequency_hz,
        modulation=facility.modulation,
        device_index=config.node.device_index,
        gain=gain,
        server_url=config.server.url,
        api_key=state.api_key,
        uploader=uploader,
    )

    streamer.run()

    log.info("Node stopped")


if __name__ == '__main__':
    main()
