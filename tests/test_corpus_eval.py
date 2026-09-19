"""Runs the real V0 corpus (corpus/*.yaml + eval/fixtures/resolutions.json)
end to end. This is what proves spec §9 acceptance criterion 2: all nine
required hard cases (§8.1) pass, plus criterion 5: it runs from fixtures
with no network access (FakeResolver only, no model call anywhere here)."""

from pathlib import Path

import yaml

from embargo.decision import decide
from embargo.prefilter import candidate_facts
from embargo.resolver import FakeResolver
from eval.run_eval import _message_from_dict, load_crossings, load_facts, load_messages_raw, run_eval

CORPUS = Path(__file__).parent.parent / "corpus"
FIXTURES = Path(__file__).parent.parent / "eval" / "fixtures" / "resolutions.json"

FACTS_PATH = CORPUS / "facts.yaml"
CROSSINGS_PATH = CORPUS / "crossings.yaml"
MESSAGES_PATH = CORPUS / "messages.yaml"


def _report():
    return run_eval(FACTS_PATH, CROSSINGS_PATH, MESSAGES_PATH, FIXTURES)


def test_corpus_has_at_least_30_messages():
    assert len(load_messages_raw(MESSAGES_PATH)) >= 30


def test_corpus_covers_all_four_verdicts():
    messages = load_messages_raw(MESSAGES_PATH)
    verdicts = {m["expected_verdict"] for m in messages}
    assert verdicts == {"clean", "review", "violation_disclosure", "violation_upstream_leak"}


def test_full_corpus_verdict_accuracy_is_perfect():
    report = _report()
    assert report.verdict_accuracy == 1.0


def test_full_corpus_resolver_metrics_are_perfect():
    report = _report()
    assert report.resolver_precision == 1.0
    assert report.resolver_recall == 1.0
    assert report.conveys_mentions_confusion == 0


# --- the nine required hard cases, spec §8.1, verified individually --------


def _verdict_for(message_id: str) -> str:
    facts = load_facts(FACTS_PATH)
    crossings = load_crossings(CROSSINGS_PATH)
    facts_by_id = {f.fact_id: f for f in facts}
    resolver = FakeResolver.from_file(FIXTURES)

    raw = next(m for m in load_messages_raw(MESSAGES_PATH) if m["message_id"] == message_id)
    message = _message_from_dict(raw)

    candidates = candidate_facts(message, facts, crossings)
    resolutions = resolver.resolve(message, [c.fact for c in candidates])
    decision = decide(message, resolutions, facts_by_id, crossings)
    return decision.verdict.value


def test_case_public_info_on_restricted_name_is_clean():
    assert _verdict_for("M001") == "clean"


def test_case_euphemism_reference_is_violation():
    assert _verdict_for("M002") == "violation_disclosure"


def test_case_chatty_mention_is_clean():
    assert _verdict_for("M003") == "clean"


def test_case_before_cleared_at_is_violation():
    assert _verdict_for("M004") == "violation_disclosure"


def test_case_after_cleared_at_is_clean():
    assert _verdict_for("M005") == "clean"


def test_case_recipient_crossed_after_message_is_violation():
    assert _verdict_for("M006") == "violation_disclosure"


def test_case_two_facts_different_states_most_severe_wins():
    assert _verdict_for("M007") == "violation_upstream_leak"


def test_case_abandoned_deal_referenced_is_violation():
    assert _verdict_for("M008") == "violation_disclosure"


def test_case_sender_not_crossed_is_upstream_leak():
    assert _verdict_for("M009") == "violation_upstream_leak"


def test_case_digestion_window_is_violation():
    assert _verdict_for("M010") == "violation_disclosure"
