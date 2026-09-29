"""The work queue and every result, in state/bench.db (SQLite).

Work is a queue of small jobs. A job's result is written in the same
transaction as its status, so a crash can never leave a job marked done
without its result, or a result without its job.

Statuses: pending -> running -> done | failed. A job that fails is retried
once (attempts < MAX_ATTEMPTS), then left failed for the user ("Retry failed").

Control flags (the `control` table) are how a window or a command talks to
the runner: `pause` (finish the current job, then stop) and `stop` (stop at
once; the running job goes back to pending).
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# BENCH_DB points everything (runner, workers, window) at another database:
# how the tests run the real queue without touching state/.
DB_PATH = Path(os.environ.get("BENCH_DB") or ROOT / "state" / "bench.db")
MAX_ATTEMPTS = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id        INTEGER PRIMARY KEY,
    kind      TEXT NOT NULL,
    key       TEXT NOT NULL UNIQUE,      -- what makes the job unique; reuse is by key
    payload   TEXT NOT NULL,             -- JSON: what the job needs
    status    TEXT NOT NULL DEFAULT 'pending',
    attempts  INTEGER NOT NULL DEFAULT 0,
    result    TEXT,                      -- JSON, written with status 'done'
    error     TEXT,
    created   REAL NOT NULL,
    started   REAL,
    finished  REAL,
    seconds   REAL                       -- how long the last attempt took
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, id);
CREATE TABLE IF NOT EXISTS control (
    name  TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS log (
    id      INTEGER PRIMARY KEY,
    ts      REAL NOT NULL,
    level   TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


def connect(path: Path = None) -> sqlite3.Connection:
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # WAL: readers (the window) never block the writer (the runner), and
    # vice versa.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


# --- Jobs -------------------------------------------------------------------------


def add_job(conn, kind: str, key: str, payload: dict) -> bool:
    """Queue a job unless one with the same key exists. Returns whether it was
    added: a job already done is reused, never rerun."""
    with transaction(conn):
        cur = conn.execute(
            "INSERT OR IGNORE INTO jobs (kind, key, payload, created) VALUES (?, ?, ?, ?)",
            (kind, key, json.dumps(payload), time.time()),
        )
    return cur.rowcount == 1


def recover(conn) -> int:
    """On start: any job left 'running' (the runner was killed) goes back to
    'pending'. Done jobs are left alone. Returns how many were recovered."""
    with transaction(conn):
        cur = conn.execute(
            # Not counted as an attempt: being killed isn't the job's fault.
            "UPDATE jobs SET status='pending', started=NULL, attempts=MAX(attempts-1, 0) "
            "WHERE status='running'")
    return cur.rowcount


def claim_next(conn):
    """Mark the oldest pending job running and return it, or None."""
    with transaction(conn):
        row = conn.execute(
            "SELECT * FROM jobs WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE jobs SET status='running', started=?, attempts=attempts+1 WHERE id=?",
            (time.time(), row["id"]),
        )
    return conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()


def finish(conn, job_id: int, result: dict) -> None:
    """The job's result and its 'done' status, in one transaction."""
    now = time.time()
    with transaction(conn):
        conn.execute(
            "UPDATE jobs SET status='done', result=?, error=NULL, finished=?, "
            "seconds=? - COALESCE(started, ?) WHERE id=? AND status='running'",
            (json.dumps(result, ensure_ascii=False), now, now, now, job_id),
        )


def fail(conn, job_id: int, error: str) -> str:
    """Record a failed attempt. Retried once (back to pending), then left
    failed. Returns the new status."""
    now = time.time()
    with transaction(conn):
        row = conn.execute("SELECT attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
        status = "pending" if row and row["attempts"] < MAX_ATTEMPTS else "failed"
        conn.execute(
            "UPDATE jobs SET status=?, error=?, finished=?, seconds=? - COALESCE(started, ?) "
            "WHERE id=?",
            (status, error[-4000:], now, now, now, job_id),
        )
    return status


def release(conn, job_id: int) -> None:
    """Stop now: the running job goes back to pending, not counted as an attempt."""
    with transaction(conn):
        conn.execute(
            "UPDATE jobs SET status='pending', started=NULL, attempts=MAX(attempts-1, 0) "
            "WHERE id=? AND status='running'", (job_id,))


def retry_failed(conn) -> int:
    with transaction(conn):
        cur = conn.execute(
            "UPDATE jobs SET status='pending', attempts=0, error=NULL WHERE status='failed'")
    return cur.rowcount


def counts(conn) -> dict:
    out = {"pending": 0, "running": 0, "done": 0, "failed": 0}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"):
        out[row["status"]] = row["n"]
    return out


# --- Control flags ----------------------------------------------------------------


def set_flag(conn, name: str, value: str = "1") -> None:
    with transaction(conn):
        conn.execute("INSERT OR REPLACE INTO control (name, value) VALUES (?, ?)", (name, value))


def clear_flag(conn, name: str) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM control WHERE name=?", (name,))


def flag(conn, name: str):
    row = conn.execute("SELECT value FROM control WHERE name=?", (name,)).fetchone()
    return row["value"] if row else None


# --- Log --------------------------------------------------------------------------


def log(conn, message: str, level: str = "info") -> None:
    with transaction(conn):
        conn.execute("INSERT INTO log (ts, level, message) VALUES (?, ?, ?)",
                     (time.time(), level, message))


def pid_alive(pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except Exception:  # noqa: BLE001 - no such process, or no access: treat as gone
        return False


def os_pid() -> int:
    return os.getpid()
