"""Rolling replay buffer backed by ffmpeg.

ffmpeg continuously records the screen into short MPEG-TS segments in a tmpfs
directory. Old segments are pruned so only the last few seconds are kept. Saving
a clip byte-concatenates the newest segments and remuxes them to MP4 without
re-encoding, so it is near-instant.
"""

import ctypes
import glob
import math
import os
import re
import shutil
import signal
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from .config import RUNTIME_DIR, Config

SEGMENT_SECONDS = 2
SEGMENT_PATTERN = "seg_%08d.ts"


def _die_with_parent() -> None:
    """Run in the ffmpeg child: get SIGTERM if momentr dies, so capture never outlives it."""
    PR_SET_PDEATHSIG = 1
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


def log(msg: str) -> None:
    print(f"momentr: {msg}", flush=True)


# --- Screen geometry -------------------------------------------------------

def capture_geometry(monitor: str) -> tuple[int, int, int, int]:
    """Return (width, height, x, y) of the area to capture."""
    if monitor == "all":
        out = subprocess.run(["xdpyinfo"], capture_output=True, text=True, check=True).stdout
        w, h = map(int, re.search(r"dimensions:\s+(\d+)x(\d+)", out).groups())
        return w, h, 0, 0

    out = subprocess.run(["xrandr", "--listmonitors"], capture_output=True, text=True, check=True).stdout
    # e.g. " 0: +*eDP 1920/344x1080/194+0+0  eDP"
    line_re = re.compile(r"^\s*\d+:\s+\+?(\*?)(\S+)\s+(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)")
    monitors = []
    for line in out.splitlines():
        m = line_re.match(line)
        if m:
            primary, name, w, h, x, y = m.groups()
            monitors.append((name, bool(primary), int(w), int(h), int(x), int(y)))
    if not monitors:
        raise RuntimeError("no monitors found via xrandr")
    for name, primary, w, h, x, y in monitors:
        if (monitor and name == monitor) or (not monitor and primary):
            return w, h, x, y
    if monitor:
        raise RuntimeError(f"monitor {monitor!r} not found; available: {[m[0] for m in monitors]}")
    _, _, w, h, x, y = monitors[0]
    return w, h, x, y


# --- Encoder selection -----------------------------------------------------

def _encoder_args(kind: str, cfg: Config, device: str | None = None) -> tuple[list[str], list[str]]:
    """Return (pre-input args, output args) for an encoder."""
    gop = str(cfg.fps * SEGMENT_SECONDS)
    keyframes = ["-g", gop, "-force_key_frames", f"expr:gte(t,n_forced*{SEGMENT_SECONDS})"]
    if kind == "nvenc":
        return [], ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "ll",
                    "-b:v", cfg.bitrate, "-pix_fmt", "yuv420p", *keyframes]
    if kind == "vaapi":
        return ["-vaapi_device", device], ["-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi",
                                           "-b:v", cfg.bitrate, *keyframes]
    return [], ["-c:v", "libx264", "-preset", "superfast", "-tune", "zerolatency",
                "-crf", "23", "-maxrate", cfg.bitrate, "-bufsize", cfg.bitrate,
                "-pix_fmt", "yuv420p", *keyframes]


def _encoder_works(pre: list[str], out: list[str]) -> bool:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", *pre,
           "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30", "-frames:v", "5",
           *out, "-f", "null", "-"]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=15).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def pick_encoder(cfg: Config) -> tuple[str, list[str], list[str]]:
    candidates: list[tuple[str, str | None]] = []
    if cfg.encoder in ("auto", "nvenc"):
        candidates.append(("nvenc", None))
    if cfg.encoder in ("auto", "vaapi"):
        candidates += [("vaapi", d) for d in sorted(glob.glob("/dev/dri/renderD*"))]
    if cfg.encoder in ("auto", "x264"):
        candidates.append(("x264", None))

    for kind, device in candidates:
        pre, out = _encoder_args(kind, cfg, device)
        if _encoder_works(pre, out):
            return (f"{kind} ({device})" if device else kind), pre, out
    raise RuntimeError(f"no working encoder found for encoder={cfg.encoder!r}")


# --- Replay buffer ---------------------------------------------------------

class ReplayBuffer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.buffer_dir = RUNTIME_DIR / "buffer"
        self.proc: subprocess.Popen | None = None
        self.encoder_name = ""
        self._enc_pre: list[str] = []
        self._enc_out: list[str] = []
        self._stop = threading.Event()
        self._paused = False
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def keep_segments(self) -> int:
        # Whole segments needed to cover the clip, plus the one being written. Read from
        # cfg each time so settings that don't affect capture can be swapped in live.
        return math.ceil(self.cfg.clip_seconds / SEGMENT_SECONDS) + 2

    # lifecycle

    def start(self) -> None:
        self.encoder_name, self._enc_pre, self._enc_out = pick_encoder(self.cfg)
        log(f"using encoder {self.encoder_name}")
        self._stop.clear()
        self._thread = threading.Thread(target=self._supervise, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._kill_ffmpeg()
        if self._thread:
            self._thread.join(timeout=5)
        shutil.rmtree(self.buffer_dir, ignore_errors=True)

    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused
            if paused:
                self._kill_ffmpeg()
                shutil.rmtree(self.buffer_dir, ignore_errors=True)

    # internals

    def _build_cmd(self) -> list[str]:
        w, h, x, y = capture_geometry(self.cfg.monitor)
        display = os.environ.get("DISPLAY", ":0")
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin", *self._enc_pre,
               "-thread_queue_size", "1024", "-f", "x11grab",
               "-framerate", str(self.cfg.fps), "-video_size", f"{w}x{h}",
               "-draw_mouse", "1" if self.cfg.draw_mouse else "0",
               "-i", f"{display}+{x},{y}"]
        if self.cfg.audio:
            cmd += ["-thread_queue_size", "1024", "-f", "pulse", "-i", "@DEFAULT_MONITOR@"]
        cmd += self._enc_out
        if self.cfg.audio:
            cmd += ["-c:a", "aac", "-b:a", "160k"]
        cmd += ["-f", "segment", "-segment_time", str(SEGMENT_SECONDS),
                "-segment_format", "mpegts", str(self.buffer_dir / SEGMENT_PATTERN)]
        return cmd

    def _spawn(self) -> None:
        shutil.rmtree(self.buffer_dir, ignore_errors=True)
        self.buffer_dir.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(self._build_cmd(), preexec_fn=_die_with_parent)

    def _kill_ffmpeg(self) -> None:
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _supervise(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            with self._lock:
                if not self._paused and (self.proc is None or self.proc.poll() is not None):
                    if self.proc is not None:
                        log(f"ffmpeg exited with code {self.proc.returncode}; restarting in {backoff:.0f}s")
                        self.proc = None
                        self._stop.wait(backoff)
                        backoff = min(backoff * 2, 30)
                        continue
                    try:
                        self._spawn()
                    except Exception as e:  # geometry lookup, missing ffmpeg, ...
                        log(f"failed to start capture: {e}")
                        self._stop.wait(backoff)
                        backoff = min(backoff * 2, 30)
                        continue
                if self.proc and self.proc.poll() is None:
                    backoff = 1.0
                self._prune()
            self._stop.wait(1)

    def _segments(self) -> list[Path]:
        return sorted(self.buffer_dir.glob("seg_*.ts"))

    def _prune(self) -> None:
        segs = self._segments()
        for seg in segs[:-self.keep_segments]:
            seg.unlink(missing_ok=True)

    # saving

    def save_clip(self) -> Path:
        """Write the last `clip_seconds` of the buffer to an MP4 and return its path."""
        with self._lock:
            if self._paused:
                raise RuntimeError("replay buffer is paused")
            segs = self._segments()
            if not segs:
                raise RuntimeError("buffer is empty (capture just started?)")
            # Newest segment is still being written; include it so the clip ends "now".
            wanted = math.ceil(self.cfg.clip_seconds / SEGMENT_SECONDS) + 1
            chosen = segs[-wanted:]
            # Snapshot into one file so pruning can't delete segments mid-remux.
            snapshot = RUNTIME_DIR / f"snapshot_{os.getpid()}.ts"
            with snapshot.open("wb") as out:
                for seg in chosen:
                    with seg.open("rb") as f:
                        shutil.copyfileobj(f, out)

        out_dir = self.cfg.output_path
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"clip_{datetime.now():%Y-%m-%d_%H-%M-%S}.mp4"
        try:
            # Trim from the end so the clip is close to clip_seconds (cuts land on keyframes).
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-sseof", f"-{self.cfg.clip_seconds}", "-i", str(snapshot),
                 "-c", "copy", "-movflags", "+faststart", str(dest)],
                capture_output=True, text=True,
            )
        finally:
            snapshot.unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg remux failed: {result.stderr.strip()}")
        return dest
