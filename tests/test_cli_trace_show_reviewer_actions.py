"""Latent bug found while scoping §14.3: read_traces(message_id=...) returns
reviewer-action records too, and cmd_trace_show indexed record['verdict']
unconditionally -- so `embargo trace show` crashed with KeyError on any
message a reviewer had acted on."""

import json
from datetime import datetime

import yaml

from embargo.cli import main
from embargo.reviewer import record_reviewer_action
from embargo.trace import read_traces


def test_trace_show_does_not_crash_when_a_reviewer_action_exists(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"

    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--materiality", "high", "--db", db])
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
    trace_id = read_traces(trace_path, message_id="M001")[0]["trace_id"]
    record_reviewer_action(trace_path, trace_id, "escalate", reviewer="carol",
                           at=datetime(2026, 6, 2), reason="needs legal")
    capsys.readouterr()

    main(["trace", "show", "M001", "--trace-file", str(trace_path)])
    out = capsys.readouterr().out

    assert "screening 1 of 1" in out
    assert "reviewer action: escalate by carol" in out
    assert "needs legal" in out
