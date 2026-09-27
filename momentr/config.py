"""User configuration, stored as TOML in ~/.config/momentr/config.toml."""

import os
import re
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "momentr"
CONFIG_PATH = CONFIG_DIR / "config.toml"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "momentr"

DEFAULT_CONFIG = """\
# Momentr configuration

# How many seconds each saved clip covers.
clip_seconds = 30

# Global hotkey that saves a clip (pynput syntax).
hotkey = "<ctrl>+<alt>+s"

# Where clips are written.
output_dir = "~/Videos/Momentr"

# Capture settings.
fps = 60
# "" = primary monitor, "all" = whole X screen, or a monitor name from `xrandr --listmonitors`.
monitor = ""
draw_mouse = true

# Encoder: "auto", "nvenc", "vaapi" or "x264".
encoder = "auto"
bitrate = "12M"

# Record desktop audio (what you hear).
audio = true

# Play a shutter sound when a clip is saved.
sound = true

# Automatic cleanup of old clips (0 = off). Only auto-named clips
# (clip_YYYY-MM-DD_HH-MM-SS.mp4) are deleted; rename a clip to keep it forever.
keep_clips = 0
keep_days = 0
"""


@dataclass
class Config:
    clip_seconds: int = 30
    hotkey: str = "<ctrl>+<alt>+s"
    output_dir: str = "~/Videos/Momentr"
    fps: int = 60
    monitor: str = ""
    draw_mouse: bool = True
    encoder: str = "auto"
    bitrate: str = "12M"
    audio: bool = True
    sound: bool = True
    keep_clips: int = 0
    keep_days: int = 0

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir).expanduser()


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(DEFAULT_CONFIG)
    with CONFIG_PATH.open("rb") as f:
        data = tomllib.load(f)
    known = {f.name for f in fields(Config)}
    unknown = set(data) - known
    if unknown:
        print(f"momentr: ignoring unknown config keys: {', '.join(sorted(unknown))}")
    return Config(**{k: v for k, v in data.items() if k in known})


# Changing these means restarting ffmpeg; everything else applies instantly.
CAPTURE_KEYS = ("fps", "monitor", "draw_mouse", "encoder", "bitrate", "audio")


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_config_value(key: str, value) -> None:
    """Rewrite one key in the config file, keeping the user's comments and layout."""
    text = CONFIG_PATH.read_text()
    line = f"{key} = {_toml_value(value)}"
    pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(lambda _: line, text, count=1)
    else:
        text = text.rstrip("\n") + f"\n{line}\n"
    CONFIG_PATH.write_text(text)
