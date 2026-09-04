#!/usr/bin/env python3
"""Create a transactionally consistent SQLite backup and prune old copies."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def sqlite_path(database_url: str) -> Path:
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if database_url.startswith(prefix):
            return Path(database_url[len(prefix):])
    raise ValueError("Only SQLite database URLs are supported")


def backup(source: Path, destination_dir: Path, keep: int) -> Path:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = destination_dir / f"judicial-comment-bot-{stamp}.db"
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    backups = sorted(destination_dir.glob("judicial-comment-bot-*.db"), reverse=True)
    for old in backups[max(1, keep):]:
        old.unlink(missing_ok=True)
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default="sqlite+aiosqlite:///runtime/judicial_comment_bot.db")
    parser.add_argument("--destination", default="runtime/backups")
    parser.add_argument("--keep", type=int, default=14)
    args = parser.parse_args()
    target = backup(sqlite_path(args.database_url), Path(args.destination), args.keep)
    print(target)


if __name__ == "__main__":
    main()
