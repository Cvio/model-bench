"""volis's translation clean-up and refusal guards, ported line for line from
volis's src/translate.rs so the bench judges output exactly as volis does.

The parity check (bench/parity.py) proves the port: the bench's translations,
after these rules, must equal `volis --translate` character for character.
If volis changes translate.rs, this file must change with it; the parity
check fails until it does.

Rust's char::is_alphanumeric is Unicode Alphabetic or Numeric, which includes
combining marks with the Other_Alphabetic property (Arabic harakat among
them); Python's str.isalnum doesn't. `_alnum` accounts for that.
"""

import unicodedata

MARK_ALPHABETIC = set(range(0x064B, 0x0658)) | {0x0670} | set(range(0x06D6, 0x06DD)) | set(range(0x06E1, 0x06E5)) \
    | {0x06E7, 0x06E8, 0x06ED}


def _alnum(c: str) -> bool:
    if c.isalnum():
        return True
    return unicodedata.category(c).startswith("M") and ord(c) in MARK_ALPHABETIC


def clean(raw: str) -> str:
    """translate.rs `clean`: strip reasoning, template markers, a leading label
    and wrapping quotes."""
    text = raw
    end = text.rfind("</think>")
    if end != -1:
        text = text[end + len("</think>"):]
    else:
        start = text.find("<think>")
        if start != -1:
            text = text[:start]
    text = text.replace("<|im_end|>", "")
    for marker in ("<|im_start|>assistant", "<|im_start|>user", "<|im_start|>"):
        text = text.replace(marker, "")
    text = text.strip()
    if ":" in text:
        first, rest = text.split(":", 1)
        label = first.strip().lower()
        looks_like_a_label = (len(label.encode("utf-8")) <= 40 and "\n" not in label and (
            "translat" in label or "english" in label or "spanish" in label
            or label.startswith("output") or label.startswith("result")))
        if looks_like_a_label and rest.strip():
            text = rest.strip()
    text = unwrap_quotes(text)
    return text.strip()


def unwrap_quotes(text: str) -> str:
    pairs = (('"', '"'), ("'", "'"), ("“", "”"), ("«", "»"))
    if len(text) < 2:
        return text
    first, last = text[0], text[-1]
    for open_, close in pairs:
        if first == open_ and last == close:
            inner = text[1:-1]
            if close not in inner:
                return inner
    return text


def normalise(text: str) -> str:
    kept = "".join(c for c in text if _alnum(c) or c.isspace())
    return " ".join(kept.lower().split())


def translates_to_itself(text: str) -> bool:
    words = [w for w in (_trim(w) for w in text.split()) if w]
    if len(words) <= 1:
        return True
    return all(w[0].isupper() or w[0].isnumeric() for w in words)


def _trim(word: str) -> str:
    """Rust's trim_matches(|c| !c.is_alphanumeric()): strip non-alphanumerics
    from both ends."""
    start, end = 0, len(word)
    while start < end and not _alnum(word[start]):
        start += 1
    while end > start and not _alnum(word[end - 1]):
        end -= 1
    return word[start:end]


def is_echo(source: str, output: str) -> bool:
    if normalise(source) != normalise(output):
        return False
    return not translates_to_itself(source)


def is_implausibly_long(source: str, output: str) -> bool:
    floor, factor = 80, 3
    return len(output) > max(floor, len(source) * factor)


def leaks_the_prompt(output: str, system_prompt: str) -> bool:
    if len(output.split()) < 4:
        return False
    return normalise(output) in normalise(system_prompt)


def system_prompt_of(template: str) -> str:
    """The system turn of a prompt template from `volis --print-prompt`."""
    start = template.index("<|im_start|>system\n") + len("<|im_start|>system\n")
    return template[start:template.index("<|im_end|>", start)]


def judge(source: str, raw: str, template: str):
    """(text, refusal): volis's final translation, or '' and why it refused.
    The order of checks is translate.rs's."""
    source = source.strip()
    if not source:
        return "", None
    cleaned = clean(raw)
    if leaks_the_prompt(cleaned, system_prompt_of(template)):
        return "", "recited its own instructions"
    if is_implausibly_long(source, cleaned):
        return "", "far longer than the source"
    if is_echo(source, cleaned):
        return "", "echoed the source"
    return cleaned, None
