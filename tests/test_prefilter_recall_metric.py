"""Prefilter recall (spec 13.5, V1 acceptance criterion 5): computed purely
from candidate_facts() output, independent of what the resolver returns --
a fact that never reaches the resolver must show up here even if no
resolver-level metric would ever catch it."""

import json

import yaml

from eval.run_eval import run_eval

FACTS = [
    {
        "fact_id": "F1", "summary": "Echo fact", "entities": ["Echo"], "aliases": [],
        "state": "announced", "recorded_at": "2026-01-01T00:00:00",
        "announced_at": "2026-01-01T00:00:00",
        "materiality": [{"effective_from": "2026-01-01T00:00:00", "level": "high"}],
    },
]

CROSSINGS: list = []  # nobody crossed -- keyword match is the only way F1 becomes a candidate

MESSAGES = [
    {
        "message_id": "M1", "sender": "alice", "recipients": ["bob"],
        "timestamp": "2026-06-01T00:00:00", "body": "Echo update inside.",
        "expected_verdict": "clean", "expected_fact_ids": ["F1"],
    },
    {
        # No mention of "Echo" at all -- F1 never becomes a prefilter
        # candidate here, a true miss invisible to any resolver-level metric.
        "message_id": "M2", "sender": "alice", "recipients": ["bob"],
        "timestamp": "2026-06-01T00:00:00", "body": "No mention of anything relevant here.",
        "expected_verdict": "clean", "expected_fact_ids": ["F1"],
    },
]

FIXTURES = {
    "M1": [{"fact_id": "F1", "mode": "conveys", "confidence": 0.9, "span": "Echo update"}],
    "M2": [],
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


def test_prefilter_recall_reflects_a_true_miss(tmp_path):
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)

    report = run_eval(facts_path, crossings_path, messages_path, fixtures_path)

    # F1 expected on both M1 and M2, but only reaches the resolver on M1.
    assert report.prefilter_recall == 0.5


def test_prefilter_recall_is_perfect_when_no_expected_facts():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        tmp_path = Path(d)
        facts_path = tmp_path / "facts.yaml"
        crossings_path = tmp_path / "crossings.yaml"
        messages_path = tmp_path / "messages.yaml"
        fixtures_path = tmp_path / "fixtures.json"

        facts_path.write_text(yaml.safe_dump([]))
        crossings_path.write_text(yaml.safe_dump([]))
        messages_path.write_text(yaml.safe_dump([
            {"message_id": "M1", "sender": "alice", "recipients": ["bob"],
             "timestamp": "2026-06-01T00:00:00", "body": "hi",
             "expected_verdict": "clean", "expected_fact_ids": []},
        ]))
        fixtures_path.write_text(json.dumps({"M1": []}))

        report = run_eval(facts_path, crossings_path, messages_path, fixtures_path)

        assert report.prefilter_recall == 1.0
