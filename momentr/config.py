"""User configuration, stored as TOML in ~/.config/momentr/config.toml."""

import os
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
