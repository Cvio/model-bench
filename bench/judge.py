"""The judge (model-bench.md, "Failures"): the assistant model reads each
translation beside its source and a professional reference, and names the
worst thing wrong with it, from a fixed list of categories.

Its labels count only once they've earned trust: a fluent speaker rates a
sample (bench.review), and if the judge agrees with the human on critical
errors less than min_critical_agreement of the time (settings.yaml), the
judged categories are shown as "unconfirmed".

The assistant model is set in machine.yaml (assistant, assistant_gguf). For
now it's Qwen3-8B, run on the CPU; README "Change the judge" says how to use
a stronger one.
"""

import re
from pathlib import Path

from bench import config, db, runners
from bench.config import ROOT

# (key, severity, what the judge is told it means)
CATEGORIES = [
    ("ok", "none", "a correct translation (small wording differences from the reference are fine)"),
    ("reversed", "critical", "meaning reversed, e.g. a negation added or lost"),
    ("wrong_person", "critical", "wrong person: who did what to whom is changed"),
    ("invented", "critical", "invented content: says something that isn't in the source"),
    ("dangerous", "critical", "dangerous mistranslation of health, medication, numbers, names or places"),
    ("answered", "critical", "answered or commented on the text instead of translating it"),
    ("filler", "minor", "a filler or spoken habit treated as a word"),
    ("stiff", "minor", "stiff or unnatural, but correct"),
    ("formal", "minor", "formal language where the dialect was asked for"),
]
SEVERITY = {k: s for k, s, _ in CATEGORIES}
CRITICAL = [k for k, s, _ in CATEGORIES if s == "critical"]
LANGUAGE_NAMES = {"en": "English", "fa": "Persian", "ar": "Modern Standard Arabic", "ar-IQ": "Iraqi Arabic"}
PROMPT_VERSION = 2          # bump when prompt() changes: labels are kept per judge and prompt version
JUDGE_CONTEXT = 2048
BATCH = 25

SCHEMA = """
CREATE TABLE IF NOT EXISTS judged (
    mt_key TEXT NOT NULL, item TEXT NOT NULL, judge TEXT NOT NULL,
    category TEXT NOT NULL, raw TEXT, seconds REAL,
    PRIMARY KEY (mt_key, item, judge));
"""


def judge_model() -> tuple:
    """(judge id, GGUF path) from machine.yaml."""
    m = config.machine()
    if (m.get("assistant") or "local") != "local":
        raise RuntimeError("only a local assistant model is supported so far; set assistant: local in machine.yaml")
    path = Path(m.get("assistant_gguf") or "")
    if not path.is_file():
        raise RuntimeError(f"machine.yaml's assistant_gguf isn't a file: '{path}'. See README, 'Change the judge'.")
    return f"{path.stem}-p{PROMPT_VERSION}", path


def prompt(source: str, reference: str, output: str, source_lang: str, target_lang: str) -> str:
    names = "\n".join(f"- {k}: {d}" for k, _, d in CATEGORIES)
    dialect = (" The translation was asked to be in the Iraqi dialect, not formal Arabic."
               if target_lang == "ar-IQ" else "")
    user = (f"You check translations from {LANGUAGE_NAMES.get(source_lang, source_lang)} into "
            f"{LANGUAGE_NAMES.get(target_lang, target_lang)}.{dialect}\n\n"
            f"Source: {source}\nReference translation (by a professional): {reference}\n"
            f"Translation to check: {output}\n\n"
            f"Pick the single worst problem with the translation to check, from this list:\n{names}\n\n"
            "Compare meaning, not wording: if the translation says the same thing as the reference, even "
            "in different words, answer ok. Only name a problem you can point to. Critical problems come "
            "before minor ones. Answer with the key only, one word.")
    # Qwen3 chat format, with an empty thinking block so it answers directly.
    return f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def parse(raw: str) -> str:
    """The first category key in the answer, or 'unparsed'."""
    words = re.findall(r"[a-z_]+", (raw or "").lower())
    for w in words:
        if w in SEVERITY:
            return w
    return "unparsed"


def judge_job(payload: dict) -> dict:
    conn = db.connect()
    conn.executescript(SCHEMA)
    judge_id, gguf = judge_model()
    args = ["--ctx-size", str(JUDGE_CONTEXT), "--threads", str(runners.THREADS), "--threads-batch",
            str(runners.THREADS), "--parallel", "1", "--no-warmup", "--reasoning-format", "none", "--no-jinja"]
    rows = []
    with runners.Translator(gguf, ROOT / "cache" / "logs", server_args=args) as t:
        for it in payload["items"]:
            raw, seconds = t.raw(prompt(it["source"], it["reference"], it["output"],
                                        payload["source_lang"], payload["target_lang"]), n_predict=8)
            rows.append((payload["mt_key"], it["item"], judge_id, parse(raw), raw, seconds))
    with db.transaction(conn):
        conn.executemany("INSERT OR REPLACE INTO judged VALUES (?, ?, ?, ?, ?, ?)", rows)
    return {"judged": len(rows), "unparsed": sum(r[3] == "unparsed" for r in rows)}


def queue(conn) -> dict:
    """Queue judge jobs for every configuration's judged sample (see
    bench.review.judged_keys); items already judged by this judge are skipped."""
    from bench import results, review

    judge_id, _ = judge_model()
    conn.executescript(SCHEMA)
    done = {(r["mt_key"], r["item"]) for r in conn.execute("SELECT mt_key, item FROM judged WHERE judge = ?",
                                                           (judge_id,))}
    n = int(review.setting("judge", "items_per_config", 100))
    added = items = 0
    for r in results.compute(conn, keep_items=True):
        if not r.get("mt_key") or not r["per_item"]:
            continue
        todo = [k for k in review.judged_keys(r, n) if (r["mt_key"], k) not in done]
        items += len(todo)
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            payload = {"mt_key": r["mt_key"], "source_lang": r["source_lang"], "target_lang": r["target_lang"],
                       "items": [{"item": k, "source": r["per_item"][k]["out"]["source"],
                                  "reference": r["per_item"][k]["ref"], "output": r["per_item"][k]["out"]["output"]}
                                 for k in batch]}
            added += db.add_job(conn, "judge", f"judge:{judge_id}:{r['mt_key']}:{batch[0]}:{len(batch)}", payload)
    return {"judge": judge_id, "jobs": added, "items": items}
