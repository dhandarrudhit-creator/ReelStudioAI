"""SQLite persistence for local accounts, projects, clips, and exports."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DATA_DIR = Path(os.getenv("DATA_DIR", "../storage")).resolve()
DB_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "reel-studio.sqlite3"))).resolve()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def initialize() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS videos (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          name TEXT NOT NULL, file_path TEXT NOT NULL, mime_type TEXT NOT NULL,
          size_bytes INTEGER NOT NULL, duration REAL, width INTEGER, height INTEGER, frame_rate REAL, has_audio INTEGER,
          status TEXT NOT NULL DEFAULT 'uploaded', created_at TEXT NOT NULL, error TEXT
        );
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
          status TEXT NOT NULL, stage TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
          error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS clips (
          id TEXT PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
          title TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL, score REAL NOT NULL,
          transcript TEXT NOT NULL, created_at TEXT NOT NULL,
          explanation TEXT NOT NULL DEFAULT '', evidence_json TEXT NOT NULL DEFAULT '[]',
          score_breakdown_json TEXT NOT NULL DEFAULT '{}', warnings_json TEXT NOT NULL DEFAULT '[]',
          review_status TEXT NOT NULL DEFAULT 'suggested', edited INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS exports (
          id TEXT PRIMARY KEY, clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
          video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
          file_path TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
          duration REAL, width INTEGER, height INTEGER, error TEXT, metadata_json TEXT
        );
        CREATE TABLE IF NOT EXISTS publishing_accounts (
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, platform TEXT NOT NULL,
          credentials TEXT NOT NULL, connected_at TEXT NOT NULL, PRIMARY KEY(user_id,platform)
        );
        CREATE TABLE IF NOT EXISTS publishing_jobs (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          export_id TEXT NOT NULL REFERENCES exports(id), platform TEXT NOT NULL,
          title TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '', scheduled_at TEXT NOT NULL, timezone TEXT NOT NULL,
          state TEXT NOT NULL, provider_id TEXT, error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TEXT, lease_until TEXT, confirmed_at TEXT, is_mock INTEGER NOT NULL DEFAULT 0,
          self_declared_made_for_kids INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_publish_due ON publishing_jobs(state,next_attempt_at,scheduled_at);
        CREATE TABLE IF NOT EXISTS performance_feedback (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          export_id TEXT NOT NULL REFERENCES exports(id), rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
          note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transcript_segments (
          id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
          start REAL NOT NULL, end REAL NOT NULL, text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_videos_user_created ON videos(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_clips_video ON clips(video_id);
        CREATE INDEX IF NOT EXISTS ix_exports_video ON exports(video_id);
        """)
        # Additive migrations keep existing local databases usable.
        for table, column in (("videos", "frame_rate REAL"), ("videos", "has_audio INTEGER"),
                              ("publishing_jobs", "self_declared_made_for_kids INTEGER"),
                              ("exports", "error TEXT"), ("exports", "metadata_json TEXT"),
                              ("clips", "moment_type TEXT NOT NULL DEFAULT 'lesson_summary'"),
                              ("clips", "signals TEXT NOT NULL DEFAULT '[]'"), ("clips", "quality_score REAL NOT NULL DEFAULT 0"),
                              ("clips", "explanation TEXT NOT NULL DEFAULT ''"), ("clips", "evidence_json TEXT NOT NULL DEFAULT '[]'"),
                              ("clips", "score_breakdown_json TEXT NOT NULL DEFAULT '{}'"), ("clips", "warnings_json TEXT NOT NULL DEFAULT '[]'"),
                              ("clips", "review_status TEXT NOT NULL DEFAULT 'suggested'"), ("clips", "edited INTEGER NOT NULL DEFAULT 0")):
            try: db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower(): raise
