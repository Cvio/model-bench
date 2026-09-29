"""What the window shows, without a window."""

from bench import session
from bench.session import Snapshot


def snap(**kw):
    counts = {"pending": 0, "running": 0, "done": 0, "failed": 0}
    counts.update(kw.pop("counts", {}))
    return Snapshot(counts=counts, **kw)


def test_status_words():
    assert session.status_words(snap(runner_pid=5)) == "Running"
    assert session.status_words(snap(runner_pid=5, pause_requested=True)).startswith("Pausing")
    assert session.status_words(snap(counts={"pending": 3})) == "Paused"
    assert session.status_words(snap(counts={"failed": 1})).startswith("Waiting for you")
    assert session.status_words(snap()).startswith("Idle")


def test_buttons_and_viewer_mode():
    idle = session.buttons(snap(counts={"pending": 2}), False)
    assert idle.start and not idle.pause and not idle.viewer
    theirs = session.buttons(snap(runner_pid=5, counts={"pending": 2}), False)
    assert not theirs.start and theirs.pause and theirs.viewer   # Pause works in viewer mode
    mine = session.buttons(snap(runner_pid=5, counts={"pending": 2}), True)
    assert not mine.viewer


def test_closing_asks_only_while_jobs_run():
    assert session.close_question(snap(runner_pid=5))
    assert not session.close_question(snap(counts={"pending": 4}))


def test_estimate():
    assert session.estimate(snap()) == "—"
    assert session.estimate(snap(counts={"pending": 3})) == "working it out…"
    assert session.estimate(snap(counts={"pending": 10}, mean_seconds=60)) == "about 10 min"


def test_a_job_left_running_without_a_runner_is_shown_as_interrupted():
    job = {"kind": "dummy", "key": "x", "started": 0}
    assert "interrupted" in session.now_running(snap(running=job))
    assert "interrupted" not in session.now_running(snap(running=job, runner_pid=5))
