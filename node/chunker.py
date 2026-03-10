from datetime import datetime, timezone
from dataclasses import dataclass

from sdr import SDRDevice


@dataclass
class AudioChunk:
    channel_index: int
    frequency_hz: int
    modulation: str
    wav_bytes: bytes
    duration_ms: int
    signal_power_db: float
    timestamp: str          # ISO8601 UTC
    is_silence: bool


class Chunker:
    def __init__(self, sdr: SDRDevice, frequency_hz: int, modulation: str,
                 chunk_duration: int = 10, squelch: float = -40.0):
        self.sdr = sdr
        self.frequency_hz = frequency_hz
        self.modulation = modulation
        self.chunk_duration = chunk_duration
        self.squelch = squelch

    def capture(self) -> AudioChunk:
        """Capture one chunk from the configured frequency. Returns chunk with is_silence flag."""
        start_ts = datetime.now(timezone.utc).isoformat()
        freq_mhz = self.frequency_hz / 1e6

        wav_bytes, power_db = self.sdr.record_chunk(
            frequency_mhz=freq_mhz,
            modulation=self.modulation,
            duration_seconds=self.chunk_duration,
        )

        is_silence = power_db < self.squelch

        return AudioChunk(
            channel_index=0,
            frequency_hz=self.frequency_hz,
            modulation=self.modulation,
            wav_bytes=wav_bytes,
            duration_ms=self.chunk_duration * 1000,
            signal_power_db=power_db,
            timestamp=start_ts,
            is_silence=is_silence,
        )
