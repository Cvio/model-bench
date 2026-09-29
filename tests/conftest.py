import os
import tempfile
from pathlib import Path

# Before bench is imported: every test run uses its own scratch database, so
# the real queue in state/ is never touched. Worker processes inherit it.
os.environ["BENCH_DB"] = str(Path(tempfile.mkdtemp(prefix="bench-test-")) / "bench.db")
