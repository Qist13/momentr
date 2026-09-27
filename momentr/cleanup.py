"""Delete old auto-named clips according to keep_clips / keep_days."""

import re
import time
from pathlib import Path

# Only clips Momentr named itself are eligible; renaming a clip protects it.
AUTO_NAME = re.compile(r"^clip_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.mp4$")


def prune_clips(out_dir: Path, keep_clips: int, keep_days: int) -> list[Path]:
    """Delete clips beyond the newest `keep_clips` or older than `keep_days`.
    A limit of 0 disables it. Returns the deleted paths."""
    if keep_clips <= 0 and keep_days <= 0:
        return []
    try:
        # Names embed the timestamp, so name order is chronological.
        clips = sorted(p for p in out_dir.iterdir() if p.is_file() and AUTO_NAME.match(p.name))
    except FileNotFoundError:
        return []

    doomed = set()
    if keep_clips > 0:
        doomed.update(clips[:-keep_clips])
    if keep_days > 0:
        cutoff = time.time() - keep_days * 86400
        doomed.update(p for p in clips if p.stat().st_mtime < cutoff)

    deleted = []
    for p in sorted(doomed):
        try:
            p.unlink()
            deleted.append(p)
        except OSError:
            pass
    return deleted
