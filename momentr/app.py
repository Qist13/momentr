"""Tray icon, global hotkey and notifications around the replay buffer."""

import os
import shutil
import signal
import subprocess
import threading
from pathlib import Path

from . import autostart
from .cleanup import prune_clips
from .config import CAPTURE_KEYS, CONFIG_PATH, RUNTIME_DIR, Config, load_config, set_config_value
from .recorder import ReplayBuffer, log

PID_FILE = RUNTIME_DIR / "momentr.pid"
SHUTTER_SOUND = Path("/usr/share/sounds/freedesktop/stereo/camera-shutter.oga")
CLIP_LENGTHS = (15, 30, 60, 120)
KEEP_COUNTS = (0, 25, 50, 100)  # 0 = forever


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


def config_mtime() -> float:
    try:
        return CONFIG_PATH.stat().st_mtime
    except FileNotFoundError:
        return 0.0


class App:
    def __init__(self, cfg: Config, tray: bool = True):
        self.cfg = cfg
        self.use_tray = tray
        self.buffer = ReplayBuffer(cfg)
        self.icon = None
        self.hotkeys = None
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
                self.cleanup()
            except Exception as e:
                notify("Couldn't save clip", str(e), icon="dialog-error")
            finally:
                self._saving.release()

        threading.Thread(target=work, daemon=True).start()

    def toggle_pause(self) -> None:
        self.buffer.set_paused(not self.buffer.paused)
        state = "paused" if self.buffer.paused else "recording"
        notify(f"Replay buffer {state}")
        self._refresh_tray()

    def cleanup(self) -> None:
        deleted = prune_clips(self.cfg.output_path, self.cfg.keep_clips, self.cfg.keep_days)
        if deleted:
            log(f"deleted {len(deleted)} old clip(s): {', '.join(p.name for p in deleted)}")

    def set_keep_clips(self, count: int) -> None:
        set_config_value("keep_clips", count)

    def set_clip_length(self, seconds: int) -> None:
        # The config watcher picks this up and applies it.
        set_config_value("clip_seconds", seconds)

    def toggle_autostart(self) -> None:
        autostart.set_enabled(not autostart.is_enabled())
        notify("Start at login " + ("enabled" if autostart.is_enabled() else "disabled"))
        self._refresh_tray()

    def open_folder(self) -> None:
        self.cfg.output_path.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(self.cfg.output_path)])

    def open_config(self) -> None:
        subprocess.Popen(["xdg-open", str(CONFIG_PATH)])

    def quit(self) -> None:
        self._quit.set()
        if self.icon:
            self.icon.stop()

    # settings

    def _start_hotkeys(self) -> None:
        from pynput import keyboard

        if self.hotkeys:
            self.hotkeys.stop()
        self.hotkeys = keyboard.GlobalHotKeys({self.cfg.hotkey: self.save_clip})
        self.hotkeys.start()

    def _watch_config(self) -> None:
        last = config_mtime()
        while not self._quit.wait(1):
            mtime = config_mtime()
            if mtime != last:
                last = mtime
                self._apply_config()

    def _apply_config(self) -> None:
        try:
            new = load_config()
        except Exception as e:
            notify("Settings not applied", f"config.toml has an error: {e}", icon="dialog-error")
            return
        old = self.cfg
        if new == old:
            return

        if new.hotkey != old.hotkey:
            try:
                self.cfg = new
                self._start_hotkeys()
            except Exception as e:
                notify("Bad hotkey", f"{new.hotkey!r}: {e}; keeping {old.hotkey}", icon="dialog-error")
                new.hotkey = old.hotkey
                self.cfg = new
                self._start_hotkeys()

        self.cfg = new
        if any(getattr(new, k) != getattr(old, k) for k in CAPTURE_KEYS):
            paused = self.buffer.paused
            self.buffer.stop()
            self.buffer = ReplayBuffer(new)
            try:
                self.buffer.start()
            except Exception as e:
                notify("Couldn't restart capture", str(e), icon="dialog-error")
                return
            if paused:
                self.buffer.set_paused(True)
            notify("Settings applied", f"Capture restarted (encoder: {self.buffer.encoder_name})")
        else:
            self.buffer.cfg = new
            notify("Settings applied")
        self.cleanup()
        self._refresh_tray()

    # run

    def run(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))
        signal.signal(signal.SIGUSR1, lambda *_: self.save_clip())
        signal.signal(signal.SIGTERM, lambda *_: self.quit())
        signal.signal(signal.SIGINT, lambda *_: self.quit())

        self._start_hotkeys()
        self.buffer.start()
        self.cleanup()
        threading.Thread(target=self._watch_config, daemon=True).start()
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
            self._quit.set()
            self.hotkeys.stop()
            self.buffer.stop()
            PID_FILE.unlink(missing_ok=True)

    def _refresh_tray(self) -> None:
        if self.icon:
            self.icon.icon = make_icon(self.buffer.paused)
            self.icon.update_menu()

    def _run_tray(self) -> None:
        import pystray
        from pystray import Menu, MenuItem as Item

        def length_item(seconds: int) -> Item:
            return Item(f"{seconds}s", lambda: self.set_clip_length(seconds),
                        checked=lambda _: self.cfg.clip_seconds == seconds, radio=True)

        def keep_item(count: int) -> Item:
            return Item("Forever" if count == 0 else f"Last {count}",
                        lambda: self.set_keep_clips(count),
                        checked=lambda _: self.cfg.keep_clips == count, radio=True)

        menu = Menu(
            Item(lambda _: f"Save last {self.cfg.clip_seconds}s", lambda: self.save_clip(), default=True),
            Item(lambda _: "Resume buffer" if self.buffer.paused else "Pause buffer",
                 lambda: self.toggle_pause()),
            Menu.SEPARATOR,
            Item("Clip length", Menu(*(length_item(s) for s in CLIP_LENGTHS))),
            Item("Keep clips", Menu(*(keep_item(c) for c in KEEP_COUNTS))),
            Item("Start at login", lambda: self.toggle_autostart(),
                 checked=lambda _: autostart.is_enabled()),
            Item("Edit all settings…", lambda: self.open_config()),
            Menu.SEPARATOR,
            Item("Open clips folder", lambda: self.open_folder()),
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
