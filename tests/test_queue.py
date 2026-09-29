"""The queue: reuse, resume, retry, pause and stop, with real worker processes."""

import threading
import time

import pytest

from bench import db, runner


@pytest.fixture
def conn():
    c = db.connect()
    c.execute("DELETE FROM jobs")
    c.execute("DELETE FROM control")
    c.execute("DELETE FROM log")
    return c


def statuses(conn):
    return {r["key"]: r["status"] for r in conn.execute("SELECT key, status FROM jobs")}


def test_a_job_is_added_once_and_reused(conn):
    assert db.add_job(conn, "dummy", "a", {"seconds": 0})
    assert not db.add_job(conn, "dummy", "a", {"seconds": 0})
    assert db.counts(conn)["pending"] == 1


def test_jobs_run_in_their_own_processes_and_results_are_stored(conn):
    for k in ("a", "b"):
        db.add_job(conn, "dummy", k, {"seconds": 0.1})
    assert runner.run(conn) == "empty"
    rows = conn.execute("SELECT status, result FROM jobs").fetchall()
    assert all(r["status"] == "done" and '"slept"' in r["result"] for r in rows)


def test_a_failing_job_is_retried_once_then_left_for_the_user(conn):
    db.add_job(conn, "dummy", "bad", {"seconds": 0, "fail": True})
    db.add_job(conn, "dummy", "good", {"seconds": 0})
    runner.run(conn)
    row = conn.execute("SELECT status, attempts, error FROM jobs WHERE key='bad'").fetchone()
    assert (row["status"], row["attempts"]) == ("failed", 2)
    assert "asked to fail" in row["error"]
    assert statuses(conn)["good"] == "done"   # one crash doesn't take down the rest
    assert db.retry_failed(conn) == 1


def test_a_job_left_running_by_a_killed_runner_runs_again_and_done_jobs_dont(conn):
    db.add_job(conn, "dummy", "finished", {"seconds": 0})
    runner.run(conn)
    db.add_job(conn, "dummy", "interrupted", {"seconds": 0})
    conn.execute("UPDATE jobs SET status='running', attempts=1 WHERE key='interrupted'")
    finished_at = conn.execute("SELECT finished FROM jobs WHERE key='finished'").fetchone()[0]
    runner.run(conn)
    assert statuses(conn) == {"finished": "done", "interrupted": "done"}
    # The kill didn't count as an attempt: the rerun is attempt 1, so a real
    # failure would still get its retry.
    assert conn.execute("SELECT attempts FROM jobs WHERE key='interrupted'").fetchone()[0] == 1
    assert conn.execute("SELECT finished FROM jobs WHERE key='finished'").fetchone()[0] == finished_at


def test_pause_finishes_the_current_job_then_stops(conn):
    for k in ("first", "second"):
        db.add_job(conn, "dummy", k, {"seconds": 1.5})
    threading.Timer(0.5, lambda: db.set_flag(db.connect(), "pause")).start()
    assert runner.run(conn) == "paused"
    assert statuses(conn) == {"first": "done", "second": "pending"}


def test_stop_ends_the_running_job_which_runs_again_later(conn):
    db.add_job(conn, "dummy", "long", {"seconds": 30})
    threading.Timer(1.0, lambda: db.set_flag(db.connect(), "stop")).start()
    started = time.time()
    assert runner.run(conn) == "stopped"
    assert time.time() - started < 10
    row = conn.execute("SELECT status, attempts FROM jobs").fetchone()
    assert (row["status"], row["attempts"]) == ("pending", 0)


def test_only_one_runner_at_a_time(conn):
    runner.LOCK.write_text('{"pid": %d}' % __import__("os").getppid(), encoding="utf-8")
    try:
        with pytest.raises(runner.LockHeld):
            runner.run(conn)
    finally:
        runner.LOCK.unlink()
