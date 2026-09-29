"""Runs one job, in a process of its own:  python -m bench.worker <job id>

The runner starts this for each job. It writes the job's result and 'done'
status in one transaction. If the job raises, it writes nothing and exits
non-zero with the error on stderr; the runner records the failure. If the
process dies outright (a crash inside a model's native code), the runner sees
the exit code and does the same.
"""

import json
import sys
import traceback

from bench import db
from bench.jobs import KINDS


def main() -> int:
    job_id = int(sys.argv[1])
    conn = db.connect()
    job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if job is None or job["status"] != "running":
        print(f"job {job_id} isn't running; nothing to do", file=sys.stderr)
        return 3
    work = KINDS.get(job["kind"])
    if work is None:
        print(f"unknown job kind {job['kind']!r}", file=sys.stderr)
        return 4
    try:
        result = work(json.loads(job["payload"]))
    except Exception:  # noqa: BLE001 - any failure of the job's own work
        traceback.print_exc()
        return 1
    db.finish(conn, job_id, result or {})
    return 0


if __name__ == "__main__":
    sys.exit(main())
