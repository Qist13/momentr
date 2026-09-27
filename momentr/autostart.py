"""Start Momentr at login via an XDG autostart entry."""

import os
import sys
from pathlib import Path

AUTOSTART_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
DESKTOP_FILE = AUTOSTART_DIR / "momentr.desktop"


def is_enabled() -> bool:
    return DESKTOP_FILE.exists()


def enable() -> None:
    # Launch through this interpreter so the entry works from the venv without activating it.
    exec_line = f'"{sys.executable}" -m momentr'
    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Momentr\n"
        "Comment=Instant-replay screen clipper\n"
        f"Exec={exec_line}\n"
        "Icon=camera-video\n"
        "Terminal=false\n"
        # Give the panel and tray host a moment to come up first.
        "X-GNOME-Autostart-Delay=5\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def disable() -> None:
    DESKTOP_FILE.unlink(missing_ok=True)


def set_enabled(enabled: bool) -> None:
    enable() if enabled else disable()
