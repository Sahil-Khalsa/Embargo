"""Advisor-flagged check before §14.3: §14.2 put backend/model_version
inside the trace record, and trace_id is a content hash of that record.
Criterion 4 (spec §14.5) needs batch and single-message screening to
produce byte-identical traces for the same input -- which silently breaks
if two logically-identical config resolutions (no --config vs an explicit
backend = "fake") ever produced different backend/model_version values."""

import json

import yaml

from embargo.cli import main
from embargo.trace import read_traces


def _write_config(path, **fields):
    lines = []
    for key, value in fields.items():
        if isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        else:
            lines.append(f"{key} = {value}")
    path.write_text("\n".join(lines) + "\n")


def test_no_config_and_explicit_fake_backend_config_produce_identical_trace_id(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path_a = tmp_path / "traces_a.jsonl"
    trace_path_b = tmp_path / "traces_b.jsonl"
    config_path = tmp_path / "embargo.toml"

    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--materiality", "high", "--db", db])
    main(["cross", "add", "--party", "alice", "--fact", "F001",
          "--effective-from", "2026-01-01T00:00:00", "--db", db])
    main(["cross", "add", "--party", "bob", "--fact", "F001",
          "--effective-from", "2026-01-01T00:00:00", "--db", db])
    capsys.readouterr()

    messages_path.write_text(yaml.safe_dump([
        {"message_id": "M001", "sender": "alice", "recipients": ["bob"],
         "timestamp": "2026-06-01T00:00:00", "body": "ACME news"},
    ]))
    fixtures_path.write_text(json.dumps({
        "M001": [{"fact_id": "F001", "mode": "conveys", "confidence": 0.9, "span": "ACME news"}],
    }))
    _write_config(config_path, backend="fake")

    main(["screen", "--message", "M001", "--db", db, "--messages", str(messages_path),
          "--fixtures", str(fixtures_path), "--trace-file", str(trace_path_a)])
    capsys.readouterr()

    main(["--config", str(config_path), "screen", "--message", "M001", "--db", db,
          "--messages", str(messages_path), "--fixtures", str(fixtures_path),
          "--trace-file", str(trace_path_b)])
    capsys.readouterr()

    record_a = read_traces(trace_path_a, message_id="M001")[0]
    record_b = read_traces(trace_path_b, message_id="M001")[0]

    assert record_a["backend"] == record_b["backend"] == "fake"
    assert record_a["model_version"] == record_b["model_version"] == "fixtures"
    assert record_a["trace_id"] == record_b["trace_id"]
