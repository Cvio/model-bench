"""What the window shows, worked out from state/bench.db alone, with no Qt.

The window keeps no state of its own: each refresh reads the database into a
Snapshot, and this module turns it into plain words and numbers. It's
unit-tested without a window, as volis's gui::Session is.
"""

import time
from dataclasses import dataclass, field

from bench import db, runner


@dataclass
class Snapshot:
    counts: dict
    running: dict = None           # the running job's row, if any
    runner_pid: int = None         # who holds the runner lock
    pause_requested: bool = False
    stop_requested: bool = False
    mean_seconds: float = None     # average time of finished jobs
    log: list = field(default_factory=list)
    round_number: int = None


def read(conn, log_lines: int = 200) -> Snapshot:
    running = conn.execute("SELECT * FROM jobs WHERE status='running' ORDER BY id LIMIT 1").fetchone()
    mean = conn.execute("SELECT AVG(seconds) AS s FROM jobs WHERE status='done' AND seconds IS NOT NULL"
                        ).fetchone()["s"]
    rows = conn.execute("SELECT ts, level, message FROM log ORDER BY id DESC LIMIT ?", (log_lines,)).fetchall()
    return Snapshot(
        counts=db.counts(conn),
        running=dict(running) if running else None,
        runner_pid=runner.lock_owner(),
        pause_requested=bool(db.flag(conn, "pause")),
        stop_requested=bool(db.flag(conn, "stop")),
        mean_seconds=mean,
        log=[dict(r) for r in reversed(rows)],
    )


def status_words(s: Snapshot) -> str:
    """The top bar's status, in plain words."""
    if s.runner_pid:
        if s.stop_requested:
            return "Stopping now"
        if s.pause_requested:
            return "Pausing — finishing the current job"
        return "Running"
    if s.counts["failed"] and not s.counts["pending"]:
        return "Waiting for you — some jobs failed"
    if s.counts["pending"]:
        return "Paused"
    return "Idle — nothing to do"


def now_running(s: Snapshot) -> str:
    if not s.running:
        return "—"
    if not s.runner_pid:
        return f"{s.running['kind']}: {s.running['key']} was interrupted; it will run again on Start"
    elapsed = time.time() - (s.running.get("started") or time.time())
    return f"{s.running['kind']}: {s.running['key']} ({elapsed:.0f} s)"


def estimate(s: Snapshot) -> str:
    left = s.counts["pending"] + s.counts["running"]
    if not left:
        return "—"
    if not s.mean_seconds:
        return "working it out…"
    seconds = left * s.mean_seconds
    if seconds < 90:
        return f"about {seconds:.0f} s"
    if seconds < 5400:
        return f"about {seconds / 60:.0f} min"
    return f"about {seconds / 3600:.1f} h"


def counts_words(s: Snapshot) -> str:
    c = s.counts
    return f"{c['done']} done · {c['pending'] + c['running']} left · {c['failed']} failed"


@dataclass
class Buttons:
    start: bool
    pause: bool
    retry_failed: bool
    viewer: bool   # another process runs the queue: this window only watches (and can pause)


def buttons(s: Snapshot, this_window_started_runner: bool) -> Buttons:
    running = bool(s.runner_pid)
    return Buttons(
        start=not running and s.counts["pending"] > 0,
        pause=running and not s.pause_requested,
        retry_failed=s.counts["failed"] > 0,
        viewer=running and not this_window_started_runner,
    )


def close_question(s: Snapshot) -> bool:
    """Whether closing the window must ask what to do: only while jobs run."""
    return bool(s.runner_pid)
