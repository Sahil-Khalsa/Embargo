import json

import yaml

from embargo.cli import main

FACTS = [
    {
        "fact_id": "F1", "summary": "Acme fact", "entities": ["Acme"], "aliases": [],
        "state": "announced", "recorded_at": "2026-01-01T00:00:00",
        "announced_at": "2026-01-01T00:00:00",
        "materiality": [{"effective_from": "2026-01-01T00:00:00", "level": "high"}],
    },
]

CROSSINGS = [
    {"party_id": "alice", "fact_id": "F1", "effective_from": "2026-01-01T00:00:00"},
    {"party_id": "bob", "fact_id": "F1", "effective_from": "2026-01-01T00:00:00"},
]

MESSAGES = [
    {
        "message_id": "M1", "sender": "alice", "recipients": ["bob"],
        "timestamp": "2026-06-01T00:00:00", "body": "Acme update, high confidence",
        "expected_verdict": "clean", "expected_fact_ids": ["F1"],
    },
    {
        "message_id": "M2", "sender": "alice", "recipients": ["bob"],
        "timestamp": "2026-06-01T00:00:00", "body": "Acme update, low confidence",
        "expected_verdict": "clean", "expected_fact_ids": ["F1"],
    },
]

FIXTURES = {
    "M1": [{"fact_id": "F1", "mode": "conveys", "confidence": 0.8, "span": "Acme update, high confidence"}],
    "M2": [{"fact_id": "F1", "mode": "conveys", "confidence": 0.3, "span": "Acme update, low confidence"}],
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


def test_calibrate_command_prints_sweep_table_and_budget_pick(tmp_path, capsys):
    """Acceptance criterion 2 (spec §13.6): calibrate produces a sweep table."""
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)

    main([
        "calibrate", "--facts", str(facts_path), "--crossings", str(crossings_path),
        "--messages", str(messages_path), "--fixtures", str(fixtures_path), "--budget", "0.5",
    ])
    out = capsys.readouterr().out

    assert "threshold" in out
    assert "recall" in out
    assert "review_share" in out
    assert "best threshold for review budget" in out
    # Transparency fix: recall is monotone in threshold, so the budget pick
    # is always the floor and does not reflect a genuine trade-off -- the
    # report must say so, plus name a second reference point that isn't.
    assert "monotone" in out.lower()
    assert "accuracy" in out.lower()
    assert "best threshold for verdict accuracy" in out
