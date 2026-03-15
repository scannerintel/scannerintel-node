import re
import requests
import json
import os
import platform
from dataclasses import dataclass
from typing import Optional, List, Dict


STATE_FILE = os.path.expanduser('~/.scannerintel/state.json')

# Only allow safe characters in stream keys
_STREAM_KEY_PATTERN = re.compile(r'^[a-zA-Z0-9_\-]+$')


@dataclass
class AssignedFacility:
    frequency_hz: int
    stream_key: str
    modulation: str = 'am'
    name: Optional[str] = None


@dataclass
class NodeState:
    device_id: str
    api_key: str
    facility: Optional[AssignedFacility] = None


class Uploader:
    def __init__(self, server_url: str):
        self.server_url = server_url.rstrip('/')
        self.state: Optional[NodeState] = None
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'scannerintel-node/1.0.0',
        })

    def register(self, hardware_fingerprint: str,
                 email: Optional[str] = None,
                 lat: Optional[float] = None,
                 lon: Optional[float] = None,
                 description: Optional[str] = None) -> NodeState:
        """Register node with ScannerIntel API. Idempotent -- safe to call on every startup."""
        payload = {
            'hardware_fingerprint': hardware_fingerprint,
            'software_version': '1.0.0',
            'platform': self._get_platform(),
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
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        facility = None
        af = data.get('assigned_facility')
        if af:
            stream_key = af.get('stream_key', '')
            if not _STREAM_KEY_PATTERN.match(stream_key):
                raise ValueError(
                    f"Server returned invalid stream_key: {stream_key!r}")
            facility = AssignedFacility(
                frequency_hz=af.get('frequency_hz'),
                stream_key=stream_key,
                modulation=af.get('modulation', 'am'),
                name=af.get('facility_name'),
            )

        state = NodeState(
            device_id=data['device_id'],
            api_key=data['api_key'],
            facility=facility,
        )
        self._save_state(state)
        self.state = state
        return state

    def upload_segment(self, stream_key: str, segment_index: int,
                       segment_bytes: bytes, duration_ms: int) -> dict:
        """Upload an HLS segment. Returns dict with 'ok' bool and 'error' string on failure."""
        if not self.state:
            raise RuntimeError("Node not registered. Call register() first.")

        try:
            resp = self.session.post(
                f'{self.server_url}/api/v1/stream/{stream_key}/segment',
                headers={'Authorization': f'Bearer {self.state.api_key}'},
                data={
                    'segment_index': str(segment_index),
                    'duration_ms': str(duration_ms),
                },
                files={
                    'segment': ('segment.ts', segment_bytes, 'video/mp2t'),
                },
                timeout=30,
            )
            if resp.status_code == 200:
                return {'ok': True}
            # Return the status and body so the caller can log it
            try:
                body = resp.json()
            except Exception:
                body = resp.text[:200]
            return {'ok': False, 'error': f'HTTP {resp.status_code}: {body}'}

        except requests.exceptions.ConnectionError as e:
            return {'ok': False, 'error': f'connection failed: {e}'}
        except requests.exceptions.Timeout:
            return {'ok': False, 'error': 'request timed out (30s)'}
        except Exception as e:
            return {'ok': False, 'error': f'unexpected: {e}'}

    def heartbeat(self) -> bool:
        """Send a heartbeat and ship buffered logs to the server."""
        if not self.state:
            return False
        try:
            resp = self.session.post(
                f'{self.server_url}/api/v1/nodes/heartbeat',
                headers={'Authorization': f'Bearer {self.state.api_key}'},
                json={'status': 'streaming'},
                timeout=10,
            )
            # Ship buffered logs after heartbeat
            self._ship_logs()
            return resp.status_code == 200
        except Exception:
            return False

    def _ship_logs(self):
        """Send buffered log entries to the server."""
        from logger import StructuredLogger
        entries = StructuredLogger.drain()
        if not entries or not self.state:
            return
        try:
            self.session.post(
                f'{self.server_url}/api/v1/nodes/logs',
                headers={'Authorization': f'Bearer {self.state.api_key}'},
                json={'logs': entries},
                timeout=10,
            )
        except Exception:
            pass  # Best-effort — don't crash if log shipping fails

    def _load_state(self) -> Optional[NodeState]:
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
                return NodeState(**data)
        except Exception:
            return None

    def _save_state(self, state: NodeState):
        state_dir = os.path.dirname(STATE_FILE)
        os.makedirs(state_dir, mode=0o700, exist_ok=True)
        fd = os.open(STATE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump({
                'device_id': state.device_id,
                'api_key': state.api_key,
            }, f)

    def _get_platform(self) -> str:
        machine = platform.machine()
        system = platform.system().lower()
        return f'{system}_{machine}'
