"""The changelog draft, from two snapshots."""

from pathlib import Path

import yaml

from bench.rounds import draft_changelog


def write(folder: Path, candidates: dict, settings: dict, prompts: dict) -> Path:
    (folder / "prompts").mkdir(parents=True)
    (folder / "candidates.yaml").write_text(yaml.safe_dump(candidates), encoding="utf-8")
    (folder / "settings.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")
    for name, body in prompts.items():
        (folder / "prompts" / name).write_text(yaml.safe_dump(body), encoding="utf-8")
    return folder


def test_the_draft_names_what_changed_and_asks_why(tmp_path):
    base = {"id": "whisper-turbo-volis", "source": "volis:x", "why": "today"}
    before = write(tmp_path / "a", {"asr": [base], "translators": []},
                   {"splits": {"seed": 1}}, {"volis-current.yaml": {"name": "volis-current"}})
    after = write(tmp_path / "b",
                  {"asr": [base, {"id": "fa-whisper", "source": "hf:x/y@abc", "why": "Persian-tuned",
                                  "requested_by": "Dana"}],
                   "translators": [], "excluded": [{"id": "big/model", "why": "no GGUF"}]},
                  {"splits": {"seed": 2}},
                  {"volis-current.yaml": {"name": "volis-current"},
                   "tag-questions.yaml": {"name": "tag-questions", "changes": "explains ¿no?"}})
    text = draft_changelog(before, after, 2)
    assert "**fa-whisper** added (asked by Dana): Persian-tuned" in text
    assert "**big/model** left out: no GGUF" in text
    assert "setting `splits.seed`: 1 -> 2" in text
    assert "prompt **tag-questions.yaml** added: explains ¿no?" in text
    assert "Why: _(fill in)_" in text


def test_the_first_round_lists_the_baselines(tmp_path):
    after = write(tmp_path / "b", {"asr": [{"id": "w", "why": "today"}], "translators": []}, {}, {})
    assert "The first round" in draft_changelog(None, after, 1)
