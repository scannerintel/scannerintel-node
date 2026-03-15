import json
import sys
import threading
from datetime import datetime, timezone


class StructuredLogger:
    """Structured JSON logger that also buffers entries for remote shipping."""

    # Class-level buffer shared by all loggers
    _buffer = []
    _lock = threading.Lock()
    _max_buffer = 500

    def __init__(self, name: str):
        self.name = name

    def _write(self, level: str, message: str, **kwargs):
        entry = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'level': level,
            'logger': self.name,
            'msg': message,
        }

        # Separate metadata from core fields
        metadata = {}
        for k, v in kwargs.items():
            metadata[k] = v

        # Always print to stdout
        out = {**entry}
        if metadata:
            out.update(metadata)
        print(json.dumps(out), flush=True)

        # Buffer for remote shipping
        if metadata:
            entry['metadata'] = metadata
        with StructuredLogger._lock:
            StructuredLogger._buffer.append(entry)
            # Drop oldest if buffer is full
            if len(StructuredLogger._buffer) > StructuredLogger._max_buffer:
                StructuredLogger._buffer = StructuredLogger._buffer[-StructuredLogger._max_buffer:]

    def info(self, msg: str, **kwargs):
        self._write('INFO', msg, **kwargs)

    def debug(self, msg: str, **kwargs):
        self._write('DEBUG', msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        self._write('WARN', msg, **kwargs)

    def error(self, msg: str, **kwargs):
        self._write('ERROR', msg, **kwargs)

    @classmethod
    def drain(cls):
        """Return and clear all buffered log entries."""
        with cls._lock:
            entries = cls._buffer[:]
            cls._buffer = []
        return entries


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(name)
