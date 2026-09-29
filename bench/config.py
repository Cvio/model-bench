"""Reading and checking the files the user edits: candidates.yaml, prompts/,
settings.yaml, and machine.yaml. The bench never changes them.

validate() returns a list of problems in plain words (empty = all good), so
the Round tab and `bench validate` can show every one at once rather than
stopping at the first.

What's checked here: structure, that each source exists and is pinned, the
languages, one baseline per role, and the prompt placeholders. Whether each
model actually loads in volis's engines is checked in B3, with the runners.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = {"ar", "ar-IQ", "fa", "en"}
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def machine() -> dict:
    path = ROOT / "machine.yaml"
    return load_yaml(path) if path.is_file() else {}


def settings() -> dict:
    return load_yaml(ROOT / "settings.yaml")


def candidates() -> dict:
    return load_yaml(ROOT / "candidates.yaml")


def prompts() -> list:
    return [dict(load_yaml(p), _file=p.name) for p in sorted((ROOT / "prompts").glob("*.yaml"))]


def volis_root() -> Path:
    """The folder volis's program is in (machine.yaml's volis_path)."""
    path = machine().get("volis_path")
    return Path(path) if path else None


def parse_source(source: str):
    """('volis', path) or ('hf', repo, commit), or None if malformed."""
    if not isinstance(source, str):
        return None
    if source.startswith("volis:"):
        return ("volis", source[len("volis:"):])
    if source.startswith("hf:"):
        rest = source[3:]
        repo, _, commit = rest.partition("@")
        if repo.count("/") != 1:
            return None
        return ("hf", repo, commit)
    return None


def check_source(where: str, source: str, problems: list, online: bool, pinned_required=True) -> None:
    parsed = parse_source(source)
    if parsed is None:
        problems.append(f"{where}: source {source!r} isn't volis:<path> or hf:<owner>/<name>@<commit>")
        return
    if parsed[0] == "volis":
        root = volis_root()
        if root is None:
            problems.append(f"{where}: uses volis, but machine.yaml has no volis_path "
                            "(copy machine.example.yaml to machine.yaml)")
        elif not (root / parsed[1]).exists():
            problems.append(f"{where}: {root / parsed[1]} doesn't exist")
        return
    _, repo, commit = parsed
    if pinned_required and not COMMIT.match(commit or ""):
        problems.append(f"{where}: {source!r} isn't pinned to a full commit (hf:{repo}@<40-character commit>)")
        return
    if online:
        try:
            from huggingface_hub import HfApi

            HfApi().model_info(repo, revision=commit or None)
        except Exception as e:  # noqa: BLE001 - any failure: report it
            problems.append(f"{where}: {repo} at {commit[:12] or 'main'} can't be found on Hugging Face "
                            f"({type(e).__name__})")


def validate(online: bool = False) -> list:
    problems = []
    for name in ("candidates.yaml", "settings.yaml"):
        if not (ROOT / name).is_file():
            problems.append(f"{name} is missing")
    if problems:
        return problems
    c = candidates()
    ids = set()
    for role in ("asr", "translators"):
        entries = c.get(role) or []
        if not entries:
            problems.append(f"candidates.yaml has no {role}")
        for n, e in enumerate(entries, 1):
            where = f"{role} #{n} ({e.get('id', 'no id')})"
            for key in ("id", "source", "why"):
                if not e.get(key):
                    problems.append(f"{where}: has no {key}")
            if e.get("id") in ids:
                problems.append(f"{where}: the id {e['id']!r} is used twice")
            ids.add(e.get("id"))
            if e.get("source"):
                check_source(where, e["source"], problems, online)
            if e.get("origin"):
                check_source(f"{where} origin", e["origin"], problems, online)
            if role == "asr":
                langs = e.get("languages") or []
                bad = [l for l in langs if l not in LANGUAGES]
                if not langs or bad:
                    problems.append(f"{where}: languages must be some of {sorted(LANGUAGES)}"
                                    + (f"; {bad} isn't" if bad else ""))
    asr_baselines = {}
    for e in c.get("asr") or []:
        if e.get("baseline"):
            for l in e.get("languages") or []:
                asr_baselines.setdefault(l, []).append(e.get("id"))
    for l in sorted(LANGUAGES):
        if len(asr_baselines.get(l, [])) != 1:
            problems.append(f"ASR for {l} needs exactly one baseline; it has {asr_baselines.get(l, [])}")
    t_baselines = [e.get("id") for e in c.get("translators") or [] if e.get("baseline")]
    if len(t_baselines) != 1:
        problems.append(f"translators need exactly one baseline; they have {t_baselines}")
    for n, e in enumerate(c.get("excluded") or [], 1):
        if not e.get("id") or not e.get("why"):
            problems.append(f"excluded #{n}: needs an id and a why")

    names = set()
    for p in prompts():
        where = f"prompts/{p['_file']}"
        if not p.get("name"):
            problems.append(f"{where}: has no name")
        if p.get("name") in names:
            problems.append(f"{where}: the name {p['name']!r} is used twice")
        names.add(p.get("name"))
        if not p.get("from_volis"):
            system = p.get("system") or ""
            for placeholder in ("{source_name}", "{target_name}"):
                if placeholder not in system:
                    problems.append(f"{where}: its system prompt has no {placeholder}")
        for key in ("changes", "why"):
            if not p.get(key):
                problems.append(f"{where}: has no {key} (what it changes, and why)")
    if "volis-current" not in names:
        problems.append("prompts/ has no volis-current (the baseline prompt)")

    s = settings()
    split = s.get("splits", {})
    total = sum(split.get(k, 0) for k in ("development", "selection", "vault"))
    if abs(total - 1) > 1e-9:
        problems.append(f"settings.yaml: the three splits add up to {total}, not 1")
    return problems
