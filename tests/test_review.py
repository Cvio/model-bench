"""The judge's parsing, the review packets' logic, and judge-to-human agreement."""

import sqlite3

from bench import judge, review
from bench.results_view import failure_rows


def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def test_judge_answers_parse_to_a_known_category():
    assert judge.parse("formal") == "formal"
    assert judge.parse("  Invented.\n") == "invented"
    assert judge.parse("The answer is wrong_person") == "wrong_person"
    assert judge.parse("I think it's fine") == "unparsed"
    assert "<think>\n\n</think>" in judge.prompt("Hi", "سلام", "سلام", "en", "fa")
    assert "Iraqi dialect" in judge.prompt("Hi", "هلو", "مرحبا", "en", "ar-IQ")


def test_the_sample_is_the_same_whatever_the_order():
    keys = [f"dev:{i}" for i in range(50)]
    assert review.sample(keys, 10) == review.sample(list(reversed(keys)), 10)
    assert review.sample(keys, 10) == review.sample(keys, 30)[:10]


def test_kappa_and_agreement():
    assert review.kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0
    assert round(review.kappa([1, 0, 1, 0], [1, 1, 0, 0]), 2) == 0.0
    a = review.agreement([("critical", "invented"), ("acceptable", "ok"), ("minor", "stiff"),
                          ("acceptable", "ok"), ("critical", "ok")])
    assert a.items == 5 and a.critical_agreement == 0.8 and a.confirmed
    b = review.agreement([("critical", "ok"), ("acceptable", "invented"), ("acceptable", "ok")])
    assert not b.confirmed and "UNCONFIRMED" in b.words()
    assert review.agreement([("critical", "unparsed")]).items == 0


def test_ratings_are_stored_and_checked(tmp_path):
    conn = memory_db()
    review.save_rating(conn, "k", "dev:1", "critical", "invented")
    review.save_rating(conn, "k", "dev:2", "acceptable", "invented")     # a category only counts for critical
    assert review.ratings(conn) == {("k", "dev:1"): ("critical", "invented"), ("k", "dev:2"): ("acceptable", "")}
    try:
        review.save_rating(conn, "k", "dev:3", "great")
        raise AssertionError("an unknown rating was accepted")
    except ValueError:
        pass
    p = review.Packet("x", "en>fa", "c", "translation",
                      [review.Item("k", "dev:1", "Hi", "سلام", "سلام", rating="critical", category="invented"),
                       review.Item("k", "dev:9", "Bye", "خداحافظ", "خداحافظ")])
    path = tmp_path / "packet.csv"
    review.write_csv(p, path)
    text = path.read_text(encoding="utf-8-sig").replace("dev:9,Bye,خداحافظ,خداحافظ,,", "dev:9,Bye,خداحافظ,خداحافظ,minor,")
    path.write_text(text, encoding="utf-8-sig")
    assert review.read_csv(conn, path) == 2
    assert review.ratings(conn)[("k", "dev:9")] == ("minor", "")


def test_next_unrated_wraps_and_right_to_left():
    items = [review.Item("k", str(i), "", "", "", rating="acceptable" if i in (0, 1, 3) else "") for i in range(4)]
    p = review.Packet("x", "d", "c", "translation", items)
    assert review.next_unrated(p) == 2
    assert review.next_unrated(p, 2) == 2
    assert review.right_to_left("این یک جمله است 2024") and not review.right_to_left("A sentence with سلام")


def test_acceptance_interval():
    share, low, high = review.acceptance(["acceptable"] * 24 + ["minor"] * 6, redraws=2000)
    assert share == 0.8 and low < 0.8 < high


def test_failure_rows_filter_by_check_and_judge():
    rows = [{"config": "c", "mt_key": "m", "per_item": {
        "a": {"failures": ["numbers"], "judge": "ok", "out": {"source": "s", "output": "o"}, "ref": "r"},
        "b": {"failures": [], "judge": "invented", "out": {"source": "s", "output": "o"}, "ref": "r"},
        "c": {"failures": [], "judge": "ok", "out": {"source": "s", "output": "o"}, "ref": "r"}}}]
    assert [r["item"] for r in failure_rows(rows, "c", "numbers")] == ["a"]
    assert [r["item"] for r in failure_rows(rows, "c", "judged critical")] == ["b"]
    assert [r["item"] for r in failure_rows(rows, "c", "any failure")] == ["a", "b"]
