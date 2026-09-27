import argparse
import os
import sys

SNAP_ORIG_SUFFIX = "_VSCODE_SNAP_ORIG"


def undo_snap_env() -> None:
    """Terminals opened from the VS Code snap point GTK at the snap's own libraries,
    which crash the tray icon. Restore the values the snap saved before overriding."""
    for key in [k for k in os.environ if k.endswith(SNAP_ORIG_SUFFIX)]:
        name, orig = key[: -len(SNAP_ORIG_SUFFIX)], os.environ.pop(key)
        if orig:
            os.environ[name] = orig
        else:
            os.environ.pop(name, None)


def main() -> int:
    undo_snap_env()
    parser = argparse.ArgumentParser(prog="momentr", description="Instant-replay screen clipper.")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="start the replay buffer (default)")
    run.add_argument("--no-tray", action="store_true", help="run without a tray icon")
    sub.add_parser("save", help="tell a running momentr to save a clip")
    auto = sub.add_parser("autostart", help="start momentr when you log in")
    auto.add_argument("state", choices=["on", "off"])
    args = parser.parse_args()

    if args.command == "autostart":
        from . import autostart
        autostart.set_enabled(args.state == "on")
        print(f"momentr: start at login {'enabled' if args.state == 'on' else 'disabled'}")
        return 0

    if args.command == "save":
        from .app import send_save_signal
        return send_save_signal()

    from .app import App
    from .config import load_config

    App(load_config(), tray=not getattr(args, "no_tray", False)).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
