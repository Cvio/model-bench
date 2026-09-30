"""End-to-end runs: the jobs that transcribe, translate and measure.

`bench run` queues, for the round's configurations on one split:
1. transcribe jobs: each recognizer transcribes each clip once (in batches);
   the transcripts are cached by recognizer (asr_key), so every translator
   reuses them;
2. a plan job, after them: it queues the translate jobs, once the
   transcripts they need exist;
3. translate jobs: batches of sentences through llama-server, each output
   judged by volis's rules.

Every job records the time per item and the peak memory of the model's
process. Nothing runs unless the current volis and engines passed parity.
"""

import json
import time

from bench import configs, data, db, parity, runners
from bench.config import ROOT, settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS asr_out (
    asr_key TEXT NOT NULL, testset TEXT NOT NULL, clip TEXT NOT NULL,
    text TEXT NOT NULL, seconds REAL, PRIMARY KEY (asr_key, testset, clip));
CREATE TABLE IF NOT EXISTS mt_out (
    mt_key TEXT NOT NULL, item TEXT NOT NULL, source TEXT NOT NULL,
    output TEXT NOT NULL, refusal TEXT, raw TEXT, seconds REAL,
    PRIMARY KEY (mt_key, item));
CREATE TABLE IF NOT EXISTS memory (
    model TEXT PRIMARY KEY, peak_mb REAL NOT NULL);
CREATE TABLE IF NOT EXISTS configs (
    id TEXT PRIMARY KEY, direction TEXT NOT NULL, asr_key TEXT, mt_key TEXT, parts TEXT NOT NULL);
"""
BATCH_CLIPS = 40
BATCH_SENTENCES = 25


def connect():
    conn = data.connect()
    conn.executescript(SCHEMA)
    return conn


def run_settings() -> dict:
    return {"split": "selection", "max_proxy_clips": 300, "max_text_sentences": 200,
            **(settings().get("run") or {})}


def speech_clips(conn, testset: str, split: str, limit: int = None) -> list:
    """(clip id, audio path, transcript, sentence key) for a speech test set's split."""
    if testset.startswith("fleurs-"):
        rows = conn.execute("""SELECT c.clip, c.audio, c.transcript, c.key FROM clips c
                               JOIN sentences s ON s.key = c.key
                               WHERE c.testset = ? AND s.split = ? ORDER BY c.clip""", (testset, split))
    else:
        rows = conn.execute("""SELECT c.clip, c.audio, c.transcript, c.testset || ':' || c.clip FROM clips c
                               JOIN sentences s ON s.key = c.testset || ':' || c.clip
                               WHERE c.testset = ? AND s.split = ? ORDER BY c.clip""", (testset, split))
    out = [tuple(r) for r in rows]
    return out[:limit] if limit else out


def text_items(conn, lang: str, split: str, limit: int = None) -> list:
    rows = conn.execute("""SELECT f.key, f.text FROM flores f JOIN sentences s ON s.key = f.key
                           WHERE f.lang = ? AND s.split = ? ORDER BY f.key""", (lang, split)).fetchall()
    out = [tuple(r) for r in rows]
    return out[:limit] if limit else out


def remember_peak(conn, model: str, peak_mb: float) -> None:
    with db.transaction(conn):
        conn.execute("INSERT INTO memory VALUES (?, ?) ON CONFLICT(model) DO UPDATE SET "
                     "peak_mb = MAX(peak_mb, excluded.peak_mb)", (model, peak_mb))


# --- Jobs -------------------------------------------------------------------------


def transcribe_job(payload: dict) -> dict:
    conn = connect()
    wavs = [ROOT / a for a in payload["audio"]]
    texts, seconds, peak = runners.transcribe(payload["source"], payload["language"], wavs, measure=True)
    with db.transaction(conn):
        conn.executemany("INSERT OR REPLACE INTO asr_out VALUES (?, ?, ?, ?, ?)",
                         [(payload["asr_key"], payload["testset"], clip, t, s)
                          for clip, t, s in zip(payload["clips"], texts, seconds)])
    remember_peak(conn, f"asr:{payload['asr_id']}", peak)
    return {"clips": len(texts), "peak_mb": round(peak)}


def translate_job(payload: dict) -> dict:
    conn = connect()
    gguf = runners.resolve(payload["source"])
    rows = []
    with runners.Translator(gguf, ROOT / "cache" / "logs") as t:
        for item, text in payload["items"]:
            r = t.translate(text, payload["template"])
            rows.append((payload["mt_key"], item, text, r["text"], r["refusal"], r["raw"], r["seconds"]))
        peak = t.peak_mb()
    with db.transaction(conn):
        conn.executemany("INSERT OR REPLACE INTO mt_out VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    remember_peak(conn, f"mt:{payload['translator_id']}", peak)
    return {"sentences": len(rows), "peak_mb": round(peak)}


def plan_job(payload: dict) -> dict:
    """Queue the translate jobs, now that the transcripts exist."""
    conn = connect()
    waiting = conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'transcribe' AND status != 'done'").fetchone()[0]
    if waiting:
        raise RuntimeError(f"{waiting} transcribe job(s) haven't finished; translations need their transcripts")
    s = run_settings()
    added = 0
    for c in configs.build():
        if c.direction.kind == "asr":
            continue
        d = c.direction
        if d.kind == "speech":
            clips = speech_clips(conn, d.testset, s["split"])
            transcripts = {r["clip"]: r["text"] for r in conn.execute(
                "SELECT clip, text FROM asr_out WHERE asr_key = ? AND testset = ?", (c.asr_key, d.testset))}
            items = [(f"{c.asr_key}:{d.testset}:{clip}", transcripts[clip]) for clip, *_ in clips if clip in transcripts]
        else:
            items = [(key, text) for key, text in text_items(conn, d.source, s["split"], s["max_text_sentences"])]
        done = {r[0] for r in conn.execute("SELECT item FROM mt_out WHERE mt_key = ?", (c.mt_key,))}
        items = [i for i in items if i[0] not in done]
        for n in range(0, len(items), BATCH_SENTENCES):
            batch = items[n:n + BATCH_SENTENCES]
            added += db.add_job(conn, "translate", f"translate:{c.mt_key}:{batch[0][0]}:{len(batch)}", {
                "mt_key": c.mt_key, "source": c.translator["source"], "translator_id": c.translator["id"],
                "template": c.template, "items": batch})
    return {"translate_jobs": added}


def queue(conn) -> dict:
    """Queue a run of the current configurations on the configured split."""
    parity.require(conn)
    s = run_settings()
    conn.executescript(SCHEMA)
    built = configs.build()
    with db.transaction(conn):
        for c in built:
            conn.execute("INSERT OR REPLACE INTO configs VALUES (?, ?, ?, ?, ?)",
                         (c.id, c.direction.id, c.asr_key, c.mt_key, json.dumps(c.parts, ensure_ascii=False)))
    added, seen = 0, set()
    for c in built:
        if not c.asr:
            continue
        d = c.direction
        if (c.asr_key, d.testset) in seen:
            continue
        seen.add((c.asr_key, d.testset))
        limit = s["max_proxy_clips"] if d.provisional else None
        clips = speech_clips(conn, d.testset, s["split"], limit)
        done = {r[0] for r in conn.execute("SELECT clip FROM asr_out WHERE asr_key = ? AND testset = ?",
                                           (c.asr_key, d.testset))}
        clips = [x for x in clips if x[0] not in done]
        for n in range(0, len(clips), BATCH_CLIPS):
            batch = clips[n:n + BATCH_CLIPS]
            added += db.add_job(conn, "transcribe", f"transcribe:{c.asr_key}:{d.testset}:{batch[0][0]}:{len(batch)}", {
                "asr_key": c.asr_key, "asr_id": c.asr["id"], "source": c.asr["source"], "language": d.source,
                "testset": d.testset, "clips": [x[0] for x in batch], "audio": [x[1] for x in batch]})
    added += db.add_job(conn, "plan", f"plan:{time.time():.0f}", {})
    return {"configurations": len(built), "jobs": added}
