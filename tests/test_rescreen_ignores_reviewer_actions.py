"""Advisor-flagged robustness requirement before building the reviewer UI:
reviewer-action records live in the same trace file as screenings (spec
§14.3's evidence chain), but current_traces()/rescreen_stale_traces() only
know how to process screening records -- ledger_version, timestamp, verdict
are all screening-only fields. A reviewer action must never crash the next
rescreen."""

import json

import yaml

from embargo.cli import main
from embargo.trace import build_reviewer_action, read_traces, write_trace
from embargo.rescreen import current_traces


def test_current_traces_ignores_reviewer_action_records():
    from datetime import datetime

    screening = {
        "record_type": "screening", "trace_id": "s1", "message_id": "M1",
        "ledger_version": 0, "timestamp": "2026-06-01T00:00:00", "verdict": "clean",
        "supersedes": None,
    }
    action = build_reviewer_action(
        message_id="M1", trace_id_referenced="s1", action="confirm",
        reviewer="alice", at=datetime(2026, 6, 2),
    )

    result = current_traces([screening, action])

    assert result == [screening]


def test_rescreen_does_not_crash_when_a_reviewer_action_is_in_the_trace_file(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"

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

    main(["screen", "--message", "M001", "--db", db, "--messages", str(messages_path),
          "--fixtures", str(fixtures_path), "--trace-file", str(trace_path)])
    capsys.readouterr()

    screening_trace_id = read_traces(trace_path, message_id="M001")[0]["trace_id"]

    from datetime import datetime
    action_record = build_reviewer_action(
        message_id="M001", trace_id_referenced=screening_trace_id, action="confirm",
        reviewer="alice", at=datetime(2026, 6, 2),
    )
    write_trace(trace_path, action_record)

    # Must not raise -- this is the exact crash the advisor flagged.
    main(["rescreen", "--since", "999", "--db", db, "--trace-file", str(trace_path),
          "--fixtures", str(fixtures_path)])
    out = capsys.readouterr().out

    assert "no verdicts changed" in out
