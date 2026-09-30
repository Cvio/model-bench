"""Statistics (model-bench.md, "Statistics"): how sure a number is, and
whether one configuration really beats another.

Every score here is a sum over sentences, divided at the end: chrF from its
character n-gram counts, CER from edits over characters, a rate from flags
over items. So each sentence becomes a row of counts, and a bootstrap redraw
is only a weighted sum of those rows (the weight is how many times the redraw
picked that sentence). 10,000 redraws of a few hundred sentences take a
second or two, and the result is exactly what recomputing the corpus score
on each redraw would give.

- interval(): a score with its 95% confidence interval.
- paired(): the difference between two configurations on the same sentences,
  with its interval. If the interval includes zero: "no established
  difference", never "slightly better".
- win_rate(): the share of sentences where A beats B, ties left out.
"""

from dataclasses import dataclass

import numpy as np
from sacrebleu.metrics.chrf import CHRF

from bench.textclean import clean

_CHRF = CHRF()


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def cer_counts(ref: str, hyp: str, lang: str) -> tuple:
    """(character edits, reference characters), spaces ignored, after cleaning."""
    r, h = clean(ref, lang).replace(" ", ""), clean(hyp, lang).replace(" ", "")
    return edit_distance(r, h), len(r)


@dataclass
class Metric:
    """Per-sentence counts, and how to turn summed counts into the score."""
    counts: np.ndarray          # one row per sentence
    score_of: object            # summed counts -> score
    higher_is_better: bool

    def score(self, weights=None) -> float:
        total = self.counts.sum(axis=0) if weights is None else weights @ self.counts
        return self.score_of(total)

    def per_sentence(self) -> np.ndarray:
        return np.array([self.score_of(row) for row in self.counts])


def chrf_score(total) -> float:
    return _CHRF._compute_score_from_stats(list(total)).score


def chrf_metric(refs: list, hyps: list, lang: str) -> Metric:
    counts = _CHRF._extract_corpus_statistics([clean(h, lang) for h in hyps], [[clean(r, lang) for r in refs]])
    return Metric(np.array(counts, dtype=float), chrf_score, True)


def cer_metric(refs: list, hyps: list, lang: str) -> Metric:
    counts = np.array([cer_counts(r, h, lang) for r, h in zip(refs, hyps)], dtype=float)
    return Metric(counts, lambda t: 100 * t[0] / max(t[1], 1), False)


def rate_metric(flags: list) -> Metric:
    """A share of items (failures, refusals), lower is better."""
    counts = np.array([[float(bool(f)), 1.0] for f in flags])
    return Metric(counts, lambda t: t[0] / max(t[1], 1), False)


def redraw_weights(n_items: int, redraws: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.multinomial(n_items, np.full(n_items, 1 / n_items), size=redraws).astype(float)


def interval(m: Metric, redraws: int = 10000, confidence: float = 0.95, seed: int = 0) -> tuple:
    """(score, low, high)."""
    w = redraw_weights(len(m.counts), redraws, seed)
    scores = np.array([m.score_of(t) for t in w @ m.counts])
    tail = (1 - confidence) / 2
    return m.score(), float(np.quantile(scores, tail)), float(np.quantile(scores, 1 - tail))


@dataclass
class Difference:
    difference: float           # A minus B
    low: float
    high: float
    established: bool           # the interval excludes zero
    a_better: bool              # direction of the difference, meaningful only if established

    def words(self, spec: str = "+.1f") -> str:
        if not self.established:
            return f"no established difference ({self.difference:{spec}} [{self.low:{spec}}, {self.high:{spec}}])"
        return f"{self.difference:{spec}} [{self.low:{spec}}, {self.high:{spec}}]"


def paired(a: Metric, b: Metric, redraws: int = 10000, confidence: float = 0.95, seed: int = 0) -> Difference:
    """A versus B on the same sentences, in the same order: each redraw picks
    the same sentences for both, so only the configurations differ."""
    if len(a.counts) != len(b.counts):
        raise ValueError("a paired comparison needs the same sentences on both sides")
    w = redraw_weights(len(a.counts), redraws, seed)
    diffs = np.array([a.score_of(x) - b.score_of(y) for x, y in zip(w @ a.counts, w @ b.counts)])
    tail = (1 - confidence) / 2
    low, high = float(np.quantile(diffs, tail)), float(np.quantile(diffs, 1 - tail))
    d = a.score() - b.score()
    established = low > 0 or high < 0
    return Difference(d, low, high, established, (d > 0) == a.higher_is_better)


def win_rate(a: Metric, b: Metric):
    """Share of sentences where A beats B, ties left out; None if all tie."""
    sa, sb = a.per_sentence(), b.per_sentence()
    wins = (sa > sb) if a.higher_is_better else (sa < sb)
    losses = (sa < sb) if a.higher_is_better else (sa > sb)
    decided = int(wins.sum() + losses.sum())
    return float(wins.sum()) / decided if decided else None
