import datetime
from dataclasses import dataclass

from sdr import SDRDevice
from config import ChannelConfig, NodeConfig


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
    def __init__(self, sdr: SDRDevice, node_config: NodeConfig):
        self.sdr = sdr
        self.config = node_config

    def capture(self, channel: ChannelConfig) -> AudioChunk:
        """Capture one chunk from a channel. Returns chunk with is_silence flag."""
        start_ts = datetime.datetime.utcnow().isoformat() + 'Z'

        wav_bytes, power_db = self.sdr.record_chunk(
            frequency_mhz=channel.frequency,
            modulation=channel.modulation,
            duration_seconds=self.config.chunk_duration,
        )

        is_silence = power_db < self.config.squelch

        return AudioChunk(
            channel_index=channel.index,
            frequency_hz=int(channel.frequency * 1e6),
            modulation=channel.modulation,
            wav_bytes=wav_bytes,
            duration_ms=self.config.chunk_duration * 1000,
            signal_power_db=power_db,
            timestamp=start_ts,
            is_silence=is_silence,
        )
