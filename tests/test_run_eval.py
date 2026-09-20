import json

import yaml

from embargo.resolver import FakeResolver
from eval.run_eval import run_eval

FACTS = [
    {
        "fact_id": "F1", "summary": "Acme fact", "entities": ["Acme"], "aliases": [],
        "state": "announced", "recorded_at": "2026-01-01T00:00:00",
        "announced_at": "2026-01-01T00:00:00",
        "materiality": [{"effective_from": "2026-01-01T00:00:00", "level": "high"}],
    },
    {
        "fact_id": "F2", "summary": "Beta fact", "entities": ["Beta"], "aliases": [],
        "state": "announced", "recorded_at": "2026-01-01T00:00:00",
        "announced_at": "2026-01-01T00:00:00",
        "materiality": [{"effective_from": "2026-01-01T00:00:00", "level": "high"}],
    },
    {
        "fact_id": "F3", "summary": "Gamma fact", "entities": ["Gamma"], "aliases": [],
        "state": "announced", "recorded_at": "2026-01-01T00:00:00",
        "announced_at": "2026-01-01T00:00:00",
        "materiality": [{"effective_from": "2026-01-01T00:00:00", "level": "high"}],
    },
    {
        "fact_id": "F4", "summary": "Delta fact", "entities": ["Delta"], "aliases": [],
        "state": "announced", "recorded_at": "2026-01-01T00:00:00",
        "announced_at": "2026-01-01T00:00:00",
        "materiality": [{"effective_from": "2026-01-01T00:00:00", "level": "high"}],
    },
]

CROSSINGS = [
    # F1: sender authorized, recipient not -> violation_disclosure
    {"party_id": "alice", "fact_id": "F1", "effective_from": "2026-01-01T00:00:00"},
    # F3: both authorized -> clean
    {"party_id": "alice", "fact_id": "F3", "effective_from": "2026-01-01T00:00:00"},
    {"party_id": "bob", "fact_id": "F3", "effective_from": "2026-01-01T00:00:00"},
    # F2, F4: nobody crossed (irrelevant: F2 never proceeds past gate, F4 never resolved at all)
]

MESSAGES = [
    {
        "message_id": "M1", "sender": "alice", "recipients": ["bob"],
        "timestamp": "2026-06-01T00:00:00", "body": "Acme update",
        "expected_verdict": "violation_disclosure", "expected_fact_ids": ["F1"],
    },
    {
        "message_id": "M2", "sender": "alice", "recipients": ["bob"],
        "timestamp": "2026-06-01T00:00:00", "body": "Beta update",
        "expected_verdict": "violation_disclosure", "expected_fact_ids": ["F2"],
    },
    {
        "message_id": "M3", "sender": "alice", "recipients": ["bob"],
        "timestamp": "2026-06-01T00:00:00", "body": "Gamma update",
        "expected_verdict": "clean", "expected_fact_ids": [],
    },
    {
        "message_id": "M4", "sender": "alice", "recipients": ["bob"],
        "timestamp": "2026-06-01T00:00:00", "body": "Delta update",
        "expected_verdict": "violation_disclosure", "expected_fact_ids": ["F4"],
    },
]

FIXTURES = {
    "M1": [{"fact_id": "F1", "mode": "conveys", "confidence": 0.9, "span": "Acme update"}],
    "M2": [{"fact_id": "F2", "mode": "mentions", "confidence": 0.9, "span": "Beta update"}],
    "M3": [{"fact_id": "F3", "mode": "conveys", "confidence": 0.9, "span": "Gamma update"}],
    "M4": [],
}


def _write_corpus(tmp_path):
    facts_path = tmp_path / "facts.yaml"
    crossings_path = tmp_path / "crossings.yaml"
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"

    facts_path.write_text(yaml.safe_dump(FACTS))
    crossings_path.write_text(yaml.safe_dump(CROSSINGS))
    messages_path.write_text(yaml.safe_dump(MESSAGES))
    fixtures_path.write_text(json.dumps(FIXTURES))

    return facts_path, crossings_path, messages_path, fixtures_path


def test_run_eval_reports_resolver_precision_and_recall(tmp_path):
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)

    report = run_eval(facts_path, crossings_path, messages_path, fixtures_path)

    # tp=1 (F1), fp=1 (F3), fn_missed=1 (F4), fn_confusion=1 (F2)
    assert report.resolver_precision == 0.5
    assert abs(report.resolver_recall - 1 / 3) < 1e-9


def test_run_eval_accepts_an_explicit_resolver_instead_of_loading_fixtures_path(tmp_path):
    """spec §14.2 criterion 2: two different backends must be able to 'run
    the eval' -- run_eval must accept a pre-built Resolver (as build_resolver
    would produce) rather than always constructing FakeResolver internally."""
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)
    explicit_resolver = FakeResolver.from_file(fixtures_path)

    report = run_eval(facts_path, crossings_path, messages_path, fixtures_path, resolver=explicit_resolver)

    assert report.resolver_precision == 0.5


def test_run_eval_reports_conveys_mentions_confusion_count(tmp_path):
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)

    report = run_eval(facts_path, crossings_path, messages_path, fixtures_path)

    assert report.conveys_mentions_confusion == 1


def test_run_eval_reports_end_to_end_verdict_accuracy(tmp_path):
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)

    report = run_eval(facts_path, crossings_path, messages_path, fixtures_path)

    assert report.total_messages == 4
    assert report.verdict_accuracy == 0.5


def test_run_eval_confusion_matrix_has_expected_cells(tmp_path):
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)

    report = run_eval(facts_path, crossings_path, messages_path, fixtures_path)

    assert report.confusion_matrix["violation_disclosure"]["violation_disclosure"] == 1
    assert report.confusion_matrix["violation_disclosure"]["clean"] == 2
    assert report.confusion_matrix["clean"]["clean"] == 1
