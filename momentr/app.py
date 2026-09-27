"""Tray icon, global hotkey and notifications around the replay buffer."""

import os
import shutil
import signal
import subprocess
import threading
from pathlib import Path

from .config import CONFIG_PATH, RUNTIME_DIR, Config
from .recorder import ReplayBuffer, log

PID_FILE = RUNTIME_DIR / "momentr.pid"
SHUTTER_SOUND = Path("/usr/share/sounds/freedesktop/stereo/camera-shutter.oga")


def notify(summary: str, body: str = "", icon: str = "camera-video") -> None:
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "Momentr", "-i", icon, summary, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log(f"{summary} {body}".strip())


def play_shutter() -> None:
    player = shutil.which("pw-play") or shutil.which("paplay")
    if player and SHUTTER_SOUND.exists():
        subprocess.Popen([player, str(SHUTTER_SOUND)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_icon(paused: bool):
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, size - 4, size - 4), fill=(40, 40, 40, 255))
    color = (150, 150, 150, 255) if paused else (230, 50, 50, 255)
    d.ellipse((18, 18, size - 18, size - 18), fill=color)
    return img


class App:
    def __init__(self, cfg: Config, tray: bool = True):
        self.cfg = cfg
        self.use_tray = tray
        self.buffer = ReplayBuffer(cfg)
        self.icon = None
        self._saving = threading.Lock()
        self._quit = threading.Event()

    # actions

    def save_clip(self) -> None:
        # Run off the hotkey/signal thread; ignore presses while a save is in flight.
        if not self._saving.acquire(blocking=False):
            return

        def work():
            try:
                path = self.buffer.save_clip()
                if self.cfg.sound:
                    play_shutter()
                notify("Clip saved", str(path))
            except Exception as e:
                notify("Couldn't save clip", str(e), icon="dialog-error")
            finally:
                self._saving.release()

        threading.Thread(target=work, daemon=True).start()

    def toggle_pause(self) -> None:
        self.buffer.set_paused(not self.buffer.paused)
        state = "paused" if self.buffer.paused else "recording"
        notify(f"Replay buffer {state}")
        if self.icon:
            self.icon.icon = make_icon(self.buffer.paused)
            self.icon.update_menu()

    def open_folder(self) -> None:
        self.cfg.output_path.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(self.cfg.output_path)])

    def open_config(self) -> None:
        subprocess.Popen(["xdg-open", str(CONFIG_PATH)])

    def quit(self) -> None:
        self._quit.set()
        if self.icon:
            self.icon.stop()

    # run

    def run(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))
        signal.signal(signal.SIGUSR1, lambda *_: self.save_clip())
        signal.signal(signal.SIGTERM, lambda *_: self.quit())
        signal.signal(signal.SIGINT, lambda *_: self.quit())

        from pynput import keyboard

        hotkeys = keyboard.GlobalHotKeys({self.cfg.hotkey: self.save_clip})
        hotkeys.start()
        self.buffer.start()
        notify("Momentr is running",
               f"Press {self.cfg.hotkey} to save the last {self.cfg.clip_seconds}s "
               f"(encoder: {self.buffer.encoder_name})")
        try:
            if self.use_tray:
                self._run_tray()
            else:
                while not self._quit.wait(0.5):
                    pass
        finally:
            hotkeys.stop()
            self.buffer.stop()
            PID_FILE.unlink(missing_ok=True)

    def _run_tray(self) -> None:
        import pystray
        from pystray import Menu, MenuItem as Item

        menu = Menu(
            Item(f"Save last {self.cfg.clip_seconds}s", lambda: self.save_clip(), default=True),
            Item(lambda _: "Resume buffer" if self.buffer.paused else "Pause buffer",
                 lambda: self.toggle_pause()),
            Menu.SEPARATOR,
            Item("Open clips folder", lambda: self.open_folder()),
            Item("Edit settings", lambda: self.open_config()),
            Menu.SEPARATOR,
            Item("Quit", lambda: self.quit()),
        )
        self.icon = pystray.Icon("momentr", make_icon(False), "Momentr", menu)
        self.icon.run()


def send_save_signal() -> int:
    try:
        pid = int(PID_FILE.read_text())
        os.kill(pid, signal.SIGUSR1)
    except (FileNotFoundError, ValueError, ProcessLookupError):
        print("momentr: not running")
        return 1
    return 0
