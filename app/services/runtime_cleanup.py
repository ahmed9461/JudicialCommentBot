"""Remove abandoned temporary artifacts from interrupted runs."""

from __future__ import annotations

import time
from pathlib import Path


def cleanup_stale_files(temp_dir: str | Path, *, max_age_hours: int) -> int:
    root = Path(temp_dir)
    if not root.exists():
        return 0
    cutoff = time.time() - max(1, max_age_hours) * 3600
    removed = 0
    for path in root.iterdir():
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed
