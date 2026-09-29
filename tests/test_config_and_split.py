"""Validation catches the mistakes it should; the split is fixed and fair."""

import yaml

from bench import config
from bench.data import split_for


def setup_files(tmp_path, monkeypatch, candidates, prompts=None, splits=None):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "candidates.yaml").write_text(yaml.safe_dump(candidates), encoding="utf-8")
    (tmp_path / "settings.yaml").write_text(yaml.safe_dump(
        {"splits": splits or {"development": 0.4, "selection": 0.3, "vault": 0.3}}), encoding="utf-8")
    for name, body in (prompts or {"volis-current.yaml": {"name": "volis-current", "from_volis": True,
                                                          "changes": "none", "why": "baseline"}}).items():
        (tmp_path / "prompts" / name).write_text(yaml.safe_dump(body), encoding="utf-8")
    (tmp_path / "machine.yaml").write_text(yaml.safe_dump({"volis_path": str(tmp_path)}), encoding="utf-8")
    (tmp_path / "models").mkdir()
    monkeypatch.setattr(config, "ROOT", tmp_path)


GOOD = {
    "asr": [{"id": "w", "source": "volis:models", "languages": ["ar", "ar-IQ", "fa"], "baseline": True, "why": "x"},
            {"id": "p", "source": "volis:models", "languages": ["en"], "baseline": True, "why": "x"}],
    "translators": [{"id": "q", "source": "volis:models", "baseline": True, "why": "x"}],
}


def test_good_files_have_no_problems(tmp_path, monkeypatch):
    setup_files(tmp_path, monkeypatch, GOOD)
    assert config.validate() == []


def test_the_mistakes_it_catches(tmp_path, monkeypatch):
    bad = {
        "asr": GOOD["asr"] + [
            {"id": "w", "source": "hf:org/model", "languages": ["fa"], "why": "dup id, unpinned"},
            {"id": "x", "source": "volis:no/such/folder", "languages": ["de"], "why": "missing, bad lang"},
        ],
        "translators": [{"id": "q", "source": "volis:models", "why": "no baseline"}],
    }
    setup_files(tmp_path, monkeypatch, bad,
                prompts={"odd.yaml": {"name": "odd", "system": "Translate into {target_name}.",
                                      "changes": "c", "why": "w"}},
                splits={"development": 0.5, "selection": 0.3, "vault": 0.3})
    text = "\n".join(config.validate())
    assert "used twice" in text
    assert "isn't pinned to a full commit" in text
    assert "folder doesn't exist" in text
    assert "'de' isn't" in text or "['de'] isn't" in text
    assert "translators need exactly one baseline" in text
    assert "no {source_name}" in text
    assert "no volis-current" in text
    assert "add up to" in text


def test_the_split_is_fixed_and_close_to_its_proportions():
    s = {"development": 0.4, "selection": 0.3, "vault": 0.3}
    keys = [f"dev:{i}" for i in range(2000)]
    first = [split_for(k, 7, s) for k in keys]
    assert first == [split_for(k, 7, s) for k in keys]          # the same every time
    shares = {name: first.count(name) / len(keys) for name in s}
    for name, want in s.items():
        assert abs(shares[name] - want) < 0.04, shares
    assert first != [split_for(k, 8, s) for k in keys]          # the seed matters
