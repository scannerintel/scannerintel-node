import json
import math
import os
import struct
import subprocess
import tempfile
import time
from typing import Optional, Tuple

from logger import get_logger

log = get_logger('calibrate')

STATE_FILE = os.path.expanduser('~/.scannerintel/state.json')

DEFAULT_GAIN = 30
DEFAULT_SQUELCH = -40.0


class Calibrator:
    def __init__(self, device_index: int, frequency_hz: int,
                 modulation: str, bias_tee: bool = False):
        self.device_index = device_index
        self.frequency_hz = frequency_hz
        self.modulation = modulation
        self.bias_tee = bias_tee

    def run(self) -> Tuple[float, float]:
        """
        Run full calibration sequence.
        Returns (calibrated_gain, calibrated_squelch).
        """
        log.info("Starting calibration",
                 frequency_hz=self.frequency_hz,
                 device_index=self.device_index)

        try:
            # Step 1: sweep gain levels to find optimal
            optimal_gain = self._find_optimal_gain()

            # Step 2: measure noise floor at optimal gain
            squelch = self._measure_noise_floor(optimal_gain)

            log.info("Calibration complete",
                     gain=optimal_gain, squelch=f"{squelch:.1f}")
            print(f"Calibration complete -- Gain: {optimal_gain}, "
                  f"Squelch: {squelch:.1f} dBm")

            self._save_calibration(optimal_gain, squelch)
            return optimal_gain, squelch

        except Exception as e:
            log.error("Calibration failed, using defaults", error=str(e))
            print(f"Calibration failed ({e}) -- using defaults: "
                  f"Gain: {DEFAULT_GAIN}, Squelch: {DEFAULT_SQUELCH}")
            self._save_calibration(DEFAULT_GAIN, DEFAULT_SQUELCH)
            return DEFAULT_GAIN, DEFAULT_SQUELCH

    def _find_optimal_gain(self) -> float:
        """Sweep gain from 10 to 49 in steps of 5, find SNR peak."""
        gain_levels = list(range(10, 50, 5))
        measurements = []

        log.info("Sweeping gain levels", levels=gain_levels)

        for gain in gain_levels:
            power = self._record_and_measure(gain, duration=5)
            measurements.append((gain, power))
            log.debug("Gain measurement", gain=gain, power_db=f"{power:.1f}")

        # Find where signal power stops increasing but noise continues
        # (SNR peak): look for the largest jump drop-off in power delta
        if len(measurements) < 2:
            return DEFAULT_GAIN

        # Calculate power deltas between successive gain levels
        deltas = []
        for i in range(1, len(measurements)):
            delta = measurements[i][1] - measurements[i - 1][1]
            deltas.append((measurements[i][0], delta))

        # SNR peaks where gain increases stop yielding proportional signal
        # improvement. Find the gain level after which the delta drops most
        # significantly (diminishing returns = noise floor rising).
        best_gain = measurements[0][0]
        best_snr_idx = 0

        for i in range(len(deltas)):
            # If delta drops compared to previous, the prior gain was better
            if i > 0 and deltas[i][1] < deltas[i - 1][1] * 0.5:
                best_snr_idx = i - 1
                break
            best_snr_idx = i

        if best_snr_idx < len(deltas):
            best_gain = deltas[best_snr_idx][0]

        # Back off 5 dB from the SNR peak for safety margin
        optimal = max(10, best_gain - 5)

        log.info("Optimal gain found", optimal_gain=optimal,
                 peak_gain=best_gain)
        return float(optimal)

    def _measure_noise_floor(self, gain: float) -> float:
        """Record 10 seconds at optimal gain and measure noise floor."""
        log.info("Measuring noise floor", gain=gain, duration=10)
        noise_power = self._record_and_measure(gain, duration=10)
        squelch = noise_power + 8.0
        log.info("Noise floor measured",
                 noise_db=f"{noise_power:.1f}",
                 squelch_db=f"{squelch:.1f}")
        return squelch

    def _record_and_measure(self, gain: float, duration: int) -> float:
        """Record raw audio at given gain for duration seconds, return RMS power in dB."""
        raw_fd, raw_path = tempfile.mkstemp(suffix='.raw')
        os.close(raw_fd)

        try:
            rtl_cmd = [
                'rtl_fm',
                '-d', str(self.device_index),
                '-f', str(self.frequency_hz),
                '-M', self.modulation,
                '-s', '48000',
                '-g', str(int(gain)),
                '-',
            ]

            if self.bias_tee:
                rtl_cmd.insert(-1, '-T')

            with open(raw_path, 'wb') as raw_out:
                proc = subprocess.Popen(
                    rtl_cmd,
                    stdout=raw_out,
                    stderr=subprocess.PIPE,
                )
                time.sleep(duration)
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

            return self._calculate_power(raw_path)

        finally:
            if os.path.exists(raw_path):
                os.unlink(raw_path)

    def _calculate_power(self, raw_path: str) -> float:
        """Calculate RMS power of raw 16-bit PCM samples in dB."""
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

    def _save_calibration(self, gain: float, squelch: float):
        """Save calibrated values to state.json."""
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

        state = {}
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
        except Exception:
            pass

        state['calibrated_gain'] = gain
        state['calibrated_squelch'] = squelch

        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)

    @staticmethod
    def load_calibration() -> Optional[Tuple[float, float]]:
        """Load calibrated values from state.json. Returns None if not present."""
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            gain = state.get('calibrated_gain')
            squelch = state.get('calibrated_squelch')
            if gain is not None and squelch is not None:
                return float(gain), float(squelch)
        except Exception:
            pass
        return None
