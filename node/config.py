import yaml
import os
from dataclasses import dataclass, field
from typing import Optional, List

CONFIG_PATHS = [
    './config.yml',
    os.path.expanduser('~/.scannerintel/config.yml'),
    '/etc/scannerintel/config.yml',
]


@dataclass
class ChannelConfig:
    index: int
    frequency: float        # MHz
    modulation: str         # 'fm' or 'am'
    description: str = ''
    enabled: bool = True


@dataclass
class LocationConfig:
    lat: Optional[float] = None
    lon: Optional[float] = None
    description: Optional[str] = None


@dataclass
class NodeConfig:
    device_index: int = 0
    gain: float = 40
    chunk_duration: int = 15
    sample_rate: int = 22050
    squelch: float = -30
    bias_tee: bool = True
    location: LocationConfig = field(default_factory=LocationConfig)


@dataclass
class ServerConfig:
    url: str = 'https://scannerintel.com'
    api_key: str = ''


@dataclass
class Config:
    server: ServerConfig
    node: NodeConfig
    channels: List[ChannelConfig]
    email: Optional[str] = None


def load_config(path: Optional[str] = None) -> Config:
    config_path = path
    if not config_path:
        for p in CONFIG_PATHS:
            if os.path.exists(p):
                config_path = p
                break

    if not config_path or not os.path.exists(config_path):
        raise FileNotFoundError(
            "No config file found. Copy config.example.yml to config.yml "
            "and fill in your details."
        )

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    # Server config
    srv = raw.get('server', {})
    server = ServerConfig(
        url=srv.get('url', 'https://scannerintel.com'),
        api_key=srv.get('api_key', ''),
    )

    if not server.api_key or server.api_key == 'sk_live_your_key_here':
        raise ValueError("server.api_key is not set in config.yml")

    # Node config
    n = raw.get('node', {})
    loc = n.get('location', {})
    node = NodeConfig(
        device_index=n.get('device_index', 0),
        gain=n.get('gain', 40),
        chunk_duration=n.get('chunk_duration', 15),
        sample_rate=n.get('sample_rate', 22050),
        squelch=n.get('squelch', -30),
        bias_tee=n.get('bias_tee', True),
        location=LocationConfig(
            lat=loc.get('lat'),
            lon=loc.get('lon'),
            description=loc.get('description'),
        ),
    )

    if not 5 <= node.chunk_duration <= 30:
        raise ValueError("node.chunk_duration must be between 5 and 30 seconds")

    # Channels
    channels = []
    for ch in raw.get('channels', []):
        mod = ch.get('modulation', 'fm').lower()
        if mod not in ('fm', 'am'):
            raise ValueError(
                f"Channel {ch.get('index')}: modulation must be 'fm' or 'am'"
            )
        channels.append(ChannelConfig(
            index=ch['index'],
            frequency=float(ch['frequency']),
            modulation=mod,
            description=ch.get('description', ''),
            enabled=ch.get('enabled', True),
        ))

    if not channels:
        raise ValueError("No channels configured in config.yml")

    return Config(
        server=server,
        node=node,
        channels=channels,
        email=raw.get('email'),
    )
