"""The numbers behind the Results tab."""

from bench.results import cer, chrf, percentile
from bench.results_view import rows_for_table


def test_cer_counts_character_edits_after_cleaning():
    assert cer(["Hello, world!"], ["hello world"], "en") == 0.0
    assert round(cer(["abcd"], ["abxd"], "en"), 1) == 25.0
    # Persian: the half-space and Arabic yeh don't count as errors.
    assert cer(["می‌روم"], ["مي روم"], "fa") == 0.0


def test_chrf_is_100_for_identical_text_and_lower_otherwise():
    assert round(chrf(["The cat sat."], ["the cat sat"], "en"), 1) == 100.0
    assert chrf(["The cat sat on the mat."], ["A dog stood."], "en") < 30


def test_percentiles_ignore_missing_values():
    assert percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert percentile([1, 2, 3, 4, 5, None], 0.9) == 4.6
    assert percentile([None], 0.5) is None


def test_table_rows_carry_their_warnings():
    rows = rows_for_table([
        {"direction": "asr ar-IQ proxy", "asr": "w", "items": 280, "expected": 300, "provisional": True,
         "cer": 12.345, "memory_mb": 1500},
        {"direction": "en>fa", "asr": "p", "translator": "q", "items": 10, "expected": 10, "chrf": 40.0,
         "refused": 0.1, "memory_mb": 40000, "fits_laptop": False, "baseline": True},
    ])
    assert "provisional" in rows[0]["warnings"] and "20 not run yet" in rows[0]["warnings"]
    assert rows[0]["cer"] == 12.3 and rows[0]["memory_gb"] == 1.5
    assert rows[1]["fits"] == "NO" and "doesn't fit" in rows[1]["warnings"] and rows[1]["refused"] == "10.0%"
