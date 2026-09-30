"""The Results tab's rows, as plain data (no Qt), so they can be tested."""


def range_words(r: dict, name: str) -> str:
    if r.get(f"{name}_low") is None:
        return "—"
    return f"{r[f'{name}_low']:.1f}–{r[f'{name}_high']:.1f}"


def versus_words(r: dict) -> str:
    """The paired comparison with the baseline, in words."""
    if r.get("baseline"):
        return "(baseline)"
    parts = []
    for key, label, spec in (("chrf_vs_base", "chrF", "+.1f"), ("cer_vs_base", "CER", "+.1f"),
                             ("failed_vs_base", "failures", "+.1%")):
        d = r.get(key)
        if d is not None:
            parts.append(f"{label} {d.words(spec)}")
    if r.get("win_rate") is not None:
        parts.append(f"wins {r['win_rate']:.0%}")
    return "; ".join(parts) or "—"


def rows_for_table(rows: list) -> list:
    out = []
    for r in rows:
        warnings = []
        if r.get("provisional"):
            warnings.append("provisional: synthetic proxy")
        if r.get("comparison"):
            warnings.append("comparison only")
        if r.get("items", 0) < r.get("expected", 0):
            warnings.append(f"{r['expected'] - r['items']} not run yet")
        if r.get("fits_laptop") is False:
            warnings.append("doesn't fit the laptop")
        mem = r.get("memory_mb")
        out.append({
            "direction": r["direction"], "asr": r.get("asr") or "(text)", "translator": r.get("translator") or "—",
            "items": r.get("items", 0),
            "cer": round(r["cer"], 1) if r.get("cer") is not None else "—",
            "chrf": round(r["chrf"], 1) if r.get("chrf") is not None else "—",
            "refused": f"{r['refused']:.1%}" if r.get("refused") is not None else "—",
            "latency_median": round(r["latency_median"], 2) if r.get("latency_median") is not None else "—",
            "latency_p90": round(r["latency_p90"], 2) if r.get("latency_p90") is not None else "—",
            "memory_gb": round(mem / 1000, 1) if mem else "—",
            "fits": {True: "yes", False: "NO"}.get(r.get("fits_laptop"), "—"),
            "cer_range": range_words(r, "cer"), "chrf_range": range_words(r, "chrf"),
            "failed": f"{r['failed']:.1%}" if r.get("failed") is not None else "—",
            "dialect": f"{r['dialect']:.0%}" if r.get("dialect") is not None else "—",
            "vs_baseline": versus_words(r),
            "warnings": "; ".join(warnings),
            "baseline": r.get("baseline", False),
        })
    return out
