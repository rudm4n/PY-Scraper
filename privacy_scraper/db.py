"""Registro SQLite dei media già scaricati, per non riscaricarli a ogni giro."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import Media

_SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    media_id   TEXT NOT NULL,
    creator_id TEXT NOT NULL,
    area       TEXT NOT NULL,
    post_id    TEXT NOT NULL,
    path       TEXT NOT NULL,
    downloaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (creator_id, media_id)
)
"""


class MediaDB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def is_downloaded(self, media: Media) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM media WHERE creator_id = ? AND media_id = ?",
            (media.creator.id, media.id),
        ).fetchone()
        return row is not None

    def mark_downloaded(self, media: Media, path: Path) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO media (media_id, creator_id, area, post_id, path) "
            "VALUES (?, ?, ?, ?, ?)",
            (media.id, media.creator.id, media.area.value, media.post_id, str(path)),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
