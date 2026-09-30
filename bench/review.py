"""Human review (model-bench.md, "Human review"), as plain data so it can be
tested; the Review tab only draws it.

- The judged sample: per configuration, a fixed set of items, the same keys
  for every configuration in a direction (so comparisons stay paired). Its
  size is judge.items_per_config in settings.yaml.
- Packets: for each direction's top configurations (the baseline, and the
  best other one by chrF), the first review.outputs_per_config items of the
  judged sample, so every rated item also has a judge label. Speech
  recognition packets hold review.asr_clips_per_config clips per recognizer.
- A rating is acceptable, minor or critical (with a category for critical).
- Agreement: how often the judge and the human agree that an output has a
  critical error, as a share and as Cohen's kappa (which discounts agreement
  that would happen by chance). Below judge.min_critical_agreement, the
  judged categories are "unconfirmed".
"""

import csv
import hashlib
import time
from dataclasses import dataclass, field

from bench import judge, stats
from bench.config import settings

RATINGS = ("acceptable", "minor", "critical")
SCHEMA = """
CREATE TABLE IF NOT EXISTS ratings (
    key TEXT NOT NULL, item TEXT NOT NULL, rating TEXT NOT NULL, category TEXT,
    rater TEXT, ts REAL NOT NULL, PRIMARY KEY (key, item));
"""


def setting(section: str, name: str, default):
    return (settings().get(section) or {}).get(name, default)


def sample(keys, n: int) -> list:
    """A fixed pseudo-random pick of n keys: the same keys whatever order they
    come in, and the same for every configuration that ran them."""
    return sorted(keys, key=lambda k: hashlib.sha1(str(k).encode("utf-8")).hexdigest())[:n]


@dataclass
class Item:
    key: str                # mt_key (translations) or asr_key (recognition)
    item: str
    source: str
    reference: str
    output: str
    audio: str = ""         # a clip to play, for recognition packets
    rating: str = ""
    category: str = ""


@dataclass
class Packet:
    name: str               # e.g. "en>fa: parakeet-volis + qwen3-1.7b-volis"
    direction: str
    config: str
    kind: str               # "translation" or "asr"
    items: list = field(default_factory=list)

    def rated(self) -> int:
        return sum(bool(i.rating) for i in self.items)


def top_configs(rows: list) -> dict:
    """Per direction: the baseline, and the best other configuration by chrF."""
    by_dir = {}
    for r in rows:
        by_dir.setdefault(r["direction"], []).append(r)
    out = {}
    for d, rs in by_dir.items():
        base = [r for r in rs if r["baseline"]]
        others = sorted((r for r in rs if not r["baseline"] and r.get("chrf") is not None),
                        key=lambda r: -r["chrf"])
        out[d] = base[:1] + others[:1]
    return out


def ratings(conn) -> dict:
    conn.executescript(SCHEMA)
    return {(r["key"], r["item"]): (r["rating"], r["category"] or "")
            for r in conn.execute("SELECT key, item, rating, category FROM ratings")}


def save_rating(conn, key: str, item: str, rating: str, category: str = "", rater: str = "") -> None:
    if rating not in RATINGS:
        raise ValueError(f"a rating is one of {', '.join(RATINGS)}")
    if rating == "critical" and category and category not in judge.CRITICAL:
        raise ValueError(f"a critical error's category is one of {', '.join(judge.CRITICAL)}")
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR REPLACE INTO ratings VALUES (?, ?, ?, ?, ?, ?)",
                 (key, item, rating, category if rating == "critical" else "", rater, time.time()))
    conn.commit()


def clear_rating(conn, key: str, item: str) -> None:
    conn.executescript(SCHEMA)
    conn.execute("DELETE FROM ratings WHERE key = ? AND item = ?", (key, item))
    conn.commit()


def packets(conn, rows: list) -> list:
    """rows: results.compute(conn, keep_items=True)."""
    have = ratings(conn)
    n_mt = int(setting("review", "outputs_per_config", 30))
    n_asr = int(setting("review", "asr_clips_per_config", 10))
    n_judged = int(setting("judge", "items_per_config", 100))
    out = []
    for direction, configs in top_configs([r for r in rows if r.get("mt_key")]).items():
        for r in configs:
            chosen = sample(judged_keys(r, n_judged), n_mt)
            p = Packet(f"{direction}: {r['asr'] or '(text)'} + {r['translator']}", direction, r["config"],
                       "translation")
            for k in chosen:
                it = r["per_item"][k]
                rating, cat = have.get((r["mt_key"], k), ("", ""))
                p.items.append(Item(r["mt_key"], k, it["out"]["source"], it["ref"], it["out"]["output"],
                                    rating=rating, category=cat))
            out.append(p)
    asr_rows = [r for r in rows if r.get("asr_key") and r["direction"].startswith("asr ")]
    for r in asr_rows:
        p = Packet(f"{r['direction']}: {r['asr']}", r["direction"], r["config"], "asr")
        for k in sample(r["per_item"], n_asr):
            it = r["per_item"][k]
            rating, cat = have.get((r["asr_key"], k), ("", ""))
            p.items.append(Item(r["asr_key"], k, "", it["asr_ref"], it["asr_hyp"], audio=it.get("audio", ""),
                                rating=rating, category=cat))
        out.append(p)
    return out


def judged_keys(row: dict, n: int) -> list:
    """The judged sample of one configuration: n items, refused outputs left
    out (they're already counted as failures, and there's nothing to judge)."""
    return sample([k for k, it in row["per_item"].items() if not it["out"]["refusal"] and it["out"]["output"]], n)


# --- Agreement --------------------------------------------------------------------------


def kappa(a: list, b: list):
    """Cohen's kappa for two raters' labels on the same items, or None."""
    n = len(a)
    if n == 0:
        return None
    labels = set(a) | set(b)
    observed = sum(x == y for x, y in zip(a, b)) / n
    expected = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


@dataclass
class Agreement:
    items: int
    critical_agreement: float = None    # share of items where both say critical, or both say not
    critical_kappa: float = None
    severity_kappa: float = None        # acceptable/minor/critical versus ok/minor/critical
    confirmed: bool = False

    def words(self) -> str:
        if not self.items:
            return "no rated items have a judge label yet"
        k = "—" if self.critical_kappa is None else f"{self.critical_kappa:.2f}"
        state = "confirmed" if self.confirmed else "UNCONFIRMED"
        return (f"judge agrees with you on critical errors {self.critical_agreement:.0%} of {self.items} items "
                f"(kappa {k}): {state}")


def severity_of_rating(rating: str) -> str:
    return {"acceptable": "none", "minor": "minor", "critical": "critical"}[rating]


def agreement(pairs: list) -> Agreement:
    """pairs: (human rating, judge category) for items that have both."""
    pairs = [(h, j) for h, j in pairs if h and j and j != "unparsed"]
    if not pairs:
        return Agreement(0)
    human_crit = [h == "critical" for h, _ in pairs]
    judge_crit = [judge.SEVERITY[j] == "critical" for _, j in pairs]
    share = sum(x == y for x, y in zip(human_crit, judge_crit)) / len(pairs)
    need = float(setting("judge", "min_critical_agreement", 0.80))
    return Agreement(len(pairs), share, kappa(human_crit, judge_crit),
                     kappa([severity_of_rating(h) for h, _ in pairs], [judge.SEVERITY[j] for _, j in pairs]),
                     share >= need)


def acceptance(ratings_list: list, redraws: int = 10000, confidence: float = 0.95):
    """(share acceptable, low, high), or None with no ratings."""
    if not ratings_list:
        return None
    m = stats.rate_metric([r == "acceptable" for r in ratings_list])
    return stats.interval(m, redraws=redraws, confidence=confidence)


# --- The CSV route ----------------------------------------------------------------------

CSV_FIELDS = ["key", "item", "source", "reference", "output", "rating", "category"]


def write_csv(packet: Packet, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:     # -sig: Excel reads it as UTF-8
        w = csv.DictWriter(f, CSV_FIELDS)
        w.writeheader()
        for i in packet.items:
            w.writerow({"key": i.key, "item": i.item, "source": i.source, "reference": i.reference,
                        "output": i.output, "rating": i.rating, "category": i.category})


def read_csv(conn, path) -> int:
    """Store the ratings filled in a packet CSV; returns how many."""
    n = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rating = (row.get("rating") or "").strip().lower()
            if rating:
                save_rating(conn, row["key"], row["item"], rating, (row.get("category") or "").strip().lower(),
                            rater="csv")
                n += 1
    return n


def next_unrated(packet: Packet, after: int = -1) -> int:
    """The index of the next unrated item after `after`, wrapping around; the
    same index if everything is rated."""
    n = len(packet.items)
    for step in range(1, n + 1):
        i = (after + step) % n
        if not packet.items[i].rating:
            return i
    return max(after, 0) % n if n else 0


def right_to_left(text: str) -> bool:
    """Mostly Arabic or Persian letters: shown right to left."""
    letters = [c for c in text or "" if c.isalpha()]
    return bool(letters) and sum("؀" <= c <= "ۿ" or "ﭐ" <= c <= "﻿" for c in letters) / len(letters) > 0.5
