import requests
import json
import os
import platform
from dataclasses import dataclass
from typing import Optional, List, Dict


STATE_FILE = os.path.expanduser('~/.scannerintel/state.json')


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
            facility = AssignedFacility(
                frequency_hz=af.get('frequency_hz'),
                stream_key=af.get('stream_key'),
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
                       segment_bytes: bytes, duration_ms: int) -> bool:
        """Upload an HLS segment. Returns True on success."""
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
