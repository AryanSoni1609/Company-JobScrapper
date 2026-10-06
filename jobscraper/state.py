"""Local SQLite state in data/state.db (gitignored).

The Google Sheet is the user-facing record; this database is the agent's
memory so it can work without re-reading the whole sheet and so the 21:00
digest knows exactly what is new since the last email.

Tables:
    companies  every company ever checked (ATS detection result + when it
               was appended to the sheet / reported in a digest)
    jobs       every matching job appended (resume path, digest status)
    meta       key/value bookkeeping (last sync, last scan, ...)
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import load_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    name_key      TEXT PRIMARY KEY,
    company_name  TEXT NOT NULL,
    source        TEXT,
    ats_type      TEXT,
    board_token   TEXT,
    career_url    TEXT,
    job_count     INTEGER,
    active        TEXT,
    checked_at    TEXT,
    added_to_sheet_at TEXT,
    notified_at   TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    job_url       TEXT PRIMARY KEY,
    company       TEXT,
    title         TEXT,
    data          TEXT,
    match_score   REAL,
    resume_path   TEXT,
    added_at      TEXT,
    notified_at   TEXT,
    status        TEXT DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_lock = threading.RLock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    def __init__(self, path: Path | None = None):
        settings = load_settings()
        settings.ensure_dirs()
        self.path = path or settings.state_db_path
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        with _lock:
            self.conn.executescript(_SCHEMA)
            self.conn.commit()

    @contextmanager
    def tx(self):
        with _lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    # ── meta ──────────────────────────────────────────────────────────────
    def get_meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # ── companies ─────────────────────────────────────────────────────────
    def checked_company_keys(self) -> set[str]:
        return {r["name_key"] for r in self.conn.execute("SELECT name_key FROM companies")}

    def record_company(self, result: dict, source: str, added_to_sheet: bool) -> None:
        with self.tx() as c:
            c.execute(
                """INSERT INTO companies(name_key, company_name, source, ats_type, board_token, career_url,
                                         job_count, active, checked_at, added_to_sheet_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(name_key) DO UPDATE SET
                     ats_type=excluded.ats_type, board_token=excluded.board_token,
                     career_url=excluded.career_url, job_count=excluded.job_count,
                     active=excluded.active, checked_at=excluded.checked_at,
                     added_to_sheet_at=COALESCE(companies.added_to_sheet_at, excluded.added_to_sheet_at)""",
                (result["company_name"].strip().lower(), result["company_name"], source,
                 result.get("ats_type", ""), result.get("board_token", ""), result.get("career_url", ""),
                 int(result.get("job_count") or 0), result.get("active", "NO"), now_iso(),
                 now_iso() if added_to_sheet else None),
            )

    def active_companies(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT company_name, ats_type, board_token FROM companies WHERE active='YES' AND board_token<>''")
        return [dict(r) for r in rows]

    def companies_not_on_sheet(self) -> list[dict]:
        """Checked while Google Sheets was not configured — appended on the next sync."""
        rows = self.conn.execute("SELECT * FROM companies WHERE added_to_sheet_at IS NULL")
        return [dict(r) for r in rows]

    def mark_companies_on_sheet(self, name_keys: list[str]) -> None:
        with self.tx() as c:
            c.executemany("UPDATE companies SET added_to_sheet_at=? WHERE name_key=?",
                          [(now_iso(), k) for k in name_keys])

    def unnotified_companies(self) -> list[dict]:
        """Newly added companies with a supported ATS, not yet reported in a digest."""
        rows = self.conn.execute(
            "SELECT * FROM companies WHERE active='YES' AND notified_at IS NULL ORDER BY company_name")
        return [dict(r) for r in rows]

    def mark_companies_notified(self, name_keys: list[str]) -> None:
        with self.tx() as c:
            c.executemany("UPDATE companies SET notified_at=? WHERE name_key=?",
                          [(now_iso(), k) for k in name_keys])

    # ── jobs ──────────────────────────────────────────────────────────────
    def known_job_urls(self) -> set[str]:
        return {r["job_url"] for r in self.conn.execute("SELECT job_url FROM jobs")}

    def add_job(self, job: dict, match_score: float, resume_path: str = "") -> None:
        data = {k: v for k, v in job.items() if k != "compensation"}
        with self.tx() as c:
            c.execute(
                "INSERT OR IGNORE INTO jobs(job_url, company, title, data, match_score, resume_path, added_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (job["url"], job.get("company", ""), job.get("title", ""), json.dumps(data, default=str),
                 match_score, resume_path, now_iso()),
            )

    def set_job_resume(self, job_url: str, resume_path: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE jobs SET resume_path=? WHERE job_url=?", (resume_path, job_url))

    def set_job_status(self, job_url: str, status: str) -> bool:
        with self.tx() as c:
            cur = c.execute("UPDATE jobs SET status=? WHERE job_url=?", (status, job_url))
            return cur.rowcount > 0

    def get_job(self, job_url: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM jobs WHERE job_url=?", (job_url,)).fetchone()
        return _job_row(r) if r else None

    def list_jobs(self, only_unnotified: bool = False, status: str | None = None, limit: int = 200) -> list[dict]:
        q, args = "SELECT * FROM jobs WHERE 1=1", []
        if only_unnotified:
            q += " AND notified_at IS NULL"
        if status:
            q += " AND status=?"
            args.append(status)
        q += " ORDER BY match_score DESC, added_at DESC LIMIT ?"
        args.append(limit)
        return [_job_row(r) for r in self.conn.execute(q, args)]

    def mark_jobs_notified(self, urls: list[str]) -> None:
        with self.tx() as c:
            c.executemany("UPDATE jobs SET notified_at=? WHERE job_url=?", [(now_iso(), u) for u in urls])

    def stats(self) -> dict:
        one = lambda q: self.conn.execute(q).fetchone()[0]  # noqa: E731
        return {
            "companies_checked": one("SELECT COUNT(*) FROM companies"),
            "companies_active": one("SELECT COUNT(*) FROM companies WHERE active='YES'"),
            "jobs_tracked": one("SELECT COUNT(*) FROM jobs"),
            "jobs_pending_digest": one("SELECT COUNT(*) FROM jobs WHERE notified_at IS NULL"),
            "companies_pending_digest": one(
                "SELECT COUNT(*) FROM companies WHERE active='YES' AND notified_at IS NULL"),
            "companies_not_on_sheet": one("SELECT COUNT(*) FROM companies WHERE added_to_sheet_at IS NULL"),
            "last_scan": self.get_meta("last_scan"),
            "last_company_sync": self.get_meta("last_company_sync"),
            "last_digest": self.get_meta("last_digest"),
        }


def _job_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    try:
        d.update({k: v for k, v in json.loads(d.pop("data") or "{}").items() if k not in d})
    except json.JSONDecodeError:
        pass
    return d
