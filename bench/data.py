"""Test data: downloading, preparing, matching FLEURS to FLORES+, and the
three-way split by sentence (model-bench.md, "Test data").

Everything here runs as queue jobs (bench prepare queues them), so a
download that drops resumes instead of starting again.

- FLORES+ (text, gated): the same 2,009 sentences in every language. A
  sentence's key is its FLORES+ split and id, e.g. "dev:12".
- FLEURS (speech, published as a loading script, so its automatic Parquet
  copy): recordings of FLORES sentences. Its validation and test splits are
  used. Each FLEURS clip is matched to a FLORES+ sentence by comparing its
  English transcript (en_us) with FLORES+ English; the other languages' clips
  share FLEURS's sentence ids. One recording per sentence per language.
- The Iraqi proxy (xtz999/iraqi_arabic_speech_youssef): speech and text only,
  unrelated to FLORES; labelled provisional everywhere.
- The user's clips (testsets/iraqi-user/, testsets/volis-recorded/), if any.

The split is by sentence key across all languages at once, assigned once
from a fixed seed, and stored: a sentence in development in Persian can never
be in the vault in English.
"""

import csv
import hashlib
import io
import json
import shutil
from difflib import SequenceMatcher
from pathlib import Path

from bench import db
from bench.config import ROOT, settings
from bench.textclean import clean

DATA_VERSION = "1"
CACHE = ROOT / "cache"
AUDIO = CACHE / "audio"
PARQUET_BRANCH = "refs/convert/parquet"
FLEURS_CONFIGS = {"fa_ir": "fa", "en_us": "en", "ar_eg": "ar"}
FLEURS_SPLITS = ("validation", "test")
FLORES_LANGUAGES = {"eng_Latn": "en", "pes_Arab": "fa", "acm_Arab": "ar-IQ", "arb_Arab": "ar"}
FLORES_SPLITS = ("dev", "devtest")
YOUSSEF = "xtz999/iraqi_arabic_speech_youssef"
RATE = 16000

SCHEMA = """
CREATE TABLE IF NOT EXISTS flores (          -- reference text: one row per sentence per language
    key TEXT NOT NULL, lang TEXT NOT NULL, text TEXT NOT NULL,
    PRIMARY KEY (key, lang));
CREATE TABLE IF NOT EXISTS clips (           -- speech: one row per recording
    testset TEXT NOT NULL,                   -- fleurs-fa, fleurs-en, fleurs-ar, youssef, iraqi-user, volis-recorded
    clip TEXT NOT NULL,                      -- the set's own id
    lang TEXT NOT NULL,
    audio TEXT NOT NULL,                     -- path to a 16 kHz mono WAV, relative to the app folder
    transcript TEXT NOT NULL,
    english TEXT,                            -- the user's English, for their own clips
    speaker TEXT,
    fleurs_id INTEGER,
    key TEXT,                                -- the FLORES sentence, once matched
    match REAL,                              -- English similarity of the match
    PRIMARY KEY (testset, clip));
CREATE TABLE IF NOT EXISTS sentences (       -- the split, assigned once and never changed
    key TEXT PRIMARY KEY, split TEXT NOT NULL);
"""


class DiskLow(Exception):
    """Not enough free space: the runner pauses the queue with this message."""


def connect():
    conn = db.connect()
    conn.executescript(SCHEMA)
    return conn


def check_disk(needed_bytes: int) -> None:
    free = shutil.disk_usage(CACHE if CACHE.exists() else ROOT).free
    keep = settings().get("disk", {}).get("min_free_gb", 20) * 1e9
    if free - needed_bytes < keep:
        raise DiskLow(f"downloading {needed_bytes / 1e9:.1f} GB would leave {(free - needed_bytes) / 1e9:.1f} GB "
                      f"free, under the {keep / 1e9:.0f} GB settings.yaml keeps. Free some space, then Start.")


# --- Downloading ----------------------------------------------------------------


def hf_files(repo: str, files: list, revision: str = None) -> list:
    """Download dataset files into cache/hf/<repo>/, skipping ones already there."""
    from huggingface_hub import HfApi, hf_hub_download
    from huggingface_hub.errors import GatedRepoError

    target = CACHE / "hf" / repo.replace("/", "__")
    api = HfApi()
    sizes = {e.path: getattr(e, "size", 0) or 0 for e in
             api.list_repo_tree(repo, repo_type="dataset", revision=revision, recursive=True)
             if hasattr(e, "size")}
    missing = [f for f in files if not (target / f).is_file()]
    check_disk(sum(sizes.get(f, 0) for f in missing))
    out = []
    for f in files:
        try:
            out.append(Path(hf_hub_download(repo, f, repo_type="dataset", revision=revision, local_dir=target)))
        except GatedRepoError as e:
            raise RuntimeError(f"{repo} is gated: open https://huggingface.co/datasets/{repo}, accept its "
                               "terms while logged in, run 'uv run hf auth login' here, then Retry failed") from e
    return out


def dataset_listing(repo: str, revision: str = None) -> list:
    from huggingface_hub import HfApi

    return [e.path for e in HfApi().list_repo_tree(repo, repo_type="dataset", revision=revision, recursive=True)
            if hasattr(e, "size")]


# --- Audio ------------------------------------------------------------------------


def write_wav(cell, path: Path) -> float:
    """A dataset audio cell ({bytes, path} or bytes) as a 16 kHz mono WAV.
    Returns its length in seconds."""
    import numpy as np
    import soundfile as sf
    import soxr

    data = cell.get("bytes") if isinstance(cell, dict) else cell
    samples, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    samples = samples.mean(axis=1)
    if rate != RATE:
        samples = soxr.resample(samples, rate, RATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.clip(samples, -1, 1), RATE, subtype="PCM_16")
    return len(samples) / RATE


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


# --- Jobs -------------------------------------------------------------------------


def prepare_flores(payload: dict) -> dict:
    files = [f"{s}/{code}.jsonl" for s in FLORES_SPLITS for code in FLORES_LANGUAGES]
    paths = hf_files("openlanguagedata/flores_plus", files)
    conn = connect()
    rows = []
    for path in paths:
        split, code = path.parent.name, path.stem
        with open(path, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                rows.append((f"{split}:{r['id']}", FLORES_LANGUAGES[code], r["text"]))
    with db.transaction(conn):
        conn.executemany("INSERT OR REPLACE INTO flores VALUES (?, ?, ?)", rows)
    return {"sentences": len({r[0] for r in rows}), "rows": len(rows)}


def prepare_fleurs(payload: dict) -> dict:
    """One FLEURS language: validation + test, one recording per sentence id."""
    import pyarrow.parquet as pq

    config = payload["config"]
    lang = FLEURS_CONFIGS[config]
    listing = dataset_listing("google/fleurs", PARQUET_BRANCH)
    files = [p for p in listing if p.startswith(f"{config}/") and p.split("/")[1] in FLEURS_SPLITS
             and p.endswith(".parquet")]
    if not files:
        raise RuntimeError(f"google/fleurs has no Parquet files for {config} on {PARQUET_BRANCH}")
    paths = hf_files("google/fleurs", files, PARQUET_BRANCH)
    testset = f"fleurs-{lang}"
    conn = connect()
    seen, rows = set(), []
    for path in paths:
        table = pq.read_table(path, columns=["id", "audio", "raw_transcription", "gender"])
        for r in table.to_pylist():
            if r["id"] in seen:
                continue   # one recording per sentence per language
            seen.add(r["id"])
            wav = AUDIO / testset / f"{r['id']}.wav"
            if not wav.is_file():
                write_wav(r["audio"], wav)
            rows.append((testset, str(r["id"]), lang, rel(wav), r["raw_transcription"] or "", None,
                         r.get("gender") and str(r["gender"]), r["id"]))
    with db.transaction(conn):
        conn.executemany(
            "INSERT OR REPLACE INTO clips (testset, clip, lang, audio, transcript, english, speaker, fleurs_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return {"testset": testset, "clips": len(rows)}


def prepare_youssef(payload: dict) -> dict:
    import pyarrow.parquet as pq

    files = [p for p in dataset_listing(YOUSSEF) if p.endswith(".parquet")]
    paths = hf_files(YOUSSEF, files)
    conn = connect()
    rows, n = [], 0
    for path in sorted(paths):
        for r in pq.read_table(path, columns=["audio", "text"]).to_pylist():
            n += 1
            wav = AUDIO / "youssef" / f"{n:05}.wav"
            if not wav.is_file():
                write_wav(r["audio"], wav)
            rows.append(("youssef", f"{n:05}", "ar-IQ", rel(wav), r["text"] or "", None, "youssef", None))
    with db.transaction(conn):
        conn.executemany(
            "INSERT OR REPLACE INTO clips (testset, clip, lang, audio, transcript, english, speaker, fleurs_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return {"testset": "youssef", "clips": len(rows)}


def prepare_user(payload: dict) -> dict:
    """testsets/<name>/speech.csv (clip, speaker, iraqi_text or text, english_text) + clips/*.wav."""
    import soundfile as sf

    name = payload["name"]
    folder = ROOT / "testsets" / name
    table = folder / "speech.csv"
    if not table.is_file():
        return {"testset": name, "clips": 0, "note": f"{table} not present"}
    conn = connect()
    rows = []
    with open(table, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            source = folder / "clips" / r["clip"]
            if not source.suffix:
                source = source.with_suffix(".wav")
            if not source.is_file():
                raise RuntimeError(f"{table}: {source} doesn't exist")
            wav = AUDIO / name / (source.stem + ".wav")
            if not wav.is_file():
                write_wav(source.read_bytes(), wav)
            text = r.get("iraqi_text") or r.get("text") or ""
            rows.append((name, source.stem, r.get("lang") or "ar-IQ", rel(wav), text,
                         r.get("english_text"), r.get("speaker"), None))
    with db.transaction(conn):
        conn.executemany(
            "INSERT OR REPLACE INTO clips (testset, clip, lang, audio, transcript, english, speaker, fleurs_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return {"testset": name, "clips": len(rows)}


def similarity(a: str, b: str, lang: str = "en") -> float:
    # autojunk=False: by default SequenceMatcher skips frequent characters in
    # texts over 200 characters, which badly underrates long Arabic sentences.
    return SequenceMatcher(None, clean(a, lang), clean(b, lang), autojunk=False).ratio()


def split_for(key: str, seed: int, s: dict) -> str:
    """development / selection / vault, from a hash of the seed and the key:
    the same key always lands in the same split, on any machine."""
    h = int(hashlib.sha256(f"{seed}:{key}".encode("utf-8")).hexdigest()[:12], 16) / 16 ** 12
    if h < s["development"]:
        return "development"
    if h < s["development"] + s["selection"]:
        return "selection"
    return "vault"


def match_and_split(payload: dict) -> dict:
    """Match FLEURS clips to FLORES+ sentences by their English, and give
    every sentence (and every non-FLORES clip) its split, once."""
    conn = connect()
    waiting = conn.execute("SELECT key FROM jobs WHERE kind LIKE 'prepare_%' AND status != 'done'").fetchall()
    if waiting:
        raise RuntimeError(f"{len(waiting)} preparation job(s) haven't finished yet ({waiting[0]['key']}, ...); "
                           "matching needs all of them")
    threshold = settings().get("matching", {}).get("min_english_similarity", 0.85)
    english = {r["key"]: r["text"] for r in conn.execute("SELECT key, text FROM flores WHERE lang='en'")}
    if not english:
        raise RuntimeError("FLORES+ isn't prepared yet")
    exact = {clean(t, "en"): k for k, t in english.items()}
    fleurs_en = conn.execute("SELECT fleurs_id, transcript FROM clips WHERE testset='fleurs-en'").fetchall()
    matched, weak = {}, 0
    for row in fleurs_en:
        text = row["transcript"]
        key = exact.get(clean(text, "en"))
        score = 1.0 if key else 0.0
        if not key:
            first = clean(text, "en").split()[:3]
            pool = [k for k, t in english.items() if clean(t, "en").split()[:3] == first] or list(english)
            key, score = max(((k, similarity(text, english[k])) for k in pool), key=lambda x: x[1])
        if score >= threshold:
            matched[row["fleurs_id"]] = (key, score)
        else:
            weak += 1
    with db.transaction(conn):
        conn.execute("UPDATE clips SET key=NULL, match=NULL WHERE testset LIKE 'fleurs-%'")
        for fid, (key, score) in matched.items():
            conn.execute("UPDATE clips SET key=?, match=? WHERE testset LIKE 'fleurs-%' AND fleurs_id=?",
                         (key, score, fid))

    # The other languages share FLEURS's sentence ids with English; check each
    # clip against FLORES+'s own text in its language too, and drop those that
    # don't match. (One FLEURS Arabic clip, 1602, carries another sentence.)
    own_min = settings().get("matching", {}).get("min_own_language_similarity", 0.5)
    dropped = {}
    rows = conn.execute("""SELECT c.testset, c.clip, c.lang, c.transcript, f.text FROM clips c
                           JOIN flores f ON f.key = c.key AND f.lang = c.lang
                           WHERE c.testset LIKE 'fleurs-%' AND c.lang != 'en'""").fetchall()
    with db.transaction(conn):
        for r in rows:
            if similarity(r["transcript"], r["text"], r["lang"]) < own_min:
                conn.execute("UPDATE clips SET key=NULL, match=NULL WHERE testset=? AND clip=?",
                             (r["testset"], r["clip"]))
                dropped.setdefault(r["testset"], []).append(r["clip"])

    s = settings()["splits"]
    seed = s["seed"]
    keys = set(english)
    # Clips that aren't FLORES sentences are split by their own id, in their own namespace.
    for r in conn.execute("SELECT testset, clip FROM clips WHERE testset NOT LIKE 'fleurs-%'"):
        keys.add(f"{r['testset']}:{r['clip']}")
    existing = {r["key"] for r in conn.execute("SELECT key FROM sentences")}
    new = [(k, split_for(k, seed, s)) for k in sorted(keys - existing)]
    with db.transaction(conn):
        conn.executemany("INSERT INTO sentences VALUES (?, ?)", new)
    return {"fleurs_en_clips": len(fleurs_en), "matched": len(matched), "unmatched": weak,
            "dropped_own_language": dropped, "new_sentences_split": len(new)}


def queue(conn) -> int:
    """Queue every preparation job (reused if already done)."""
    added = 0
    added += db.add_job(conn, "prepare_flores", f"data{DATA_VERSION}:flores", {})
    for config in FLEURS_CONFIGS:
        added += db.add_job(conn, "prepare_fleurs", f"data{DATA_VERSION}:fleurs:{config}", {"config": config})
    added += db.add_job(conn, "prepare_youssef", f"data{DATA_VERSION}:youssef", {})
    for name in ("iraqi-user", "volis-recorded"):
        # The key carries a fingerprint of speech.csv: new clips mean a new job.
        table = ROOT / "testsets" / name / "speech.csv"
        mark = hashlib.sha256(table.read_bytes()).hexdigest()[:12] if table.is_file() else "none"
        added += db.add_job(conn, "prepare_user", f"data{DATA_VERSION}:user:{name}:{mark}", {"name": name})
    added += db.add_job(conn, "match_and_split", f"data{DATA_VERSION}:match-split", {})
    return added
