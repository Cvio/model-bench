"""Commands (bench.ps1 runs these):

    bench                     open the window
    bench start --no-window   run the queue in this terminal
    bench pause               finish the current job, then stop
    bench stop                stop at once (the running job runs again later)
    bench status              counts, what's running, the last log lines
    bench retry-failed        put failed jobs back in the queue
    bench add-dummy N SECONDS [--fail]   queue N dummy jobs (for testing the queue)
    bench validate            check candidates.yaml, prompts/ and settings.yaml
    bench prepare             queue the test data and contamination jobs
    bench new-round           snapshot the files as a new round, and draft its changelog
    bench data                counts per test set and split
"""

import argparse
import sys
import time
import uuid

from bench import db, runner, session


def cmd_start(a) -> int:
    if not a.no_window:
        return open_window()
    try:
        why = runner.run()
    except runner.LockHeld as e:
        print(f"STOP: {e}. Use 'bench pause' to pause it, or open the window to watch.")
        return 1
    print({"empty": "Done: the queue is empty.", "paused": "Paused.", "stopped": "Stopped."}[why])
    return 0


def cmd_pause(a) -> int:
    conn = db.connect()
    if not runner.lock_owner():
        print("Nothing is running.")
        return 0
    db.set_flag(conn, "pause")
    print("Pausing: the current job will finish, then the runner stops.")
    return 0


def cmd_stop(a) -> int:
    conn = db.connect()
    if not runner.lock_owner():
        print("Nothing is running.")
        return 0
    db.set_flag(conn, "stop")
    print("Stopping now: the running job is ended and will run again next time.")
    return 0


def cmd_status(a) -> int:
    s = session.read(db.connect(), log_lines=10)
    print(f"status:  {session.status_words(s)}")
    print(f"jobs:    {session.counts_words(s)}")
    print(f"running: {session.now_running(s)}")
    print(f"left:    {session.estimate(s)}")
    for line in s.log:
        print(f"  {time.strftime('%H:%M:%S', time.localtime(line['ts']))} {line['level']:5} {line['message']}")
    return 0


def cmd_retry(a) -> int:
    n = db.retry_failed(db.connect())
    print(f"{n} failed job(s) back in the queue.")
    return 0


def cmd_add_dummy(a) -> int:
    conn = db.connect()
    batch = uuid.uuid4().hex[:6]
    for i in range(a.n):
        db.add_job(conn, "dummy", f"dummy-{batch}-{i + 1}", {"seconds": a.seconds, "fail": a.fail})
    print(f"Queued {a.n} dummy job(s) of {a.seconds:g} s (batch {batch}).")
    return 0


def cmd_validate(a) -> int:
    from bench import config

    problems = config.validate(online=True)
    for p in problems:
        print(f"  - {p}")
    print("OK: candidates.yaml, prompts/ and settings.yaml are sound." if not problems
          else f"STOP: {len(problems)} problem(s) above.")
    return 1 if problems else 0


def cmd_prepare(a) -> int:
    from bench import config, contamination, data

    problems = config.validate(online=False)
    if problems:
        print("STOP: fix these first (bench validate):")
        for p in problems:
            print(f"  - {p}")
        return 1
    conn = db.connect()
    n = data.queue(conn) + contamination.queue(conn, config.candidates())
    print(f"Queued {n} new job(s); jobs already done are reused. Start the queue to run them.")
    return 0


def cmd_new_round(a) -> int:
    from bench import rounds

    n = rounds.new_round()
    print(f"Round {n} started: {rounds.folder(n)}. Edit its changelog.md: say why each change was made.")
    return 0


def cmd_data(a) -> int:
    from bench import report_data

    print(report_data.summary(db.connect()))
    return 0


def open_window() -> int:
    from bench.gui.window import main as window_main

    return window_main()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="bench", description="model-bench")
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("start")
    p.add_argument("--no-window", action="store_true")
    p.set_defaults(func=cmd_start)
    sub.add_parser("pause").set_defaults(func=cmd_pause)
    sub.add_parser("stop").set_defaults(func=cmd_stop)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("retry-failed").set_defaults(func=cmd_retry)
    sub.add_parser("validate").set_defaults(func=cmd_validate)
    sub.add_parser("prepare").set_defaults(func=cmd_prepare)
    sub.add_parser("new-round").set_defaults(func=cmd_new_round)
    sub.add_parser("data").set_defaults(func=cmd_data)
    p = sub.add_parser("add-dummy")
    p.add_argument("n", type=int)
    p.add_argument("seconds", type=float)
    p.add_argument("--fail", action="store_true")
    p.set_defaults(func=cmd_add_dummy)
    a = parser.parse_args(argv)
    if not a.command:
        return open_window()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
