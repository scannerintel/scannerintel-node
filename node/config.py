import yaml
import os
from dataclasses import dataclass, field
from typing import Optional


CONFIG_PATHS = [
    './config.yml',
    os.path.expanduser('~/.scannerintel/config.yml'),
    '/etc/scannerintel/config.yml',
]


@dataclass
class LocationConfig:
    lat: Optional[float] = None
    lon: Optional[float] = None
    description: Optional[str] = None


@dataclass
class NodeConfig:
    device_index: int = 0
    gain: float = 49
    sample_rate: int = 48000
    bias_tee: bool = False
    location: LocationConfig = field(default_factory=LocationConfig)


@dataclass
class ServerConfig:
    url: str = 'https://api.scannerintel.com'


@dataclass
class Config:
    server: ServerConfig
    node: NodeConfig
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
        url=srv.get('url', 'https://api.scannerintel.com'),
    )

    # Node config
    n = raw.get('node', {})
    loc = n.get('location', {})
    node = NodeConfig(
        device_index=n.get('device_index', 0),
        gain=n.get('gain', 49),
        sample_rate=n.get('sample_rate', 48000),
        bias_tee=n.get('bias_tee', False),
        location=LocationConfig(
            lat=loc.get('lat'),
            lon=loc.get('lon'),
            description=loc.get('description'),
        ),
    )

    if not isinstance(node.gain, (int, float)) or not 0 <= node.gain <= 49:
        raise ValueError("node.gain must be a number between 0 and 49")

    if not isinstance(node.device_index, int) or node.device_index < 0:
        raise ValueError("node.device_index must be a non-negative integer")

    if not isinstance(node.sample_rate, int) or node.sample_rate <= 0:
        raise ValueError("node.sample_rate must be a positive integer")

    url = server.url
    if not url.startswith('https://'):
        raise ValueError("server.url must use HTTPS")

    email = raw.get('email')
    if email is not None and not isinstance(email, str):
        raise ValueError("email must be a string")

    return Config(
        server=server,
        node=node,
        email=email,
    )
