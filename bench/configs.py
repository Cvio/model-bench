"""Configurations: one complete, runnable setup, and its ID.

A configuration is a direction (e.g. Persian speech -> English text), a
speech recognizer (none for text-only directions), a translator, a prompt,
and the translator settings (greedy, thinking off, as volis). Its ID is a
hash of all of that, including a fingerprint of every model file (size and
modification time), the prompt's exact text, and the engine versions, so a
changed file can never reuse an old result.

The pieces have IDs of their own, so work is shared: a recognizer's
transcripts (asr_key) are reused by every translator; a translator setup's
outputs (mt_key) are reused across rounds while nothing about it changes.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from bench import config, runners

SHERPA = "sherpa-onnx 1.13.8"


@dataclass(frozen=True)
class Direction:
    id: str            # e.g. "fa>en"
    kind: str          # "speech" (ASR then translate), "text" (translate only), "asr" (ASR only)
    source: str        # language tag of the input
    target: str = ""   # language tag of the output ("" for ASR only)
    testset: str = ""  # speech test set, for speech and ASR directions
    reference: str = ""  # FLORES+ language of the reference translation
    comparison: bool = False   # measured for comparison only (formal Arabic)
    provisional: bool = False  # rests on the synthetic Iraqi proxy
    note: str = ""


DIRECTIONS = [
    Direction("fa>en", "speech", "fa", "en", "fleurs-fa", "en", note="Persian speech to English"),
    Direction("en>fa", "speech", "en", "fa", "fleurs-en", "fa", note="English speech to Persian"),
    Direction("en>ar-IQ", "speech", "en", "ar-IQ", "fleurs-en", "ar-IQ", note="English speech to Iraqi Arabic"),
    Direction("en>ar", "speech", "en", "ar", "fleurs-en", "ar", comparison=True,
              note="English speech to formal Arabic, for comparison"),
    Direction("ar>en", "speech", "ar", "en", "fleurs-ar", "en", comparison=True,
              note="Formal Arabic speech to English, for comparison"),
    Direction("ar-IQ>en text", "text", "ar-IQ", "en", reference="en",
              note="Iraqi Arabic text to English (FLORES+); translation only"),
    Direction("en>ar-IQ text", "text", "en", "ar-IQ", reference="ar-IQ",
              note="English text to Iraqi Arabic (FLORES+); translation only"),
    Direction("asr ar-IQ proxy", "asr", "ar-IQ", testset="youssef", provisional=True,
              note="Iraqi speech recognition on the synthetic proxy; provisional"),
]


def stamp(path: Path) -> str:
    st = path.stat()
    return f"{path.name}:{st.st_size}:{int(st.st_mtime)}"


def folder_stamp(folder: Path) -> str:
    return ";".join(stamp(p) for p in sorted(folder.rglob("*")) if p.is_file() and p.suffix in (".onnx", ".toml", ".txt"))


def digest(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def asr_key(entry: dict, language: str) -> str:
    folder = runners.resolve(entry["source"])
    return digest("asr", entry["id"], entry["source"], folder_stamp(folder), language.split("-")[0], SHERPA)


def mt_key(entry: dict, prompt_name: str, template: str, direction: Direction) -> str:
    gguf = runners.resolve(entry["source"])
    return digest("mt", entry["id"], entry["source"], stamp(gguf), prompt_name, template,
                  direction.source, direction.target, "greedy", runners.LLAMA_CPP_COMMIT,
                  runners.CONTEXT_TOKENS, runners.MAX_OUTPUT_TOKENS)


@dataclass
class Config:
    id: str
    direction: Direction
    asr: dict = None             # candidate entry, or None
    translator: dict = None
    prompt: str = ""
    template: str = ""
    asr_key: str = ""
    mt_key: str = ""
    parts: dict = field(default_factory=dict)


def build(prompt_name: str = "volis-current") -> list:
    """Every configuration the candidates allow, for every direction."""
    c = config.candidates()
    asr_entries = c.get("asr") or []
    translators = c.get("translators") or []
    templates = {}
    out = []
    for d in DIRECTIONS:
        asrs = [e for e in asr_entries if d.source in (e.get("languages") or [])] if d.kind != "text" else [None]
        if d.kind == "asr":
            for a in asrs:
                key = asr_key(a, d.source)
                out.append(Config(digest("config", d.id, key), d, asr=a, asr_key=key,
                                  parts={"direction": d.id, "asr": a["id"]}))
            continue
        if (d.source, d.target) not in templates:
            templates[(d.source, d.target)] = runners.volis_prompt(d.source, d.target)
        template = templates[(d.source, d.target)]
        for a in asrs:
            for t in translators:
                akey = asr_key(a, d.source) if a else ""
                mkey = mt_key(t, prompt_name, template, d)
                out.append(Config(
                    digest("config", d.id, akey, mkey), d, asr=a, translator=t, prompt=prompt_name,
                    template=template, asr_key=akey, mt_key=mkey,
                    parts={"direction": d.id, "asr": a["id"] if a else None, "translator": t["id"],
                           "prompt": prompt_name, "decoding": "greedy, thinking off (as volis)",
                           "engines": {"asr": SHERPA if a else None, "llama.cpp": runners.LLAMA_CPP_COMMIT}}))
    return out
