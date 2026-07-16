"""SQLite-backed dedupe store so we don't re-email the same domain every run."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path


class SeenStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_domains (
                domain        TEXT PRIMARY KEY,
                first_seen    TEXT NOT NULL,
                last_emailed  TEXT,
                last_score    INTEGER,
                times_emailed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self.conn.commit()

    def is_suppressed(self, domain: str, suppress_days: int) -> bool:
        """True if the domain was emailed within the suppress window."""
        row = self.conn.execute(
            "SELECT last_emailed FROM seen_domains WHERE domain = ?", (domain,)
        ).fetchone()
        if not row or not row[0]:
            return False
        last = datetime.fromisoformat(row[0]).date()
        return (date.today() - last) < timedelta(days=suppress_days)

    def record_seen(self, domain: str, score: int) -> None:
        today = date.today().isoformat()
        self.conn.execute(
            """
            INSERT INTO seen_domains (domain, first_seen, last_score)
            VALUES (?, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET last_score = excluded.last_score
            """,
            (domain, today, score),
        )
        self.conn.commit()

    def mark_emailed(self, domains: list[str]) -> None:
        today = date.today().isoformat()
        for d in domains:
            self.conn.execute(
                """
                INSERT INTO seen_domains (domain, first_seen, last_emailed, times_emailed)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(domain) DO UPDATE SET
                    last_emailed = excluded.last_emailed,
                    times_emailed = times_emailed + 1
                """,
                (d, today, today),
            )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
