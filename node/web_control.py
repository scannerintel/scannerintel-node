"""
Local testing web UI for ScannerIntel Node.
NOT FOR PRODUCTION -- development and debugging only.
"""

import json
import subprocess
import threading
from collections import deque

from flask import Flask, render_template_string, request, jsonify

from logger import get_logger

log = get_logger('web_control')

# Circular buffer for recent log lines
_log_lines = deque(maxlen=20)
_streamer_ref = None
_config_ref = None
_current_gain = 0
_current_squelch = 0.0

HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>ScannerIntel Node Control</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0a0a0a; color: #e0e0e0; padding: 20px; }
  .banner { background: #b91c1c; color: white; text-align: center;
            padding: 12px; font-weight: 700; font-size: 14px;
            letter-spacing: 1px; margin-bottom: 24px; border-radius: 4px; }
  .card { background: #1a1a1a; border: 1px solid #333; border-radius: 8px;
          padding: 20px; margin-bottom: 16px; }
  h2 { font-size: 16px; color: #888; text-transform: uppercase;
       letter-spacing: 1px; margin-bottom: 12px; }
  .stat { display: flex; justify-content: space-between; padding: 8px 0;
          border-bottom: 1px solid #222; }
  .stat:last-child { border-bottom: none; }
  .stat-label { color: #888; }
  .stat-value { color: #4ade80; font-family: monospace; font-size: 15px; }
  .controls { display: flex; gap: 12px; margin-top: 16px; }
  .btn { padding: 10px 24px; border: none; border-radius: 6px; cursor: pointer;
         font-size: 14px; font-weight: 600; }
  .btn-start { background: #16a34a; color: white; }
  .btn-stop { background: #dc2626; color: white; }
  .btn:hover { opacity: 0.85; }
  form { margin-top: 12px; }
  label { display: block; color: #888; font-size: 13px; margin-top: 10px; }
  input, select { background: #111; border: 1px solid #444; color: #e0e0e0;
                  padding: 8px 12px; border-radius: 4px; width: 100%;
                  margin-top: 4px; font-size: 14px; }
  .btn-submit { background: #2563eb; color: white; margin-top: 16px; width: 100%; }
  .log-box { background: #000; border: 1px solid #333; border-radius: 6px;
             padding: 12px; font-family: monospace; font-size: 12px;
             line-height: 1.6; max-height: 400px; overflow-y: auto;
             white-space: pre-wrap; word-break: break-all; color: #aaa; }
  .status-active { color: #4ade80; }
  .status-stopped { color: #f87171; }
</style>
</head>
<body>
  <div class="banner">LOCAL TESTING TOOL &mdash; NOT FOR PRODUCTION</div>

  <div class="card">
    <h2>Node Status</h2>
    <div class="stat">
      <span class="stat-label">Frequency</span>
      <span class="stat-value" id="freq">{{ frequency }}</span>
    </div>
    <div class="stat">
      <span class="stat-label">Modulation</span>
      <span class="stat-value" id="mod">{{ modulation }}</span>
    </div>
    <div class="stat">
      <span class="stat-label">Gain</span>
      <span class="stat-value" id="gain">{{ gain }}</span>
    </div>
    <div class="stat">
      <span class="stat-label">Squelch</span>
      <span class="stat-value" id="squelch">{{ squelch }} dBm</span>
    </div>
    <div class="stat">
      <span class="stat-label">Stream</span>
      <span class="stat-value" id="stream-status">
        <span class="{{ 'status-active' if running else 'status-stopped' }}">
          {{ 'Active' if running else 'Stopped' }}
        </span>
      </span>
    </div>
    <div class="controls">
      <button class="btn btn-start" onclick="doAction('start')">Start</button>
      <button class="btn btn-stop" onclick="doAction('stop')">Stop</button>
    </div>
  </div>

  <div class="card">
    <h2>Retune</h2>
    <form id="retune-form" onsubmit="return doRetune(event)">
      <label>Frequency (Hz)
        <input type="number" id="new-freq" value="{{ frequency_hz }}" step="1000">
      </label>
      <label>Modulation
        <select id="new-mod">
          <option value="am" {{ 'selected' if modulation == 'AM' else '' }}>AM</option>
          <option value="fm" {{ 'selected' if modulation == 'FM' else '' }}>FM</option>
        </select>
      </label>
      <button type="submit" class="btn btn-submit">Apply</button>
    </form>
  </div>

  <div class="card">
    <h2>Logs</h2>
    <div class="log-box" id="log-box">Loading...</div>
  </div>

<script>
function doAction(action) {
  fetch('/api/' + action, { method: 'POST' })
    .then(r => r.json())
    .then(d => { if (d.error) alert(d.error); else location.reload(); });
}

function doRetune(e) {
  e.preventDefault();
  const freq = document.getElementById('new-freq').value;
  const mod = document.getElementById('new-mod').value;
  fetch('/api/retune', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({frequency_hz: parseInt(freq), modulation: mod})
  }).then(r => r.json())
    .then(d => { if (d.error) alert(d.error); else location.reload(); });
  return false;
}

function refreshLogs() {
  fetch('/api/logs')
    .then(r => r.json())
    .then(d => {
      const box = document.getElementById('log-box');
      box.textContent = d.lines.join('\\n');
      box.scrollTop = box.scrollHeight;
    });
}

setInterval(refreshLogs, 2000);
refreshLogs();
</script>
</body>
</html>"""


def create_app():
    app = Flask(__name__)

    @app.route('/')
    def index():
        streamer = _streamer_ref
        running = streamer is not None and streamer._running
        freq_hz = streamer.frequency_hz if streamer else 0
        freq_mhz = freq_hz / 1e6 if freq_hz else 0
        mod = (streamer.modulation if streamer else 'am').upper()

        return render_template_string(
            HTML_PAGE,
            frequency=f"{freq_mhz:.3f} MHz",
            frequency_hz=freq_hz,
            modulation=mod,
            gain=_current_gain,
            squelch=f"{_current_squelch:.1f}",
            running=running,
        )

    @app.route('/api/logs')
    def api_logs():
        return jsonify(lines=list(_log_lines))

    @app.route('/api/stop', methods=['POST'])
    def api_stop():
        if _streamer_ref and _streamer_ref._running:
            _streamer_ref._running = False
            _streamer_ref._stop_pipeline()
            _log_lines.append("Stream stopped via web control")
            return jsonify(ok=True)
        return jsonify(error="Not running")

    @app.route('/api/start', methods=['POST'])
    def api_start():
        if _streamer_ref and not _streamer_ref._running:
            _streamer_ref._running = True
            t = threading.Thread(target=_restart_stream, daemon=True)
            t.start()
            _log_lines.append("Stream started via web control")
            return jsonify(ok=True)
        return jsonify(error="Already running")

    @app.route('/api/retune', methods=['POST'])
    def api_retune():
        data = request.get_json()
        freq = data.get('frequency_hz')
        mod = data.get('modulation', 'am')

        if not freq:
            return jsonify(error="frequency_hz required")

        streamer = _streamer_ref
        if not streamer:
            return jsonify(error="No streamer active")

        # Stop current pipeline
        streamer._running = False
        streamer._stop_pipeline()

        # Update frequency and modulation
        streamer.frequency_hz = int(freq)
        streamer.modulation = mod
        streamer._running = True

        _log_lines.append(f"Retuned to {int(freq)} Hz {mod.upper()}")

        t = threading.Thread(target=_restart_stream, daemon=True)
        t.start()

        return jsonify(ok=True, frequency_hz=int(freq), modulation=mod)

    return app


def _restart_stream():
    """Restart the streaming pipeline in a background thread."""
    import os
    import shutil

    streamer = _streamer_ref
    if not streamer:
        return

    os.makedirs(streamer.tmp_dir, exist_ok=True)

    try:
        streamer._start_pipeline()
        streamer._watch_segments()
    finally:
        streamer._stop_pipeline()
        if os.path.exists(streamer.tmp_dir):
            shutil.rmtree(streamer.tmp_dir, ignore_errors=True)


def start_web_control(streamer, config, gain, squelch):
    """Entry point called from main.py in a daemon thread."""
    global _streamer_ref, _config_ref, _current_gain, _current_squelch
    _streamer_ref = streamer
    _config_ref = config
    _current_gain = gain
    _current_squelch = squelch

    app = create_app()
    app.run(host='0.0.0.0', port=8080, use_reloader=False)
