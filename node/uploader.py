import requests
import json
import os
import platform
from dataclasses import dataclass
from typing import Optional, List, Dict

from chunker import AudioChunk

STATE_FILE = os.path.expanduser('~/.scannerintel/state.json')


@dataclass
class NodeState:
    device_id: str
    api_key: str


class Uploader:
    def __init__(self, server_url: str, api_key: str):
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.state: Optional[NodeState] = self._load_state()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'scannerintel-node/1.0.0',
        })

    def register(self, hardware_fingerprint: str, channels: List[Dict],
                 email: Optional[str] = None,
                 lat: Optional[float] = None,
                 lon: Optional[float] = None,
                 description: Optional[str] = None) -> NodeState:
        """Register node with ScannerIntel API. Idempotent -- safe to call on every startup."""
        if self.state:
            return self.state

        payload = {
            'hardware_fingerprint': hardware_fingerprint,
            'software_version': '1.0.0',
            'platform': self._get_platform(),
            'detected_channels': channels,
        }
        if email:
            payload['email'] = email
        if lat is not None and lon is not None:
            payload['latitude'] = lat
            payload['longitude'] = lon
        if description:
            payload['location_description'] = description

        resp = self.session.post(
            f'{self.server_url}/api/v1/nodes/register',
            json=payload,
            headers={'Authorization': f'Bearer {self.api_key}'},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        state = NodeState(
            device_id=data['device_id'],
            api_key=data['api_key'],
        )
        self._save_state(state)
        self.state = state
        return state

    def upload_chunk(self, chunk: AudioChunk) -> bool:
        """Upload audio chunk. Returns True on success."""
        if not self.state:
            raise RuntimeError("Node not registered. Call register() first.")

        try:
            resp = self.session.post(
                f'{self.server_url}/api/v1/ingest/chunk',
                headers={'Authorization': f'Bearer {self.state.api_key}'},
                data={
                    'node_id': self.state.device_id,
                    'channel_index': str(chunk.channel_index),
                    'frequency_hz': str(chunk.frequency_hz),
                    'chunk_start_ts': chunk.timestamp,
                    'duration_ms': str(chunk.duration_ms),
                },
                files={
                    'audio': ('chunk.wav', chunk.wav_bytes, 'audio/wav'),
                },
                timeout=30,
            )
            return resp.status_code == 200

        except requests.exceptions.ConnectionError:
            return False
        except requests.exceptions.Timeout:
            return False
        except Exception:
            return False

    def _load_state(self) -> Optional[NodeState]:
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
                return NodeState(**data)
        except Exception:
            return None

    def _save_state(self, state: NodeState):
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            json.dump({
                'device_id': state.device_id,
                'api_key': state.api_key,
            }, f)

    def _get_platform(self) -> str:
        machine = platform.machine()
        system = platform.system().lower()
        return f'{system}_{machine}'
