"""The cleaning rules, with real Arabic and Persian text."""

from bench.textclean import clean


def test_persian_arabic_yeh_and_kaf_become_persian():
    # "کتاب" (book) and "یک" (one) typed with Arabic ك and ي.
    assert clean("كتاب يك", "fa") == "کتاب یک"
    assert clean("كتاب يك", "fa") == clean("کتاب یک", "fa")


def test_persian_half_space_is_a_space():
    # می‌روم (I go) with a zero-width non-joiner, and typed with a space.
    assert clean("می‌روم", "fa") == clean("می روم", "fa") == "می روم"


def test_persian_and_arabic_indic_digits_become_ascii():
    assert clean("۱۴۰۳ و ٢٠٢٤", "fa") == "1403 و 2024"


def test_persian_also_gets_the_arabic_rules():
    # Diacritics, tatweel and alef forms, then Persian letters.
    assert clean("إِنَّ آنـها", "fa") == "ان انها"


def test_arabic_rules():
    assert clean("مُحَمَّد", "ar") == "محمد"                 # diacritics
    assert clean("جمـــيل", "ar") == "جميل"                  # tatweel
    assert clean("أحمد إلى آخر", "ar") == "احمد الي اخر"    # alef forms, ى -> ي
    assert clean("مدرسة", "ar-IQ") == "مدرسه"                # ة -> ه; region ignored
    assert clean("شنو هذا؟ «زين»، كلش!", "ar") == "شنو هذا زين كلش"   # Arabic punctuation


def test_arabic_keeps_arabic_letters():
    # Arabic text isn't given Persian letters.
    assert clean("يك", "ar") == "يك"


def test_english():
    assert clean("  Hello, World!  It's 5 p.m. ", "en") == "hello world it s 5 p m"


def test_mixed_script_text_stays_intact():
    assert clean("Volis نسخه ۲", "fa") == "Volis نسخه 2"
