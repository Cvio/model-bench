"""B5's check: two configurations that differ only by chance give "no
established difference"; a planted real difference is detected."""

import random

from bench import failures, stats

WORDS = ("river market doctor window seven orange travel quiet morning letter garden bridge winter "
         "station careful follow answer village number simple").split()


def references(n=200, seed=1):
    rng = random.Random(seed)
    return [" ".join(rng.choice(WORDS) for _ in range(rng.randint(6, 14))) for _ in range(n)]


def noisy(refs, error_rate, seed):
    """A 'translation': each word replaced by another at random, at the given rate."""
    rng = random.Random(seed)
    return [" ".join(rng.choice(WORDS) if rng.random() < error_rate else w for w in r.split()) for r in refs]


def test_chance_only_gives_no_established_difference():
    refs = references()
    a = stats.chrf_metric(refs, noisy(refs, 0.25, seed=2), "en")
    b = stats.chrf_metric(refs, noisy(refs, 0.25, seed=3), "en")
    d = stats.paired(a, b, redraws=2000)
    assert not d.established, d
    assert d.words().startswith("no established difference")


def test_planted_difference_is_detected():
    refs = references()
    better = stats.chrf_metric(refs, noisy(refs, 0.15, seed=2), "en")
    worse = stats.chrf_metric(refs, noisy(refs, 0.35, seed=3), "en")
    d = stats.paired(better, worse, redraws=2000)
    assert d.established and d.a_better and d.low > 0
    assert stats.win_rate(better, worse) > 0.6


def test_lower_is_better_for_cer_and_failure_rates():
    refs = references(100)
    good = stats.cer_metric(refs, noisy(refs, 0.05, seed=4), "en")
    bad = stats.cer_metric(refs, noisy(refs, 0.40, seed=5), "en")
    d = stats.paired(good, bad, redraws=2000)
    assert d.established and d.difference < 0 and d.a_better
    rate = stats.rate_metric([["numbers"]] * 30 + [[]] * 70)
    score, low, high = stats.interval(rate, redraws=2000)
    assert score == 0.3 and low < 0.3 < high


def test_bootstrap_sums_match_the_corpus_score():
    refs = references(50)
    hyps = noisy(refs, 0.3, seed=6)
    import sacrebleu
    assert abs(stats.chrf_metric(refs, hyps, "en").score() - sacrebleu.CHRF().corpus_score(hyps, [refs]).score) < 1e-9


def test_translation_checks():
    assert failures.translation_checks("Hello", "", None, "fa") == ["empty"]
    assert failures.translation_checks("Hello", "Hello", "echo", "fa") == ["refused"]
    assert failures.translation_checks("Hello there", "Hello there", None, "fa") == ["wrong_script"]
    assert failures.translation_checks("Johnson has 2,243 points.", "جانسون ۲٬۲۴۳ امتیاز دارد.", None, "fa") == []
    assert failures.translation_checks("Johnson has 2,243 points.", "جانسون ۲۲۴ امتیاز دارد.", None, "fa") == ["numbers"]
    assert "too_long" in failures.translation_checks("Hi.", "سلام " * 30, None, "fa")


def test_asr_checks_and_dialect():
    assert failures.asr_checks("", "en") == ["empty"]
    assert failures.asr_checks("thank you thank you thank you", "en") == ["repetition"]
    assert failures.asr_checks("the the the", "en") == []
    words = {"iraqi": ["هسه", "شنو"], "formal": ["الان"]}
    assert failures.leans_iraqi("هسه شنو تريد؟", words)
    assert not failures.leans_iraqi("ماذا تريد الآن؟", words)


def test_false_alarms_stay_near_five_percent():
    """Across many chance-only pairs, a 95% interval should wrongly exclude
    zero about 1 time in 20."""
    refs = references(150)
    alarms = 0
    for s in range(60):
        a = stats.chrf_metric(refs, noisy(refs, 0.25, seed=100 + s), "en")
        b = stats.chrf_metric(refs, noisy(refs, 0.25, seed=200 + s), "en")
        alarms += stats.paired(a, b, redraws=1000, seed=s).established
    assert alarms <= 8, alarms


def test_numbers_understand_thousands_written_as_words():
    assert failures.numbers_in("۴۰۰ هزار مورد") == ["400000"]
    assert failures.numbers_in("400,000 cases and 2.5 million people") == ["400000", "2500000"]
    assert failures.translation_checks("حدود 400 هزار مورد", "about 400,000 cases", None, "en") == []
