import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Job

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_jobs (
    id TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS job_history (
    id       TEXT NOT NULL,
    title    TEXT,
    subject  TEXT,
    url      TEXT,
    first_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS health_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        REAL NOT NULL,
    ok        INTEGER NOT NULL,
    job_count INTEGER,
    message   TEXT
);
"""


class Store:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(db_path), check_same_thread=False)
        self._con.executescript(_SCHEMA)
        self._con.commit()

    def is_baseline_established(self) -> bool:
        row = self._con.execute(
            "SELECT value FROM metadata WHERE key='baseline_established'"
        ).fetchone()
        return row is not None and row[0] == "1"

    def establish_baseline(self, jobs: list[Job]) -> None:
        """Silently absorb all current jobs so we only alert on future ones."""
        ts = datetime.now(timezone.utc).timestamp()
        with self._con:
            for job in jobs:
                self._con.execute(
                    "INSERT OR IGNORE INTO seen_jobs (id) VALUES (?)", (job.id,)
                )
                self._con.execute(
                    "INSERT OR IGNORE INTO job_history (id, title, subject, url, first_seen) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (job.id, job.title, job.subject, job.url, ts),
                )
            self._con.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES ('baseline_established', '1')"
            )
        logger.info("Baseline established with %d jobs (no notifications sent)", len(jobs))

    def new_jobs(self, jobs: list[Job]) -> list[Job]:
        """Return jobs from `jobs` that haven't been seen before."""
        if not jobs:
            return []
        seen = {
            row[0]
            for row in self._con.execute("SELECT id FROM seen_jobs").fetchall()
        }
        return [j for j in jobs if j.id not in seen]

    def mark_seen(self, jobs: list[Job]) -> None:
        """Persist jobs as seen. Call only after notifications are sent successfully."""
        ts = datetime.now(timezone.utc).timestamp()
        with self._con:
            for job in jobs:
                self._con.execute(
                    "INSERT OR IGNORE INTO seen_jobs (id) VALUES (?)", (job.id,)
                )
                self._con.execute(
                    "INSERT OR IGNORE INTO job_history (id, title, subject, url, first_seen) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (job.id, job.title, job.subject, job.url, ts),
                )

    def record_health_check(self, ok: bool, job_count: int, message: str) -> None:
        ts = datetime.now(timezone.utc).timestamp()
        with self._con:
            self._con.execute(
                "INSERT INTO health_events (at, ok, job_count, message) VALUES (?, ?, ?, ?)",
                (ts, 1 if ok else 0, job_count, message),
            )
            self._con.execute(
                "DELETE FROM health_events WHERE id NOT IN "
                "(SELECT id FROM health_events ORDER BY at DESC LIMIT 200)"
            )

    def record_poll(self) -> None:
        ts = datetime.now(timezone.utc).timestamp()
        with self._con:
            self._con.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_poll_at', ?)",
                (str(ts),),
            )

    def close(self) -> None:
        self._con.close()
