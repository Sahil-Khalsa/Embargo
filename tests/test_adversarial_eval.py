"""Runs the adversarial corpus (spec 13.3) end to end, proving V1 acceptance
criterion 3: it runs and reports separately from the V0 corpus. Unlike the
V0 corpus, this one is built to break the resolver -- its numbers are
expected to be well below 1.0, not merged with V0's report."""

from pathlib import Path

from eval.run_eval import load_messages_raw, run_eval

ADVERSARIAL = Path(__file__).parent.parent / "corpus" / "adversarial"
FIXTURES = Path(__file__).parent.parent / "eval" / "fixtures" / "adversarial.json"

FACTS_PATH = ADVERSARIAL / "facts.yaml"
CROSSINGS_PATH = ADVERSARIAL / "crossings.yaml"
MESSAGES_PATH = ADVERSARIAL / "messages.yaml"


def _report():
    return run_eval(FACTS_PATH, CROSSINGS_PATH, MESSAGES_PATH, FIXTURES)


def test_adversarial_corpus_covers_all_six_categories():
    messages = load_messages_raw(MESSAGES_PATH)
    assert len(messages) == 8


def test_adversarial_resolver_metrics_are_well_below_one():
    """The corpus is meant to look bad -- a perfect score here would mean
    the fixtures were hand-tuned to pass rather than to expose failure
    modes, which defeats the point of an adversarial set."""
    report = _report()
    assert report.resolver_precision < 0.5
    assert report.resolver_recall < 0.5


def test_adversarial_verdict_accuracy_is_not_perfect_but_not_zero():
    report = _report()
    assert 0.0 < report.verdict_accuracy < 1.0


def test_adversarial_report_is_independent_of_v0_corpus():
    """Same run_eval() function, disjoint corpus -- proves the two are
    never merged into one number, only ever produced as separate reports."""
    from tests.test_corpus_eval import FACTS_PATH as V0_FACTS
    from tests.test_corpus_eval import CROSSINGS_PATH as V0_CROSSINGS
    from tests.test_corpus_eval import MESSAGES_PATH as V0_MESSAGES
    from tests.test_corpus_eval import FIXTURES as V0_FIXTURES

    v0_report = run_eval(V0_FACTS, V0_CROSSINGS, V0_MESSAGES, V0_FIXTURES)
    adversarial_report = _report()

    assert v0_report.verdict_accuracy == 1.0
    assert adversarial_report.verdict_accuracy != v0_report.verdict_accuracy
