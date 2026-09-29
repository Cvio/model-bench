"""Could a candidate have trained on a test set? (model-bench.md, "Contamination")

For each candidate, its Hugging Face model card is searched for each test
set's name: the model itself for an hf: source, its `origin` for a volis: one.
Where the name appears matters, so each hit is sorted by where it was found:

- **training**: the card's own list of training datasets (`datasets:` or a
  `dataset:` tag). The model says it trained on it: flagged.
- **text**: the card's prose mentions it. It might describe training data, or
  just a benchmark: flagged, with the sentence shown, for a person to judge.
- **evaluation**: only in the card's evaluation results (`model-index`). The
  model was *scored* on it, which isn't training on it: noted, not flagged.

A flagged candidate's score on that test is shown as "may have trained on
this test" and left out of that test's ranking. A card that lists nothing
proves nothing: "no mention" isn't "clean", and the report says so.
"""

import json
import re

from bench import db

TESTS = {
    "fleurs": [r"\bfleurs\b", r"google/fleurs"],
    "flores": [r"\bflores(?:[-_ ]?(?:plus|\+|101|200))?\b", r"openlanguagedata/flores"],
    "common_voice": [r"common[\s_-]?voice", r"mozilla-foundation/common_voice"],
    "youssef": [r"youssef", r"iraqi_arabic_speech"],
}
FLAGGED = ("training", "text")
SCHEMA = """
CREATE TABLE IF NOT EXISTS contamination (
    candidate TEXT NOT NULL, test TEXT NOT NULL, found INTEGER NOT NULL,
    evidence TEXT, checked_repo TEXT, place TEXT,
    PRIMARY KEY (candidate, test));
"""


def first_hit(text: str, patterns: list):
    for pattern in patterns:
        m = re.search(pattern, text or "", re.IGNORECASE)
        if m:
            start = max(0, m.start() - 60)
            return " ".join(text[start:m.end() + 60].split())
    return None


def strip_front_matter(body: str) -> str:
    """The card's prose, without its YAML header (searched separately)."""
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            return body[end + 4:]
    return body


def search(training: str, prose: str, evaluation: str) -> dict:
    """{test: (place, evidence) or None}, taking the strongest place found."""
    out = {}
    for test, patterns in TESTS.items():
        out[test] = None
        for place, text in (("training", training), ("text", prose), ("evaluation", evaluation)):
            hit = first_hit(text, patterns)
            if hit:
                out[test] = (place, hit)
                break
    return out


def check(payload: dict) -> dict:
    from huggingface_hub import HfApi, ModelCard

    repo, commit = payload["repo"], payload.get("commit") or None
    info = HfApi().model_info(repo, revision=commit)
    card = info.card_data.to_dict() if info.card_data else {}
    try:
        body = ModelCard.load(repo, revision=commit).text
    except Exception:  # noqa: BLE001 - no README: search what there is
        body = ""
    training = " ".join([json.dumps(card.get("datasets") or []),
                         " ".join(t for t in (info.tags or []) if t.startswith("dataset:"))])
    evaluation = json.dumps(card.get("model-index") or card.get("model_index") or [], default=str)
    found = search(training, strip_front_matter(body), evaluation)
    conn = db.connect()
    conn.executescript(SCHEMA)
    try:
        conn.execute("ALTER TABLE contamination ADD COLUMN place TEXT")
    except Exception:  # noqa: BLE001 - the column exists already
        pass
    with db.transaction(conn):
        for test, hit in found.items():
            place, evidence = hit or (None, None)
            conn.execute("INSERT OR REPLACE INTO contamination "
                         "(candidate, test, found, evidence, checked_repo, place) VALUES (?, ?, ?, ?, ?, ?)",
                         (payload["candidate"], test, int(place in FLAGGED), evidence,
                          f"{repo}@{(commit or 'main')[:12]}", place))
    return {"repo": repo, "found": {t: (h[0] if h else None) for t, h in found.items()}}


def queue(conn, candidates: dict) -> int:
    from bench.config import parse_source

    added = 0
    for role in ("asr", "translators"):
        for e in candidates.get(role) or []:
            ref = e.get("source") if str(e.get("source", "")).startswith("hf:") else e.get("origin")
            parsed = parse_source(ref) if ref else None
            if parsed and parsed[0] == "hf":
                _, repo, commit = parsed
                added += db.add_job(conn, "contamination", f"contamination2:{e['id']}:{repo}@{commit}",
                                    {"candidate": e["id"], "repo": repo, "commit": commit})
    return added
