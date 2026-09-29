"""The test data in numbers: clips and sentences per test set and split, how
many FLEURS clips matched FLORES+, and what the contamination check found.
Used by `bench data`, the Round tab, and later the report."""

from bench import data
from bench.contamination import SCHEMA as CONTAMINATION_SCHEMA

SPLITS = ("development", "selection", "vault")


def tables(conn) -> dict:
    conn.executescript(data.SCHEMA)
    conn.executescript(CONTAMINATION_SCHEMA)
    out = {"clips": [], "text": [], "contamination": [], "matching": {}}
    # Speech: FLEURS clips count only once matched; other sets by their own ids.
    rows = conn.execute("""
        SELECT c.testset, c.lang, s.split, COUNT(*) AS n
        FROM clips c
        JOIN sentences s ON s.key = CASE WHEN c.testset LIKE 'fleurs-%' THEN c.key
                                         ELSE c.testset || ':' || c.clip END
        GROUP BY c.testset, c.lang, s.split""").fetchall()
    by_set = {}
    for r in rows:
        by_set.setdefault((r["testset"], r["lang"]), {})[r["split"]] = r["n"]
    for (testset, lang), counts in sorted(by_set.items()):
        out["clips"].append({"testset": testset, "lang": lang, **{s: counts.get(s, 0) for s in SPLITS}})
    # Text: FLORES+ sentences per language and split.
    rows = conn.execute("""
        SELECT f.lang, s.split, COUNT(*) AS n FROM flores f JOIN sentences s ON s.key = f.key
        GROUP BY f.lang, s.split""").fetchall()
    by_lang = {}
    for r in rows:
        by_lang.setdefault(r["lang"], {})[r["split"]] = r["n"]
    for lang, counts in sorted(by_lang.items()):
        out["text"].append({"lang": lang, **{s: counts.get(s, 0) for s in SPLITS}})
    for testset in ("fleurs-en", "fleurs-fa", "fleurs-ar"):
        r = conn.execute("SELECT COUNT(*) AS total, SUM(key IS NOT NULL) AS matched, "
                         "MIN(match) AS weakest FROM clips WHERE testset=?", (testset,)).fetchone()
        out["matching"][testset] = dict(r)
    try:
        conn.execute("ALTER TABLE contamination ADD COLUMN place TEXT")
    except Exception:  # noqa: BLE001 - the column exists already
        pass
    out["contamination"] = [dict(r) for r in conn.execute(
        "SELECT candidate, test, found, evidence, checked_repo, place FROM contamination "
        "ORDER BY candidate, test")]
    # A sentence in two splits would be a bug: the key is the table's primary key.
    out["duplicate_keys"] = conn.execute(
        "SELECT COUNT(*) FROM (SELECT key FROM sentences GROUP BY key HAVING COUNT(*) > 1)").fetchone()[0]
    return out


def summary(conn) -> str:
    t = tables(conn)
    lines = ["Speech clips per test set and split"]
    lines.append(f"  {'test set':16} {'lang':6} {'develop.':>9} {'select.':>8} {'vault':>6} {'total':>6}")
    for r in t["clips"]:
        total = sum(r[s] for s in SPLITS)
        lines.append(f"  {r['testset']:16} {r['lang']:6} {r['development']:9} {r['selection']:8} "
                     f"{r['vault']:6} {total:6}")
    lines.append("\nFLORES+ sentences (reference text) per language and split")
    for r in t["text"]:
        lines.append(f"  {r['lang']:6} {r['development']:9} {r['selection']:8} {r['vault']:6}")
    lines.append("\nFLEURS clips matched to FLORES+ sentences (by their English)")
    for testset, m in t["matching"].items():
        if m["total"]:
            weakest = f"{m['weakest']:.2f}" if m["weakest"] is not None else "-"
            lines.append(f"  {testset:12} {m['matched'] or 0} of {m['total']} matched; weakest match {weakest}")
    lines.append(f"\nSentences in more than one split: {t['duplicate_keys']}")
    lines.append("\nContamination (from model cards; no mention doesn't prove clean)")
    words = {"training": "MAY HAVE TRAINED ON IT (listed as training data)",
             "text": "MAY HAVE TRAINED ON IT (named in the card; read the sentence)",
             "evaluation": "evaluated on it (card's results), not listed as training", None: "no mention"}
    for r in t["contamination"]:
        lines.append(f"  {r['candidate']:22} {r['test']:13} {words.get(r['place'], 'no mention')}"
                     + (f"\n  {'':36}\"{r['evidence'][:100]}\"" if r["evidence"] else ""))
    return "\n".join(lines)
