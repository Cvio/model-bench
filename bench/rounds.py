"""Rounds: rounds/<n>/ holds a snapshot of candidates.yaml, prompts/ and
settings.yaml as they were that round, and changelog.md: what changed from
the previous round and why. The bench writes a draft from the differences
between the two snapshots; the user edits it (who asked, and why, in their
words).
"""

import shutil
from pathlib import Path

import yaml

from bench.config import ROOT

ROUNDS = ROOT / "rounds"
SNAPSHOT_FILES = ("candidates.yaml", "settings.yaml")


def numbers() -> list:
    if not ROUNDS.is_dir():
        return []
    return sorted(int(p.name) for p in ROUNDS.iterdir() if p.is_dir() and p.name.isdigit())


def current() -> int:
    n = numbers()
    return n[-1] if n else None


def folder(n: int) -> Path:
    return ROUNDS / str(n)


def snapshot(into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    for name in SNAPSHOT_FILES:
        shutil.copy2(ROOT / name, into / name)
    if (into / "prompts").exists():
        shutil.rmtree(into / "prompts")
    shutil.copytree(ROOT / "prompts", into / "prompts")


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _entries(c: dict) -> dict:
    out = {}
    for role in ("asr", "translators", "excluded"):
        for e in c.get(role) or []:
            out[(role, e.get("id"))] = e
    return out


def _flatten(d: dict, prefix="") -> dict:
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, dict):
            out.update(_flatten(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def draft_changelog(before: Path, after: Path, n: int) -> str:
    """What changed between two snapshots, in plain words, as a draft."""
    lines = [f"# Round {n}", "", "*Drafted by the bench from the file differences. Edit it: say in",
             "your own words why each change was made, and who asked, if someone did.*", ""]
    if before is None:
        lines += ["The first round: volis's current models and prompt, as the baseline.", ""]
        c = _load(after / "candidates.yaml")
        for (role, cid), e in _entries(c).items():
            lines.append(f"- {role}: **{cid}**: {e.get('why', '')}")
        return "\n".join(lines) + "\n"

    old, new = _entries(_load(before / "candidates.yaml")), _entries(_load(after / "candidates.yaml"))
    changes = []
    for key in new.keys() - old.keys():
        e = new[key]
        who = f" (asked by {e['requested_by']})" if e.get("requested_by") else ""
        verb = "left out" if key[0] == "excluded" else "added"
        changes.append(f"- {key[0]}: **{key[1]}** {verb}{who}: {e.get('why', '')}")
    for key in old.keys() - new.keys():
        changes.append(f"- {key[0]}: **{key[1]}** removed. Why: _(fill in)_")
    for key in new.keys() & old.keys():
        if new[key] != old[key]:
            diff = sorted(k for k in set(new[key]) | set(old[key]) if new[key].get(k) != old[key].get(k))
            changes.append(f"- {key[0]}: **{key[1]}** changed ({', '.join(diff)}). Why: _(fill in)_")

    s_old, s_new = _flatten(_load(before / "settings.yaml")), _flatten(_load(after / "settings.yaml"))
    for k in sorted(set(s_old) | set(s_new)):
        if s_old.get(k) != s_new.get(k):
            changes.append(f"- setting `{k}`: {s_old.get(k)} -> {s_new.get(k)}. Why: _(fill in)_")

    p_old = {p.name: p.read_text(encoding="utf-8") for p in (before / "prompts").glob("*.yaml")}
    p_new = {p.name: p.read_text(encoding="utf-8") for p in (after / "prompts").glob("*.yaml")}
    for name in sorted(p_new.keys() - p_old.keys()):
        changes.append(f"- prompt **{name}** added: {_load(after / 'prompts' / name).get('changes', '')}")
    for name in sorted(p_old.keys() - p_new.keys()):
        changes.append(f"- prompt **{name}** removed. Why: _(fill in)_")
    for name in sorted(p_new.keys() & p_old.keys()):
        if p_new[name] != p_old[name]:
            changes.append(f"- prompt **{name}** edited. Why: _(fill in)_")

    lines += changes or ["Nothing changed in candidates.yaml, settings.yaml or prompts/."]
    return "\n".join(lines) + "\n"


def new_round() -> int:
    """Snapshot the files as round n+1 and draft its changelog."""
    last = current()
    n = (last or 0) + 1
    into = folder(n)
    snapshot(into / "snapshot")
    before = folder(last) / "snapshot" if last else None
    (into / "changelog.md").write_text(draft_changelog(before, into / "snapshot", n), encoding="utf-8")
    return n


def pending_changes() -> str:
    """What the next New round would record, for the Round tab."""
    last = current()
    if not last:
        return "No rounds yet: New round starts round 1."
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        snapshot(Path(tmp))
        return draft_changelog(folder(last) / "snapshot", Path(tmp), last + 1)
