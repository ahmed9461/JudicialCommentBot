import os
import time
from pathlib import Path

from app.services.runtime_cleanup import cleanup_stale_files


def test_stale_cleanup_only_removes_old_files(tmp_path: Path) -> None:
    old = tmp_path / "old.pdf"
    recent = tmp_path / "recent.docx"
    old.write_bytes(b"old")
    recent.write_bytes(b"new")
    timestamp = time.time() - 10 * 3600
    os.utime(old, (timestamp, timestamp))
    assert cleanup_stale_files(tmp_path, max_age_hours=6) == 1
    assert not old.exists()
    assert recent.exists()
