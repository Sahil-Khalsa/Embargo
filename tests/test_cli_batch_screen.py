"""spec §14.4: `embargo screen --batch <file>` for bulk screening with a
summary report, sharing the exact same code path as single-message
screening. Acceptance criterion 4 (spec §14.5): batch and single-message
screening produce byte-identical traces for the same input."""

import json

import yaml

from embargo.cli import main
from embargo.trace import read_traces


def _setup_ledger(tmp_path):
    db = str(tmp_path / "embargo.db")
    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--materiality", "high", "--db", db])
    main(["cross", "add", "--party", "alice", "--fact", "F001",
          "--effective-from", "2026-01-01T00:00:00", "--db", db])
    main(["cross", "add", "--party", "bob", "--fact", "F001",
          "--effective-from", "2026-01-01T00:00:00", "--db", db])
    return db


def test_batch_and_single_message_screening_produce_byte_identical_traces(tmp_path, capsys):
    db = _setup_ledger(tmp_path)
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_single = tmp_path / "single.jsonl"
    trace_batch = tmp_path / "batch.jsonl"

    messages_path.write_text(yaml.safe_dump([
        {"message_id": "M001", "sender": "alice", "recipients": ["bob"],
         "timestamp": "2026-06-01T00:00:00", "body": "ACME news"},
    ]))
    fixtures_path.write_text(json.dumps({
        "M001": [{"fact_id": "F001", "mode": "conveys", "confidence": 0.9, "span": "ACME news"}],
    }))
    capsys.readouterr()

    main(["screen", "--message", "M001", "--db", db, "--messages", str(messages_path),
          "--fixtures", str(fixtures_path), "--trace-file", str(trace_single)])
    capsys.readouterr()

    main(["screen", "--batch", str(messages_path), "--db", db,
          "--fixtures", str(fixtures_path), "--trace-file", str(trace_batch)])
    capsys.readouterr()

    single_record = read_traces(trace_single, message_id="M001")[0]
    batch_record = read_traces(trace_batch, message_id="M001")[0]

    # prev_hash differs deliberately (different files, each is the first
    # record in its own file) -- everything else, including trace_id (a
    # content hash excluding prev_hash), must match exactly.
    assert single_record["trace_id"] == batch_record["trace_id"]
    for key in single_record:
        if key == "prev_hash":
            continue
        assert single_record[key] == batch_record[key], f"mismatch on {key!r}"


def test_batch_screens_every_message_and_reports_verdict_counts(tmp_path, capsys):
    db = _setup_ledger(tmp_path)
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"

    messages_path.write_text(yaml.safe_dump([
        {"message_id": "M001", "sender": "alice", "recipients": ["bob"],
         "timestamp": "2026-06-01T00:00:00", "body": "ACME news"},
        {"message_id": "M002", "sender": "alice", "recipients": ["dave"],
         "timestamp": "2026-06-01T00:00:00", "body": "ACME update"},
    ]))
    fixtures_path.write_text(json.dumps({
        "M001": [{"fact_id": "F001", "mode": "conveys", "confidence": 0.9, "span": "ACME news"}],
        "M002": [{"fact_id": "F001", "mode": "conveys", "confidence": 0.9, "span": "ACME update"}],
    }))
    capsys.readouterr()

    main(["screen", "--batch", str(messages_path), "--db", db,
          "--fixtures", str(fixtures_path), "--trace-file", str(trace_path)])
    out = capsys.readouterr().out

    assert "screened 2 message(s)" in out
    assert "clean: 1" in out
    assert "violation_disclosure: 1" in out

    records = read_traces(trace_path)
    assert len(records) == 2


def test_screen_requires_exactly_one_of_message_or_batch(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")

    try:
        main(["screen", "--db", db])
        raised = False
    except SystemExit:
        raised = True

    assert raised
