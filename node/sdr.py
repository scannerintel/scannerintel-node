import subprocess
import os
import struct
import math
import time
import tempfile
import shutil
from typing import List, Dict, Tuple


class SDRDevice:
    def __init__(self, device_index: int, gain: float, sample_rate: int,
                 bias_tee: bool = True):
        self.device_index = device_index
        self.gain = gain
        self.sample_rate = sample_rate
        self.bias_tee = bias_tee
        self._validate()

    def _validate(self):
        """Check rtl_fm is available and device index exists."""
        if not shutil.which('rtl_fm'):
            raise RuntimeError(
                "rtl_fm not found. Install rtl-sdr: sudo apt install rtl-sdr"
            )

        result = subprocess.run(
            ['rtl_test', '-d', str(self.device_index), '-t'],
            capture_output=True, text=True, timeout=15,
        )
        combined = result.stderr + result.stdout
        if 'Failed to open' in combined:
            raise RuntimeError(
                f"RTL-SDR device {self.device_index} not found or in use"
            )

    def detect_devices(self) -> List[Dict]:
        """Return list of all detected RTL-SDR devices."""
        result = subprocess.run(
            ['rtl_test', '-t'],
            capture_output=True, text=True, timeout=5,
        )
        devices = []
        for line in result.stdout.splitlines() + result.stderr.splitlines():
            line = line.strip()
            if line and line[0].isdigit() and ':' in line:
                parts = line.split(':', 1)
                devices.append({
                    'index': int(parts[0].strip()),
                    'name': parts[1].strip() if len(parts) > 1 else 'Unknown',
                })
        return devices

    def record_chunk(self, frequency_mhz: float, modulation: str,
                     duration_seconds: int) -> Tuple[bytes, float]:
        """
        Record audio from frequency for duration_seconds.
        Returns (wav_bytes, signal_power_db).
        Modulation: 'fm' or 'am'
        """
        freq_str = f"{frequency_mhz}M"
        gain_str = str(self.gain) if self.gain != 'auto' else '0'

        raw_fd, raw_path = tempfile.mkstemp(suffix='.raw')
        os.close(raw_fd)
        wav_fd, wav_path = tempfile.mkstemp(suffix='.wav')
        os.close(wav_fd)

        try:
            # Capture raw audio via rtl_fm
            rtl_cmd = [
                'rtl_fm',
                '-d', str(self.device_index),
                '-f', freq_str,
                '-M', modulation,
                '-s', str(self.sample_rate),
                '-g', gain_str,
            ]

            if self.bias_tee:
                rtl_cmd.append('-T')

            rtl_cmd.append('-')

            with open(raw_path, 'wb') as raw_out:
                proc = subprocess.Popen(
                    rtl_cmd,
                    stdout=raw_out,
                    stderr=subprocess.PIPE,
                )
                time.sleep(duration_seconds)
                proc.terminate()
                proc.wait(timeout=5)

            # Convert raw PCM to WAV via sox
            sox_cmd = [
                'sox',
                '-t', 'raw',
                '-r', str(self.sample_rate),
                '-e', 'signed-integer',
                '-b', '16',
                '-c', '1',
                raw_path,
                wav_path,
            ]
            subprocess.run(sox_cmd, check=True, capture_output=True, timeout=10)

            # Calculate signal power from raw samples
            signal_power = self._calculate_power(raw_path)

            with open(wav_path, 'rb') as f:
                wav_bytes = f.read()

            return wav_bytes, signal_power

        finally:
            if os.path.exists(raw_path):
                os.unlink(raw_path)
            if os.path.exists(wav_path):
                os.unlink(wav_path)

    def _calculate_power(self, raw_path: str) -> float:
        """Calculate RMS power of raw PCM samples in dB."""
        try:
            with open(raw_path, 'rb') as f:
                data = f.read()

            if len(data) < 2:
                return -100.0

            num_samples = len(data) // 2
            samples = struct.unpack(f'<{num_samples}h', data[:num_samples * 2])
            if not samples:
                return -100.0

            rms = math.sqrt(sum(s * s for s in samples) / len(samples))
            if rms == 0:
                return -100.0

            return 20 * math.log10(rms / 32768.0)

        except Exception:
            return -100.0
