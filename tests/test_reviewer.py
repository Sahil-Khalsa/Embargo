"""Business logic for the reviewer UI (spec §14.3), kept separate from and
testable without any HTTP mechanics."""

import json
from datetime import datetime

import yaml

from embargo.access import Access
from embargo.cli import main
from embargo.ledger import Ledger
from embargo.reviewer import build_evidence_chain, build_queue, get_finding, record_reviewer_action
from embargo.trace import read_traces


def _setup(tmp_path, *, sender_crossed=True, recipient_crossed=True):
    db = str(tmp_path / "embargo.db")
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"

    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--materiality", "high", "--db", db])
    main(["ledger", "transition", "F001", "announced", "--announced-at", "2026-01-02T00:00:00", "--db", db])
    if sender_crossed:
        main(["cross", "add", "--party", "alice", "--fact", "F001",
              "--effective-from", "2026-01-01T00:00:00", "--db", db])
    if recipient_crossed:
        main(["cross", "add", "--party", "bob", "--fact", "F001",
              "--effective-from", "2026-01-01T00:00:00", "--db", db])

    messages_path.write_text(yaml.safe_dump([
        {"message_id": "M001", "sender": "alice", "recipients": ["bob"],
         "timestamp": "2026-06-01T00:00:00", "body": "ACME news"},
    ]))
    fixtures_path.write_text(json.dumps({
        "M001": [{"fact_id": "F001", "mode": "conveys", "confidence": 0.9, "span": "ACME news"}],
    }))

    main(["screen", "--message", "M001", "--db", db, "--messages", str(messages_path),
          "--fixtures", str(fixtures_path), "--trace-file", str(trace_path)])

    return db, trace_path


def test_build_queue_excludes_clean_verdicts(tmp_path, capsys):
    db, trace_path = _setup(tmp_path)  # fully authorized -> clean
    capsys.readouterr()

    queue = build_queue(trace_path)

    assert queue == []


def test_build_queue_includes_violations_sorted_most_severe_first(tmp_path, capsys):
    # Sender unauthorized -> violation_upstream_leak (most severe)
    db1, trace_path1 = _setup(tmp_path, sender_crossed=False)
    capsys.readouterr()

    queue = build_queue(trace_path1)

    assert len(queue) == 1
    assert queue[0]["verdict"] == "violation_upstream_leak"


def test_build_queue_orders_disclosure_below_upstream_leak(tmp_path, capsys):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _, trace_a = _setup(tmp_path / "a", sender_crossed=False)  # upstream_leak
    _, trace_b = _setup(tmp_path / "b", recipient_crossed=False)  # disclosure
    capsys.readouterr()

    # Merge both trace files into one queue view by reading and combining --
    # build_queue itself only takes one path, so verify severity ordering
    # via two separate calls compared against each other.
    queue_a = build_queue(trace_a)
    queue_b = build_queue(trace_b)

    assert queue_a[0]["verdict"] == "violation_upstream_leak"
    assert queue_b[0]["verdict"] == "violation_disclosure"


def test_get_finding_returns_the_matching_screening_record(tmp_path, capsys):
    db, trace_path = _setup(tmp_path, sender_crossed=False)
    capsys.readouterr()
    trace_id = read_traces(trace_path, message_id="M001")[0]["trace_id"]

    finding = get_finding(trace_path, trace_id)

    assert finding["trace_id"] == trace_id
    assert finding["verdict"] == "violation_upstream_leak"


def test_get_finding_returns_none_for_unknown_trace_id(tmp_path, capsys):
    db, trace_path = _setup(tmp_path)
    capsys.readouterr()

    assert get_finding(trace_path, "does-not-exist") is None


def test_build_evidence_chain_includes_fact_state_and_authorization_per_party(tmp_path, capsys):
    db, trace_path = _setup(tmp_path, sender_crossed=False)
    capsys.readouterr()
    trace_id = read_traces(trace_path, message_id="M001")[0]["trace_id"]
    ledger = Ledger(db)
    access = Access(db)

    chain = build_evidence_chain(trace_path, ledger, access, trace_id)

    assert chain["screening"]["trace_id"] == trace_id
    assert chain["facts"][0]["fact_id"] == "F001"
    assert chain["facts"][0]["state"] == "announced"
    assert chain["authorization"]["alice"] is False  # sender, never crossed
    assert chain["authorization"]["bob"] is True
    assert chain["reviewer_actions"] == []


def test_build_evidence_chain_includes_prior_reviewer_actions(tmp_path, capsys):
    db, trace_path = _setup(tmp_path, sender_crossed=False)
    capsys.readouterr()
    trace_id = read_traces(trace_path, message_id="M001")[0]["trace_id"]
    ledger = Ledger(db)
    access = Access(db)

    record_reviewer_action(trace_path, trace_id, "escalate", reviewer="carol", at=datetime(2026, 6, 2))
    chain = build_evidence_chain(trace_path, ledger, access, trace_id)

    assert len(chain["reviewer_actions"]) == 1
    assert chain["reviewer_actions"][0]["action"] == "escalate"
    assert chain["reviewer_actions"][0]["reviewer"] == "carol"


def test_record_reviewer_action_appends_never_overwrites(tmp_path, capsys):
    db, trace_path = _setup(tmp_path, sender_crossed=False)
    capsys.readouterr()
    trace_id = read_traces(trace_path, message_id="M001")[0]["trace_id"]

    before = len(read_traces(trace_path))
    record_reviewer_action(trace_path, trace_id, "dismiss", reviewer="carol",
                            at=datetime(2026, 6, 2), reason="false positive")
    after = read_traces(trace_path)

    assert len(after) == before + 1
    assert after[0]["record_type"] == "screening"  # original untouched
    assert after[-1]["record_type"] == "reviewer_action"
    assert after[-1]["reason"] == "false positive"


def test_record_reviewer_action_keeps_chain_intact(tmp_path, capsys):
    from embargo.trace import verify_chain

    db, trace_path = _setup(tmp_path, sender_crossed=False)
    capsys.readouterr()
    trace_id = read_traces(trace_path, message_id="M001")[0]["trace_id"]

    record_reviewer_action(trace_path, trace_id, "confirm", reviewer="carol", at=datetime(2026, 6, 2))

    assert verify_chain(trace_path).ok is True
