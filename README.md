# Momentr

Instant-replay screen clipper for Linux (X11). Momentr keeps the last few seconds of
your screen and desktop audio in a rolling buffer in RAM. Press a hotkey and the last
30 seconds are saved as an MP4.

## How it works

- ffmpeg records the screen (`x11grab`) and desktop audio (`@DEFAULT_MONITOR@`) into
  2-second MPEG-TS segments in `$XDG_RUNTIME_DIR/momentr/buffer` (tmpfs). Old
  segments are deleted as new ones arrive.
- Saving a clip joins the newest segments and remuxes them to MP4 without
  re-encoding, so a save takes well under a second.
- The encoder is picked automatically: NVENC, then VAAPI (each `/dev/dri/renderD*`),
  then libx264 on the CPU.

## Install

Requires `ffmpeg`, `xrandr`, `xdpyinfo` and PipeWire or PulseAudio.

```sh
python3 -m venv --system-site-packages .venv   # system site-packages gives pystray the AppIndicator bindings
.venv/bin/pip install -e .
```

## Use

```sh
.venv/bin/momentr              # start with a tray icon
.venv/bin/momentr run --no-tray
.venv/bin/momentr save         # save a clip from a running instance (e.g. bind to a GNOME shortcut)
.venv/bin/momentr autostart on # start at login (or use "Start at login" in the tray menu)
```

Default hotkey: **Ctrl+Alt+S**. Clips are saved to `~/Videos/Momentr`.

The tray menu can save a clip, pause or resume the buffer, set the clip length, set how many clips to keep, toggle
start at login, open the settings file and open the clips folder.

## Configuration

`~/.config/momentr/config.toml` is created on first run:

| key            | default            | meaning                                                            |
|----------------|--------------------|--------------------------------------------------------------------|
| `clip_seconds` | `30`               | length of each saved clip                                          |
| `hotkey`       | `"<ctrl>+<alt>+s"` | global hotkey, in pynput syntax                                    |
| `output_dir`   | `~/Videos/Momentr` | where clips go                                                     |
| `fps`          | `60`               | capture frame rate                                                 |
| `monitor`      | `""`               | `""` = primary, `"all"` = whole screen, or an `xrandr` monitor name |
| `draw_mouse`   | `true`             | include the cursor                                                 |
| `encoder`      | `"auto"`           | `auto`, `nvenc`, `vaapi` or `x264`                                 |
| `bitrate`      | `"12M"`            | target video bitrate                                               |
| `audio`        | `true`             | record desktop audio                                               |
| `sound`        | `true`             | play a shutter sound when a clip is saved                          |
| `overlay`      | `true`             | show a "Clipped with Momentr" pop-up at the top-left on save        |
| `keep_clips`   | `0`                | keep only the newest N clips (0 = keep all)                        |
| `keep_days`    | `0`                | delete clips older than N days (0 = never)                         |

Changes apply as soon as you save the file. Capture settings (`fps`, `monitor`,
`draw_mouse`, `encoder`, `bitrate`, `audio`) restart capture, which clears the buffer;
everything else applies without interruption. If the file has an error, Momentr keeps
the previous settings and shows a notification.

Cleanup only deletes clips with Momentr's own names (`clip_YYYY-MM-DD_HH-MM-SS.mp4`),
and deletion is permanent. Rename a clip to keep it forever. Cleanup runs at startup,
after each save and whenever settings change.

## Limitations

- X11 only. On Wayland, `x11grab` can't capture the screen, and global hotkeys
  need a desktop shortcut that runs `momentr save`.
