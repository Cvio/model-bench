"""What each kind of job does. A job runs in its own process (bench.worker),
so a crash inside a model marks only that job failed.

Kinds are added milestone by milestone (prepare a dataset, convert a model,
transcribe a batch, translate a batch, judge a batch, statistics, report).
B1 has only the dummy job used to test the queue.
"""

import time


def dummy(payload: dict) -> dict:
    """Sleep, reporting progress each second; optionally crash, to test that a
    failure is contained and retried."""
    seconds = float(payload.get("seconds", 1))
    started = time.time()
    while time.time() - started < seconds:
        time.sleep(min(1.0, seconds - (time.time() - started)))
    if payload.get("fail"):
        raise RuntimeError(f"dummy job asked to fail after {seconds:g} s")
    return {"slept": seconds}


KINDS = {"dummy": dummy}
