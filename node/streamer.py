import os
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone

from logger import get_logger
from uploader import Uploader

log = get_logger('streamer')


class Streamer:
    def __init__(self, stream_key: str, frequency_hz: int, modulation: str,
                 device_index: int, gain: float, server_url: str,
                 api_key: str, uploader: Uploader):
        self.stream_key = stream_key
        self.frequency_hz = frequency_hz
        self.modulation = modulation
        self.device_index = device_index
        self.gain = gain
        self.server_url = server_url
        self.api_key = api_key
        self.uploader = uploader
        self.tmp_dir = f'/tmp/sis_{stream_key}'
        self._running = True
        self._rtl_proc = None
        self._ffmpeg_proc = None

    def run(self):
        """Block until SIGINT/SIGTERM. Streams radio -> HLS -> server."""
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        os.makedirs(self.tmp_dir, exist_ok=True)

        try:
            self._start_pipeline()
            self._watch_segments()
        finally:
            self._stop_pipeline()
            if os.path.exists(self.tmp_dir):
                shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _handle_signal(self, sig, frame):
        log.info("Shutdown signal received")
        self._running = False

    def _start_pipeline(self):
        """Launch rtl_fm piped into ffmpeg."""
        gain_str = str(self.gain) if self.gain != 'auto' else '0'

        rtl_cmd = [
            'rtl_fm',
            '-d', str(self.device_index),
            '-f', str(self.frequency_hz),
            '-M', self.modulation,
            '-s', '200000',
            '-r', '48000',
            '-g', gain_str,
            '-',
        ]

        ffmpeg_cmd = [
            'ffmpeg',
            '-hide_banner', '-loglevel', 'warning',
            '-f', 's16le',
            '-ar', '48000',
            '-ac', '1',
            '-i', 'pipe:0',
            '-codec:a', 'aac',
            '-b:a', '32k',
            '-f', 'hls',
            '-hls_time', '10',
            '-hls_list_size', '10',
            '-hls_flags', 'delete_segments+append_list',
            os.path.join(self.tmp_dir, 'playlist.m3u8'),
        ]

        log.info("Starting rtl_fm",
                 frequency_hz=self.frequency_hz,
                 modulation=self.modulation,
                 device_index=self.device_index)

        self._rtl_proc = subprocess.Popen(
            rtl_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        log.info("Starting ffmpeg HLS segmenter")

        self._ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=self._rtl_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Allow rtl_fm to receive SIGPIPE if ffmpeg dies
        self._rtl_proc.stdout.close()

    def _watch_segments(self):
        """Poll temp dir for new .ts files and upload them."""
        uploaded = set()
        segment_index = 0
        freq_mhz = self.frequency_hz / 1e6

        log.info("Watching for HLS segments", tmp_dir=self.tmp_dir)

        while self._running:
            # Check if pipeline processes are still alive
            if self._rtl_proc.poll() is not None:
                log.error("rtl_fm exited unexpectedly",
                          returncode=self._rtl_proc.returncode)
                break
            if self._ffmpeg_proc.poll() is not None:
                log.error("ffmpeg exited unexpectedly",
                          returncode=self._ffmpeg_proc.returncode)
                break

            try:
                files = os.listdir(self.tmp_dir)
            except FileNotFoundError:
                time.sleep(2)
                continue

            ts_files = sorted(f for f in files
                              if f.endswith('.ts') and f not in uploaded)

            for ts_file in ts_files:
                ts_path = os.path.join(self.tmp_dir, ts_file)
                try:
                    with open(ts_path, 'rb') as f:
                        segment_bytes = f.read()
                except (FileNotFoundError, PermissionError):
                    continue

                if not segment_bytes:
                    continue

                success = self.uploader.upload_segment(
                    stream_key=self.stream_key,
                    segment_index=segment_index,
                    segment_bytes=segment_bytes,
                    duration_ms=10000,
                )

                ts_now = datetime.now(timezone.utc).isoformat()
                if success:
                    log.info("Segment uploaded",
                             frequency_mhz=f"{freq_mhz:.3f}",
                             segment_index=segment_index,
                             timestamp=ts_now)
                else:
                    log.warning("Segment upload failed",
                                frequency_mhz=f"{freq_mhz:.3f}",
                                segment_index=segment_index,
                                timestamp=ts_now)

                uploaded.add(ts_file)
                segment_index += 1

            time.sleep(2)

    def _stop_pipeline(self):
        """Terminate rtl_fm and ffmpeg cleanly."""
        for name, proc in [('ffmpeg', self._ffmpeg_proc),
                           ('rtl_fm', self._rtl_proc)]:
            if proc and proc.poll() is None:
                log.info(f"Stopping {name}", pid=proc.pid)
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

        log.info("Pipeline stopped")
