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


def _data(name):
    def run(payload):
        from bench import data

        return getattr(data, name)(payload)
    return run


def _contamination(payload):
    from bench import contamination

    return contamination.check(payload)


KINDS = {
    "dummy": dummy,
    "prepare_flores": _data("prepare_flores"),
    "prepare_fleurs": _data("prepare_fleurs"),
    "prepare_youssef": _data("prepare_youssef"),
    "prepare_user": _data("prepare_user"),
    "match_and_split": _data("match_and_split"),
    "contamination": _contamination,
}
