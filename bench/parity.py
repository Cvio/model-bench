"""The parity check: before any result counts, prove the bench runs volis's
engines exactly as volis does (model-bench.md, "What runs, and how").

- ASR: each baseline recognizer transcribes 20 clips through the bench's
  runner and through `volis --transcribe`; every transcript must be identical.
- Translator: the baseline translator translates 20 sentences in each of
  three directions (English -> Persian, Persian -> English, English -> Iraqi
  Arabic, the last using volis's dialect prompt) through the bench's runner
  and through `volis --translate`; every output must be identical, refusals
  included.

The result is stored against the runtime it proved: volis's program and
model files (size and modification time) and the llama.cpp commit. Results
only count while the latest parity check for the current runtime passed.
"""

import hashlib
import json
import time
from pathlib import Path

from bench import config, data, db, runners
from bench.config import ROOT

CLIPS = 20
SENTENCES = 20
DIRECTIONS = (("en", "fa"), ("fa", "en"), ("en", "ar-IQ"))
SCHEMA = """
CREATE TABLE IF NOT EXISTS parity (
    runtime TEXT NOT NULL, checked REAL NOT NULL, passed INTEGER NOT NULL, details TEXT NOT NULL);
"""


def file_stamp(path: Path) -> str:
    st = path.stat()
    return f"{path.name}:{st.st_size}:{int(st.st_mtime)}"


def runtime_key() -> str:
    """What a parity result proves: volis's program and models, and the engines."""
    root = config.volis_root()
    parts = [file_stamp(root / "volis.exe"), file_stamp(runners.LLAMA_SERVER), runners.LLAMA_CPP_COMMIT]
    for folder in ("models/asr", "models/mt"):
        for p in sorted((root / folder).rglob("*")):
            if p.is_file() and p.suffix in (".onnx", ".gguf", ".toml", ".txt"):
                parts.append(file_stamp(p))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def baselines() -> tuple:
    c = config.candidates()
    asr = [e for e in c.get("asr") or [] if e.get("baseline")]
    translator = next(e for e in c.get("translators") or [] if e.get("baseline"))
    return asr, translator


def check(payload: dict) -> dict:
    conn = data.connect()
    conn.executescript(SCHEMA)
    details = {"asr": [], "translation": []}
    passed = True
    asr, translator = baselines()

    for entry in asr:
        folder = entry["source"].split(":", 1)[1].rstrip("/").split("/")[-1]
        for lang in (l for l in entry["languages"] if l in ("fa", "en")):
            testset = f"fleurs-{lang}"
            rows = conn.execute(
                "SELECT c.audio FROM clips c JOIN sentences s ON s.key = c.key "
                "WHERE c.testset = ? AND s.split = 'development' ORDER BY c.clip LIMIT ?",
                (testset, CLIPS)).fetchall()
            wavs = [ROOT / r["audio"] for r in rows]
            ours = runners.transcribe(entry["source"], lang, wavs)
            theirs = runners.volis_transcribe(folder, lang, wavs)
            diffs = [{"clip": str(w.name), "bench": a, "volis": b} for w, a, b in zip(wavs, ours, theirs) if a != b]
            details["asr"].append({"recognizer": entry["id"], "language": lang, "identical": len(wavs) - len(diffs),
                                   "total": len(wavs), "differences": diffs})
            passed &= not diffs and len(wavs) == CLIPS

    gguf = runners.resolve(translator["source"])
    with runners.Translator(gguf, ROOT / "cache" / "logs") as t:
        for source, target in DIRECTIONS:
            lang = source if source != "ar-IQ" else "ar-IQ"
            rows = conn.execute(
                "SELECT f.text FROM flores f JOIN sentences s ON s.key = f.key "
                "WHERE f.lang = ? AND s.split = 'development' ORDER BY f.key LIMIT ?",
                (lang, SENTENCES)).fetchall()
            lines = [r["text"] for r in rows]
            template = runners.volis_prompt(source, target)
            ours = [t.translate(l, template)["text"] for l in lines]
            theirs = runners.volis_translate(source, target, lines)
            diffs = [{"source": l, "bench": a, "volis": b} for l, a, b in zip(lines, ours, theirs) if a != b]
            details["translation"].append({"direction": f"{source}>{target}", "identical": len(lines) - len(diffs),
                                           "total": len(lines), "differences": diffs})
            passed &= not diffs and len(lines) == SENTENCES

    with db.transaction(conn):
        conn.execute("INSERT INTO parity VALUES (?, ?, ?, ?)",
                     (runtime_key(), time.time(), int(passed), json.dumps(details, ensure_ascii=False)))
    if not passed:
        raise RuntimeError("parity failed: the bench doesn't reproduce volis exactly; see `bench parity-report`. "
                           "Nothing measured until this passes means anything.")
    return {"passed": True, "asr": [(d["recognizer"], d["language"], d["identical"]) for d in details["asr"]],
            "translation": [(d["direction"], d["identical"]) for d in details["translation"]]}


def latest(conn) -> dict:
    """The latest parity check for the current runtime, or None."""
    conn.executescript(SCHEMA)
    row = conn.execute("SELECT * FROM parity WHERE runtime = ? ORDER BY checked DESC LIMIT 1",
                       (runtime_key(),)).fetchone()
    return dict(row) if row else None


def require(conn) -> None:
    """Stop unless the current runtime has passed its parity check."""
    result = latest(conn)
    if not result:
        raise RuntimeError("no parity check for the current volis and engines; run `bench parity` first")
    if not result["passed"]:
        raise RuntimeError("the parity check for the current volis and engines failed; results can't count")


def report(conn) -> str:
    result = latest(conn)
    if not result:
        return "No parity check yet for the current volis and engines. Run: .\\bench.ps1 parity"
    d = json.loads(result["details"])
    lines = [f"Parity with volis: {'PASSED' if result['passed'] else 'FAILED'} "
             f"({time.strftime('%Y-%m-%d %H:%M', time.localtime(result['checked']))}, runtime {runtime_key()})"]
    for a in d["asr"]:
        lines.append(f"  ASR {a['recognizer']} ({a['language']}): {a['identical']} of {a['total']} transcripts identical")
        for x in a["differences"][:5]:
            lines.append(f"    {x['clip']}\n      bench: {x['bench']}\n      volis: {x['volis']}")
    for t in d["translation"]:
        lines.append(f"  translator {t['direction']}: {t['identical']} of {t['total']} translations identical")
        for x in t["differences"][:5]:
            lines.append(f"    {x['source'][:80]}\n      bench: {x['bench']}\n      volis: {x['volis']}")
    return "\n".join(lines)
