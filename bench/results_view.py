"""The Results tab's rows, as plain data (no Qt), so they can be tested."""


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
            "warnings": "; ".join(warnings),
            "baseline": r.get("baseline", False),
        })
    return out
