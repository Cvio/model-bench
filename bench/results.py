"""Per-configuration numbers, worked out from the stored outputs.

For each configuration on a split:
- how many items were run, and how many were refused or came out empty;
- ASR: CER (character error rate) against the clip's transcript, after both
  are cleaned the same way;
- translation: chrF against the FLORES+ reference, after both are cleaned the
  same way;
- latency per item (recognition + translation, up to the finished
  translation), median and 90th percentile;
- peak memory of each model, and whether recognizer + translator fit the
  laptop's memory with room left for volis's voice and the system.

These are point estimates. Confidence intervals and paired comparisons are
B5's; until then every difference here is unestablished.
"""

import statistics

from bench import configs, run
from bench.config import machine
from bench.textclean import clean

VOICE_AND_SYSTEM_GB = 3.0   # volis's voice model, its window, and Windows itself


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def cer(refs: list, hyps: list, lang: str) -> float:
    errors = chars = 0
    for r, h in zip(refs, hyps):
        r, h = clean(r, lang).replace(" ", ""), clean(h, lang).replace(" ", "")
        errors += edit_distance(r, h)
        chars += len(r)
    return 100 * errors / max(chars, 1)


def chrf(refs: list, hyps: list, lang: str) -> float:
    import sacrebleu

    return sacrebleu.CHRF().corpus_score([clean(h, lang) for h in hyps], [[clean(r, lang) for r in refs]]).score


def percentile(values: list, q: float):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def compute(conn=None) -> list:
    conn = conn or run.connect()
    s = run.run_settings()
    laptop_gb = float(machine().get("laptop_ram_gb") or 16)
    memory = {r["model"]: r["peak_mb"] for r in conn.execute("SELECT model, peak_mb FROM memory")}
    rows = []
    for c in configs.build():
        d = c.direction
        row = {"config": c.id, "direction": d.id, "note": d.note, "asr": c.asr["id"] if c.asr else "",
               "translator": c.translator["id"] if c.translator else "", "prompt": c.prompt,
               "baseline": bool((not c.asr or c.asr.get("baseline")) and (not c.translator or c.translator.get("baseline"))),
               "comparison": d.comparison, "provisional": d.provisional, "split": s["split"]}
        asr_by_clip = {}
        if c.asr:
            asr_by_clip = {r["clip"]: r for r in conn.execute(
                "SELECT clip, text, seconds FROM asr_out WHERE asr_key = ? AND testset = ?", (c.asr_key, d.testset))}
        if d.kind == "asr":
            clips = run.speech_clips(conn, d.testset, s["split"], s["max_proxy_clips"] if d.provisional else None)
            got = [(t, asr_by_clip[clip]) for clip, _, t, _ in clips if clip in asr_by_clip]
            row.update(items=len(got), expected=len(clips))
            if got:
                row["cer"] = cer([t for t, _ in got], [a["text"] for _, a in got], d.source)
                row["empty"] = sum(not a["text"] for _, a in got) / len(got)
                lat = [a["seconds"] for _, a in got]
                row["latency_median"], row["latency_p90"] = percentile(lat, 0.5), percentile(lat, 0.9)
            row["memory_mb"] = memory.get(f"asr:{c.asr['id']}")
            rows.append(row)
            continue

        outputs = {r["item"]: r for r in conn.execute(
            "SELECT item, source, output, refusal, seconds FROM mt_out WHERE mt_key = ?", (c.mt_key,))}
        refs = {r["key"]: r["text"] for r in conn.execute("SELECT key, text FROM flores WHERE lang = ?", (d.reference,))}
        pairs, asr_refs, asr_hyps, latency = [], [], [], []
        if d.kind == "speech":
            clips = run.speech_clips(conn, d.testset, s["split"])
            for clip, _, transcript, key in clips:
                item = f"{c.asr_key}:{d.testset}:{clip}"
                if item in outputs and key in refs:
                    o, a = outputs[item], asr_by_clip.get(clip)
                    pairs.append((refs[key], o))
                    asr_refs.append(transcript)
                    asr_hyps.append(a["text"] if a else "")
                    latency.append((a["seconds"] or 0) + (o["seconds"] or 0) if a else None)
            expected = len(clips)
        else:
            items = run.text_items(conn, d.source, s["split"], s["max_text_sentences"])
            for key, _ in items:
                if key in outputs and key in refs:
                    pairs.append((refs[key], outputs[key]))
                    latency.append(outputs[key]["seconds"])
            expected = len(items)
        row.update(items=len(pairs), expected=expected)
        if pairs:
            row["chrf"] = chrf([r for r, _ in pairs], [o["output"] for _, o in pairs], d.target)
            row["refused"] = sum(bool(o["refusal"]) for _, o in pairs) / len(pairs)
            row["latency_median"], row["latency_p90"] = percentile(latency, 0.5), percentile(latency, 0.9)
        if asr_refs:
            row["cer"] = cer(asr_refs, asr_hyps, d.source)
        mem_asr = memory.get(f"asr:{c.asr['id']}") if c.asr else 0
        mem_mt = memory.get(f"mt:{c.translator['id']}")
        row["memory_mb"] = (mem_asr or 0) + (mem_mt or 0) if mem_mt else None
        if row["memory_mb"]:
            row["fits_laptop"] = row["memory_mb"] / 1000 + VOICE_AND_SYSTEM_GB <= laptop_gb
        rows.append(row)
    return rows


def fmt(value, spec="", none="—"):
    return none if value is None else format(value, spec)


def table(rows: list) -> str:
    lines = [f"{'direction':17} {'ASR':20} {'translator':17} {'items':>9} {'CER':>6} {'chrF':>6} "
             f"{'refused':>8} {'median s':>9} {'p90 s':>7} {'memory':>8} fits"]
    for r in rows:
        tags = (" (comparison)" if r["comparison"] else "") + (" PROVISIONAL" if r["provisional"] else "")
        lines.append(
            f"{r['direction']:17} {r['asr'] or '(text)':20} {r['translator'] or '-':17} "
            f"{r['items']:>4}/{r['expected']:<4} {fmt(r.get('cer'), '6.1f'):>6} {fmt(r.get('chrf'), '6.1f'):>6} "
            f"{fmt(r.get('refused'), '8.1%'):>8} {fmt(r.get('latency_median'), '9.2f'):>9} "
            f"{fmt(r.get('latency_p90'), '7.2f'):>7} "
            f"{fmt(r.get('memory_mb') and r['memory_mb'] / 1000, '6.1f') + ' GB' if r.get('memory_mb') else '—':>8} "
            f"{'' if 'fits_laptop' not in r else ('yes' if r['fits_laptop'] else 'NO')}{tags}")
    lines.append("\nPoint estimates on the " + (rows[0]["split"] if rows else "?") +
                 " split. Latency is up to the finished translation (no text-to-speech). "
                 "Intervals and comparisons come in B5.")
    return "\n".join(lines)
