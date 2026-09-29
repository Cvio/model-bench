"""What the Round tab shows, as plain data (no Qt), so it can be tested."""

from dataclasses import dataclass, field

from bench import config, rounds


@dataclass
class RoundView:
    number: int
    asr: list = field(default_factory=list)          # rows: id, source, languages, baseline, why
    translators: list = field(default_factory=list)
    excluded: list = field(default_factory=list)     # rows: id, why
    prompts: list = field(default_factory=list)      # rows: name, changes, why
    problems: list = field(default_factory=list)
    pending: str = ""                                 # what New round would record


def build() -> RoundView:
    try:
        c = config.candidates()
    except Exception as e:  # noqa: BLE001 - an unreadable file is itself a problem to show
        return RoundView(number=rounds.current(), problems=[f"candidates.yaml can't be read: {e}"])
    view = RoundView(number=rounds.current())
    for role, rows in (("asr", view.asr), ("translators", view.translators)):
        for e in c.get(role) or []:
            rows.append({"id": e.get("id", ""), "source": e.get("source", ""),
                         "languages": ", ".join(e.get("languages") or []) if role == "asr" else "",
                         "baseline": "yes" if e.get("baseline") else "",
                         "why": e.get("why", ""), "risks": e.get("risks", "")})
    view.excluded = [{"id": e.get("id", ""), "why": e.get("why", "")} for e in c.get("excluded") or []]
    try:
        view.prompts = [{"name": p.get("name", p["_file"]), "changes": p.get("changes", ""),
                         "why": p.get("why", "")} for p in config.prompts()]
    except Exception as e:  # noqa: BLE001
        view.problems.append(f"prompts/ can't be read: {e}")
    view.problems += config.validate(online=False)
    view.pending = rounds.pending_changes()
    return view
