import json
import sys
from datetime import datetime, timezone


class StructuredLogger:
    def __init__(self, name: str):
        self.name = name

    def _write(self, level: str, message: str, **kwargs):
        entry = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'level': level,
            'logger': self.name,
            'msg': message,
            **kwargs,
        }
        print(json.dumps(entry), flush=True)

    def info(self, msg: str, **kwargs):
        self._write('INFO', msg, **kwargs)

    def debug(self, msg: str, **kwargs):
        self._write('DEBUG', msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        self._write('WARN', msg, **kwargs)

    def error(self, msg: str, **kwargs):
        self._write('ERROR', msg, **kwargs)


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(name)
