"""On-screen "clip saved" toast, shown near the top-left of the captured monitor.

Runs as its own short-lived process (`python -m momentr.overlay X Y TITLE DETAIL`) so
Tk never shares a thread or main loop with the tray icon's GTK loop.
"""

import subprocess
import sys

MARGIN = 24
SHOW_MS = 2500
SLIDE_MS = 250
FRAME_MS = 10

BG = "#1e1e1e"
ACCENT = "#e63232"
FG = "#ffffff"
FG_DIM = "#b4b4b4"


def show_toast(x: int, y: int, title: str, detail: str = "") -> None:
    """Spawn the toast without blocking; (x, y) is the monitor's top-left corner."""
    subprocess.Popen([sys.executable, "-m", "momentr.overlay", str(x), str(y), title, detail],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _run(x: int, y: int, title: str, detail: str) -> None:
    import tkinter as tk

    root = tk.Tk()
    root.overrideredirect(True)  # no title bar or border
    root.attributes("-topmost", True)
    try:
        root.attributes("-type", "notification")  # keeps it out of the taskbar and alt-tab
    except tk.TclError:
        pass
    root.configure(bg=ACCENT)

    # A thin red stripe on the left (the root's background) next to the dark card.
    card = tk.Frame(root, bg=BG, padx=16, pady=10)
    card.pack(side="left", fill="both", padx=(4, 0))
    tk.Label(card, text="● " + title, bg=BG, fg=FG, font=("Sans", 12, "bold"),
             anchor="w").pack(fill="x")
    if detail:
        tk.Label(card, text=detail, bg=BG, fg=FG_DIM, font=("Sans", 9), anchor="w").pack(fill="x")

    # Start just off the monitor's left edge, slide in, wait, then slide back out.
    root.update_idletasks()
    hidden_x = x - root.winfo_reqwidth()
    shown_x = x + MARGIN
    top = y + MARGIN
    root.geometry(f"+{hidden_x}+{top}")
    root.bind("<Button-1>", lambda _: root.destroy())

    def slide(start: int, end: int, then, frame: int = 0) -> None:
        frames = max(1, SLIDE_MS // FRAME_MS)
        t = min(1.0, frame / frames)
        eased = 1 - (1 - t) ** 3 if end > start else t ** 3  # ease out going in, ease in going out
        root.geometry(f"+{round(start + (end - start) * eased)}+{top}")
        if t < 1.0:
            root.after(FRAME_MS, slide, start, end, then, frame + 1)
        else:
            then()

    def slide_out() -> None:
        slide(shown_x, hidden_x, root.destroy)

    root.after(0, slide, hidden_x, shown_x, lambda: root.after(SHOW_MS, slide_out))
    root.mainloop()


if __name__ == "__main__":
    _run(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "")
