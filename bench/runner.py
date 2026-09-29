"""The runner: works through the queue, one job at a time, each in its own
process. One runner at a time, held by state/runner.lock.

- Resume: on start, any job left 'running' goes back to 'pending'. Done jobs
  are never rerun.
- Pause (flag 'pause'): finish the current job, then stop.
- Stop now (flag 'stop'): end the current job's process at once; that job goes
  back to pending (not counted as a failed attempt), and nothing else is lost.
- A job whose process fails is retried once, then left failed.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from bench import db

LOCK = db.DB_PATH.parent / "runner.lock"
POLL = 0.25


class LockHeld(Exception):
    pass


def lock_owner():
    """The pid holding the runner lock, or None if it's free (or stale)."""
    try:
        info = json.loads(LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid = info.get("pid")
    return pid if pid and db.pid_alive(pid) else None


def acquire_lock() -> None:
    owner = lock_owner()
    if owner and owner != os.getpid():
        raise LockHeld(f"another runner is working (process {owner})")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({"pid": os.getpid(), "since": time.time()}), encoding="utf-8")


def release_lock() -> None:
    try:
        if json.loads(LOCK.read_text(encoding="utf-8")).get("pid") == os.getpid():
            LOCK.unlink()
    except (OSError, ValueError):
        pass


def run_job(conn, job) -> str:
    """Run one claimed job in its own process. Returns 'done', 'failed',
    'pending' (retrying) or 'stopped'."""
    command = [sys.executable, "-m", "bench.worker", str(job["id"])]
    db.log(conn, f"started job {job['id']} ({job['kind']}: {job['key']}), attempt {job['attempts']}")
    process = subprocess.Popen(command, cwd=db.ROOT, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    while process.poll() is None:
        if db.flag(conn, "stop"):
            process.kill()
            process.wait()
            db.release(conn, job["id"])
            db.log(conn, f"stopped job {job['id']} at once; it will run again", "warn")
            return "stopped"
        time.sleep(POLL)
    stderr = process.stderr.read().strip()
    if process.returncode == 5:   # bench.worker.DISK_LOW
        db.release(conn, job["id"])
        db.set_flag(conn, "pause")
        db.log(conn, f"paused: {stderr.splitlines()[-1] if stderr else 'the disk is nearly full'}", "error")
        return "pending"
    status = conn.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()["status"]
    if process.returncode == 0 and status == "done":
        db.log(conn, f"finished job {job['id']}")
        return "done"
    reason = stderr.splitlines()[-1] if stderr else f"the process exited with code {process.returncode}"
    new = db.fail(conn, job["id"], stderr or reason)
    if new == "pending":
        db.log(conn, f"job {job['id']} failed ({reason}); retrying once", "warn")
    else:
        db.log(conn, f"job {job['id']} failed again ({reason}); left for you (Retry failed)", "error")
    return new


def run(conn=None) -> str:
    """Work until the queue is empty, or until paused or stopped. Returns why
    it ended: 'empty', 'paused' or 'stopped'."""
    conn = conn or db.connect()
    acquire_lock()
    try:
        db.clear_flag(conn, "pause")
        db.clear_flag(conn, "stop")
        recovered = db.recover(conn)
        db.set_flag(conn, "runner", str(os.getpid()))
        db.log(conn, "runner started" + (f"; {recovered} interrupted job(s) will run again"
                                         if recovered else ""))
        while True:
            if db.flag(conn, "stop"):
                db.log(conn, "stopped")
                return "stopped"
            if db.flag(conn, "pause"):
                db.log(conn, "paused")
                return "paused"
            job = db.claim_next(conn)
            if job is None:
                db.log(conn, "the queue is empty")
                return "empty"
            if run_job(conn, job) == "stopped":
                return "stopped"
    finally:
        db.clear_flag(conn, "runner")
        db.clear_flag(conn, "pause")
        db.clear_flag(conn, "stop")
        release_lock()
