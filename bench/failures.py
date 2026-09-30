"""Automatic failure checks and the dialect score (model-bench.md, "Failures"
and "Scores per configuration"): exact and cheap, run on every output.

Translation checks, each a name in the list an output gets:
- refused: volis's own guards caught it (it echoed the source, recited the
  prompt, or said nothing usable). A refused output gets no other checks.
- empty: nothing came out.
- wrong_script: under half its letters are in the target language's script.
- too_long: far longer than the source (over 3 times, plus a little slack).
- numbers: a number in the source is missing or changed in the output.

Speech recognition checks: empty, and repetition (the same phrase over and
over, a common Whisper failure).

The dialect score: for output going into Iraqi Arabic, does it lean Iraqi
(more Iraqi-only words than formal-only ones from dialect-words.yaml)?
"""

import re
from functools import lru_cache

import yaml

from bench.config import ROOT
from bench.textclean import DIGITS, clean

LENGTH_RATIO = 3.0
LENGTH_SLACK = 20           # characters, so a short source isn't flagged for a normal translation
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def script_of(lang: str) -> str:
    return "arabic" if lang.split("-")[0] in ("ar", "fa") else "latin"


def letter_script(c: str) -> str:
    if "؀" <= c <= "ۿ" or "ݐ" <= c <= "ݿ" or "ﭐ" <= c <= "﻿":
        return "arabic"
    if c.isascii() or "À" <= c <= "ɏ":
        return "latin"
    return "other"


def in_target_script(text: str, lang: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True             # digits only: leave it to the number check
    want = script_of(lang)
    return sum(letter_script(c) == want for c in letters) / len(letters) >= 0.5


SCALES = {"thousand": 1000, "هزار": 1000, "الف": 1000, "ألف": 1000, "آلاف": 1000, "الاف": 1000,
          "million": 10**6, "میلیون": 10**6, "مليون": 10**6, "ملايين": 10**6}
SCALED = re.compile(r"(\d+(?:\.\d+)?)\s*(" + "|".join(SCALES) + r")\b", re.IGNORECASE)


def numbers_in(text: str) -> list:
    """The numbers in a text as plain digits: '2,243' and '۲٬۲۴۳' both become
    '2243', and '400 thousand' / '400 هزار' becomes '400000'."""
    text = text.translate(DIGITS).replace("٬", ",").replace("٫", ".")
    text = re.sub(r"(?<=\d)[,.](?=\d{3}\b)", "", text)
    text = SCALED.sub(lambda m: str(round(float(m.group(1)) * SCALES[m.group(2).lower()])), text)
    return NUMBER.findall(text)


def translation_checks(source: str, output: str, refusal, target: str) -> list:
    if refusal:
        return ["refused"]
    out = (output or "").strip()
    if not out:
        return ["empty"]
    found = []
    if not in_target_script(out, target):
        found.append("wrong_script")
    if len(out) > LENGTH_RATIO * len(source) + LENGTH_SLACK:
        found.append("too_long")
    have = numbers_in(out)
    for n in numbers_in(source):
        if n in have:
            have.remove(n)
        else:
            found.append("numbers")
            break
    return found


def repeats(words: list) -> bool:
    """The same phrase of 1-6 words, three or more times in a row (a single
    word four or more times)."""
    for n in range(1, 7):
        need = 4 if n == 1 else 3
        for i in range(len(words) - n * need + 1):
            phrase = words[i:i + n]
            if all(words[i + k * n:i + (k + 1) * n] == phrase for k in range(need)):
                return True
    return False


def asr_checks(text: str, lang: str) -> list:
    words = clean(text or "", lang).split()
    if not words:
        return ["empty"]
    return ["repetition"] if repeats(words) else []


@lru_cache(maxsize=1)
def dialect_words() -> dict:
    data = yaml.safe_load((ROOT / "dialect-words.yaml").read_text(encoding="utf-8")) or {}
    return {side: [clean(w, "ar") for w in data.get(side) or []] for side in ("iraqi", "formal")}


def count_words(cleaned: str, words: list) -> int:
    padded = f" {cleaned} "
    return sum(padded.count(f" {w} ") for w in words)


def leans_iraqi(text: str, words: dict = None) -> bool:
    words = words or dialect_words()
    cleaned = clean(text or "", "ar")
    return count_words(cleaned, words["iraqi"]) > count_words(cleaned, words["formal"])
