"""Per-configuration numbers, worked out from the stored outputs.

For each configuration on a split:
- how many items were run;
- ASR: CER (character error rate) against the clip's transcript, after both
  are cleaned the same way, with its 95% interval; the empty and repetition
  rates;
- translation: chrF against the FLORES+ reference, after both are cleaned the
  same way, with its 95% interval; the refusal rate and the automatic
  failure rate (bench.failures); into Iraqi Arabic, the share of outputs that
  lean Iraqi (the dialect score);
- latency per item (recognition + translation, up to the finished
  translation), median and 90th percentile;
- peak memory of each model, and whether recognizer + translator fit the
  laptop's memory with room left for volis's voice and the system.

Then every configuration that isn't the baseline is compared with its
direction's baseline, paired, on the sentences both ran (bench.stats): the
difference in chrF, CER and failure rate with 95% intervals, and the win
rate. An interval that includes zero reads "no established difference".
"""

from bench import configs, failures, run, stats
from bench.config import machine, settings

VOICE_AND_SYSTEM_GB = 3.0   # volis's voice model, its window, and Windows itself


def cer(refs: list, hyps: list, lang: str) -> float:
    return stats.cer_metric(refs, hyps, lang).score()


def chrf(refs: list, hyps: list, lang: str) -> float:
    return stats.chrf_metric(refs, hyps, lang).score()


def percentile(values: list, q: float):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def bootstrap_settings() -> dict:
    s = settings().get("statistics") or {}
    return {"redraws": int(s.get("bootstrap_redraws", 10000)), "confidence": float(s.get("confidence", 0.95))}


def with_interval(row: dict, name: str, metric, b: dict) -> None:
    row[name], row[f"{name}_low"], row[f"{name}_high"] = stats.interval(metric, **b)


def compute(conn=None, keep_items: bool = False) -> list:
    conn = conn or run.connect()
    s = run.run_settings()
    b = bootstrap_settings()
    laptop_gb = float(machine().get("laptop_ram_gb") or 16)
    memory = {r["model"]: r["peak_mb"] for r in conn.execute("SELECT model, peak_mb FROM memory")}
    rows = []
    for c in configs.build():
        d = c.direction
        row = {"config": c.id, "direction": d.id, "note": d.note, "asr": c.asr["id"] if c.asr else "",
               "translator": c.translator["id"] if c.translator else "", "prompt": c.prompt,
               "baseline": bool((not c.asr or c.asr.get("baseline")) and (not c.translator or c.translator.get("baseline"))),
               "comparison": d.comparison, "provisional": d.provisional, "split": s["split"],
               "source_lang": d.source, "target_lang": d.target, "per_item": {},
               "asr_key": c.asr_key if c.asr else "", "mt_key": c.mt_key if c.translator else ""}
        asr_by_clip = {}
        if c.asr:
            asr_by_clip = {r["clip"]: r for r in conn.execute(
                "SELECT clip, text, seconds FROM asr_out WHERE asr_key = ? AND testset = ?", (c.asr_key, d.testset))}
        if d.kind == "asr":
            clips = run.speech_clips(conn, d.testset, s["split"], s["max_proxy_clips"] if d.provisional else None)
            audio = {clip: path for clip, path, _, _ in clips}
            got = [(clip, t, asr_by_clip[clip]) for clip, _, t, _ in clips if clip in asr_by_clip]
            row.update(items=len(got), expected=len(clips))
            row["per_item"] = {clip: {"asr_ref": t, "asr_hyp": a["text"], "audio": str(audio[clip])}
                               for clip, t, a in got}
            if got:
                with_interval(row, "cer", stats.cer_metric([t for _, t, _ in got], [a["text"] for *_, a in got],
                                                           d.source), b)
                checks = [failures.asr_checks(a["text"], d.source) for *_, a in got]
                row["empty"] = sum("empty" in f for f in checks) / len(got)
                row["repetition"] = sum("repetition" in f for f in checks) / len(got)
                lat = [a["seconds"] for *_, a in got]
                row["latency_median"], row["latency_p90"] = percentile(lat, 0.5), percentile(lat, 0.9)
            row["memory_mb"] = memory.get(f"asr:{c.asr['id']}")
            rows.append(row)
            continue

        outputs = {r["item"]: r for r in conn.execute(
            "SELECT item, source, output, refusal, seconds FROM mt_out WHERE mt_key = ?", (c.mt_key,))}
        refs = {r["key"]: r["text"] for r in conn.execute("SELECT key, text FROM flores WHERE lang = ?", (d.reference,))}
        latency = []
        if d.kind == "speech":
            clips = run.speech_clips(conn, d.testset, s["split"])
            for clip, _, transcript, key in clips:
                item = f"{c.asr_key}:{d.testset}:{clip}"
                if item in outputs and key in refs:
                    o, a = outputs[item], asr_by_clip.get(clip)
                    row["per_item"][clip] = {"ref": refs[key], "out": o, "asr_ref": transcript,
                                             "asr_hyp": a["text"] if a else ""}
                    latency.append((a["seconds"] or 0) + (o["seconds"] or 0) if a else None)
            expected = len(clips)
        else:
            items = run.text_items(conn, d.source, s["split"], s["max_text_sentences"])
            for key, _ in items:
                if key in outputs and key in refs:
                    row["per_item"][key] = {"ref": refs[key], "out": outputs[key]}
                    latency.append(outputs[key]["seconds"])
            expected = len(items)
        got = list(row["per_item"].values())
        row.update(items=len(got), expected=expected)
        if got:
            for p in got:
                p["failures"] = failures.translation_checks(p["out"]["source"], p["out"]["output"],
                                                            p["out"]["refusal"], d.target)
            with_interval(row, "chrf", stats.chrf_metric([p["ref"] for p in got], [p["out"]["output"] for p in got],
                                                         d.target), b)
            row["refused"] = sum("refused" in p["failures"] for p in got) / len(got)
            with_interval(row, "failed", stats.rate_metric([p["failures"] for p in got]), b)
            row["failure_kinds"] = {k: sum(k in p["failures"] for p in got)
                                    for k in ("refused", "empty", "wrong_script", "too_long", "numbers")}
            if d.target == "ar-IQ":
                row["dialect"] = sum(failures.leans_iraqi(p["out"]["output"]) for p in got) / len(got)
            row["latency_median"], row["latency_p90"] = percentile(latency, 0.5), percentile(latency, 0.9)
            if d.kind == "speech":
                with_interval(row, "cer", stats.cer_metric([p["asr_ref"] for p in got], [p["asr_hyp"] for p in got],
                                                           d.source), b)
        mem_asr = memory.get(f"asr:{c.asr['id']}") if c.asr else 0
        mem_mt = memory.get(f"mt:{c.translator['id']}")
        row["memory_mb"] = (mem_asr or 0) + (mem_mt or 0) if mem_mt else None
        if row["memory_mb"]:
            row["fits_laptop"] = row["memory_mb"] / 1000 + VOICE_AND_SYSTEM_GB <= laptop_gb
        rows.append(row)
    add_judge_and_ratings(conn, rows, b)
    compare_with_baselines(rows, b)
    if not keep_items:
        for r in rows:
            r.pop("per_item", None)
    return rows


def judged_labels(conn) -> dict:
    """{(mt_key, item): category} from the judge set in machine.yaml, or {}."""
    from bench import judge

    try:
        judge_id, _ = judge.judge_model()
    except RuntimeError:
        return {}
    conn.executescript(judge.SCHEMA)
    return {(r["mt_key"], r["item"]): r["category"] for r in conn.execute(
        "SELECT mt_key, item, category FROM judged WHERE judge = ?", (judge_id,))}


def add_judge_and_ratings(conn, rows: list, b: dict) -> None:
    """The critical error rate (judge), human acceptance, and how far the
    judge can be trusted, per configuration."""
    from bench import judge, review

    labels = judged_labels(conn)
    have = review.ratings(conn)
    n = int(review.setting("judge", "items_per_config", 100))
    pairs = [(have[k][0], labels[k]) for k in have if k in labels]
    agreement = review.agreement(pairs)
    for r in rows:
        r["judge_agreement"] = agreement
        if r.get("mt_key") and r["per_item"]:
            got = [(k, labels[(r["mt_key"], k)]) for k in review.judged_keys(r, n) if (r["mt_key"], k) in labels]
            got = [(k, c) for k, c in got if c != "unparsed"]
            for k, c in got:
                r["per_item"][k]["judge"] = c
            if got:
                with_interval(r, "critical", stats.rate_metric([judge.SEVERITY[c] == "critical" for _, c in got]), b)
                r["judged"] = len(got)
                r["critical_confirmed"] = agreement.confirmed
            rated = [have[(r["mt_key"], k)][0] for k in r["per_item"] if (r["mt_key"], k) in have]
        elif r.get("asr_key") and r["direction"].startswith("asr ") and r["per_item"]:
            rated = [have[(r["asr_key"], k)][0] for k in r["per_item"] if (r["asr_key"], k) in have]
        else:
            continue
        if rated:
            r["rated"] = len(rated)
            r["accepted"], r["accepted_low"], r["accepted_high"] = review.acceptance(rated, **b)
    metric_agreement(rows)


def metric_agreement(rows: list) -> None:
    """Does the chrF ranking match the human one? Per direction, once two or
    more configurations have 10+ ratings each. If not, the human ranking wins."""
    by_dir = {}
    for r in rows:
        if r.get("chrf") is not None and (r.get("rated") or 0) >= 10:
            by_dir.setdefault(r["direction"], []).append(r)
    for d, rs in by_dir.items():
        if len(rs) < 2:
            continue
        by_chrf = [r["config"] for r in sorted(rs, key=lambda r: -r["chrf"])]
        by_human = [r["config"] for r in sorted(rs, key=lambda r: -r["accepted"])]
        words = ("chrF and your ratings rank these the same way" if by_chrf == by_human else
                 "chrF and your ratings DISAGREE on the order; go by your ratings")
        for r in rs:
            r["metric_agreement"] = words


def compare(a: dict, base: dict, b: dict) -> dict:
    """a versus its direction's baseline, paired on the items both ran."""
    shared = [k for k in a["per_item"] if k in base["per_item"]]
    out = {"shared_items": len(shared)}
    if len(shared) < 2:
        return out
    pa, pb = [a["per_item"][k] for k in shared], [base["per_item"][k] for k in shared]
    if "ref" in pa[0]:
        lang = a["target_lang"]
        ma = stats.chrf_metric([p["ref"] for p in pa], [p["out"]["output"] for p in pa], lang)
        mb = stats.chrf_metric([p["ref"] for p in pb], [p["out"]["output"] for p in pb], lang)
        out["chrf_vs_base"] = stats.paired(ma, mb, **b)
        out["win_rate"] = stats.win_rate(ma, mb)
        out["failed_vs_base"] = stats.paired(stats.rate_metric([p["failures"] for p in pa]),
                                             stats.rate_metric([p["failures"] for p in pb]), **b)
        both = [(x["judge"], y["judge"]) for x, y in zip(pa, pb) if x.get("judge") and y.get("judge")]
        if len(both) >= 2:
            from bench import judge

            crit = lambda c: judge.SEVERITY[c] == "critical"  # noqa: E731
            out["critical_vs_base"] = stats.paired(stats.rate_metric([crit(x) for x, _ in both]),
                                                   stats.rate_metric([crit(y) for _, y in both]), **b)
    if "asr_hyp" in pa[0] and a["asr"] != base["asr"]:
        lang = a["source_lang"]
        ca = stats.cer_metric([p["asr_ref"] for p in pa], [p["asr_hyp"] for p in pa], lang)
        cb = stats.cer_metric([p["asr_ref"] for p in pb], [p["asr_hyp"] for p in pb], lang)
        out["cer_vs_base"] = stats.paired(ca, cb, **b)
        out.setdefault("win_rate", stats.win_rate(ca, cb))
    return out


def compare_with_baselines(rows: list, b: dict) -> None:
    base = {r["direction"]: r for r in rows if r["baseline"]}
    for r in rows:
        if not r["baseline"] and r["direction"] in base and r["per_item"]:
            r.update(compare(r, base[r["direction"]], b))


def fmt(value, spec="", none="—"):
    return none if value is None else format(value, spec)


def with_range(r: dict, name: str, spec: str = ".1f") -> str:
    if r.get(name) is None:
        return "—"
    return f"{r[name]:{spec}} [{r[f'{name}_low']:{spec}}–{r[f'{name}_high']:{spec}}]"


def critical_words(r: dict) -> str:
    if r.get("critical") is None:
        return "—"
    return f"{r['critical']:.0%}" + ("" if r.get("critical_confirmed") else "?")


def table(rows: list) -> str:
    lines = [f"{'direction':16} {'ASR':20} {'translator':17} {'items':>9} {'CER [95%]':>18} {'chrF [95%]':>18} "
             f"{'refused':>7} {'failed':>7} {'critical':>9} {'accepted':>9} {'Iraqi':>6} {'median s':>8} {'p90 s':>6} {'memory':>7} fits"]
    for r in rows:
        tags = (" (comparison)" if r["comparison"] else "") + (" PROVISIONAL" if r["provisional"] else "")
        mem = f"{r['memory_mb'] / 1000:.1f} GB" if r.get("memory_mb") else "—"
        lines.append(
            f"{r['direction']:16} {r['asr'] or '(text)':20} {r['translator'] or '-':17} "
            f"{r['items']:>4}/{r['expected']:<4} {with_range(r, 'cer'):>18} {with_range(r, 'chrf'):>18} "
            f"{fmt(r.get('refused'), '.1%'):>7} {fmt(r.get('failed'), '.1%'):>7} {critical_words(r):>9} "
            f"{fmt(r.get('accepted'), '.0%'):>9} {fmt(r.get('dialect'), '.0%'):>6} "
            f"{fmt(r.get('latency_median'), '.2f'):>8} {fmt(r.get('latency_p90'), '.2f'):>6} {mem:>7} "
            f"{'' if 'fits_laptop' not in r else ('yes' if r['fits_laptop'] else 'NO')}{tags}")
    split = rows[0]["split"] if rows else "?"
    lines.append(f"\nOn the {split} split, with 95% intervals. Latency is up to the finished translation "
                 "(no text-to-speech). 'failed' counts any automatic check (refused, empty, wrong script, "
                 "far too long, numbers lost); 'critical' is the judge's critical error rate on its sample "
                 "(? = not yet confirmed against your ratings); 'accepted' is the share you rated acceptable; "
                 "'Iraqi' is the share of outputs that lean Iraqi.")
    if rows:
        lines.append("Judge: " + rows[0]["judge_agreement"].words())
    for d in sorted({(r["direction"], r["metric_agreement"]) for r in rows if r.get("metric_agreement")}):
        lines.append(f"  {d[0]}: {d[1]}")
    compared = [r for r in rows if r.get("shared_items") is not None]
    lines.append("\nCompared with the baseline (paired, same sentences):")
    if not compared:
        lines.append("  Nothing to compare yet: only the baselines have run.")
    for r in compared:
        lines.append(f"  {r['direction']}: {r['asr'] or '(text)'} + {r['translator']} ({r['shared_items']} shared)")
        for key, label, spec in (("chrf_vs_base", "chrF", "+.1f"), ("cer_vs_base", "CER", "+.1f"),
                                 ("failed_vs_base", "failure rate", "+.1%"),
                                 ("critical_vs_base", "critical error rate", "+.1%")):
            if r.get(key):
                lines.append(f"    {label}: {r[key].words(spec)}")
        if r.get("win_rate") is not None:
            lines.append(f"    wins {r['win_rate']:.0%} of the sentences that differ")
    return "\n".join(lines)
