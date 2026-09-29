"""The port of volis's translation rules behaves as translate.rs does
(cases taken from translate.rs's own tests)."""

from bench import volis_rules as v

TEMPLATE = ("<|im_start|>system\nYou are a translation engine. Translate the user's English text into "
            "Persian.\nOutput only the translation, with no quotation marks, no notes and no explanation.<|im_end|>\n"
            "<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")


def test_clean_drops_reasoning_labels_and_quotes():
    assert v.clean("<think>\nhmm\n</think>\nHola.") == "Hola."
    assert v.clean("<think>\nstill thinking") == ""
    assert v.clean("Translation: Good morning.") == "Good morning."
    assert v.clean("He said one thing: we are leaving.") == "He said one thing: we are leaving."
    assert v.clean('"Good morning."') == "Good morning."
    assert v.clean('He said "hello" to me.') == 'He said "hello" to me.'
    assert v.clean("Hola.<|im_end|>") == "Hola."


def test_echo_guard_exempts_names_numbers_and_single_words():
    assert v.is_echo("no preguntes qué puede hacer tu país", "No preguntes qué puede hacer tu país.")
    assert not v.is_echo("Buenos Aires", "Buenos Aires")
    assert not v.is_echo("Taxi.", "Taxi")
    assert v.is_echo("Buenos días.", "Buenos días.")   # a phrase, not a name


def test_length_and_recital_guards():
    assert v.is_implausibly_long("Hi.", "x" * 81)
    assert not v.is_implausibly_long("Hi.", "x" * 80)
    system = v.system_prompt_of(TEMPLATE)
    assert v.leaks_the_prompt("Output only the translation, with no quotation marks", system)
    assert not v.leaks_the_prompt("no quotation marks", system)   # under four words


def test_judge_orders_the_checks_as_volis_does():
    assert v.judge("Where is the station?", "ایستگاه کجاست؟", TEMPLATE) == ("ایستگاه کجاست؟", None)
    assert v.judge("where is the train station", "Where is the train station?", TEMPLATE)[1] == "echoed the source"
    assert v.judge("   ", "x", TEMPLATE) == ("", None)


def test_arabic_diacritics_count_as_letters_like_rust():
    # Rust treats harakat as alphabetic, so they survive normalise.
    assert v.normalise("مُحَمَّد") == "مُحَمَّد"
