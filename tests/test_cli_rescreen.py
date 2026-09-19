import json

import yaml

from embargo.cli import main


def _write_messages(path, messages):
    path.write_text(yaml.safe_dump(messages))


def _write_fixtures(path, fixtures):
    path.write_text(json.dumps(fixtures))


def test_ledger_add_auto_rescreens_affected_messages(tmp_path, capsys):
    """Acceptance criterion 1 (spec §13.6): a fact entered after the fact
    re-screens affected messages and produces superseding traces with
    changed verdicts where appropriate."""
    db = str(tmp_path / "embargo.db")
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"

    _write_messages(messages_path, [
        {"message_id": "M100", "sender": "alice", "recipients": ["bob"],
         "timestamp": "2026-06-01T00:00:00", "body": "Heads up on the Zylo situation."},
    ])
    _write_fixtures(fixtures_path, {
        "M100": [{"fact_id": "F_ZYLO", "mode": "conveys", "confidence": 0.9, "span": "Zylo situation"}],
    })

    # Screen before F_ZYLO exists in the ledger at all -- clean by omission.
    main(["screen", "--message", "M100", "--db", db, "--messages", str(messages_path),
          "--fixtures", str(fixtures_path), "--trace-file", str(trace_path)])
    first_verdict = capsys.readouterr().out.strip()
    assert first_verdict == "clean"

    # Now the fact is entered, backdated (valid_from before the message).
    main(["ledger", "add", "--id", "F_ZYLO", "--summary", "Zylo situation",
          "--entities", "Zylo", "--recorded-at", "2026-07-01T00:00:00",
          "--valid-from", "2026-01-01T00:00:00", "--materiality", "high",
          "--db", db, "--trace-file", str(trace_path), "--fixtures", str(fixtures_path)])
    add_output = capsys.readouterr().out

    assert "re-screened" in add_output
    assert "M100" in add_output
    assert "clean -> violation_upstream_leak" in add_output

    from embargo.trace import read_traces
    records = read_traces(trace_path, message_id="M100")
    assert len(records) == 2
    assert records[1]["supersedes"] == records[0]["trace_id"]
    assert records[1]["verdict"] == "violation_upstream_leak"


def test_rescreen_since_reports_changed_verdicts(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"

    _write_messages(messages_path, [
        {"message_id": "M100", "sender": "alice", "recipients": ["bob"],
         "timestamp": "2026-06-01T00:00:00", "body": "Heads up on the Zylo situation."},
    ])
    _write_fixtures(fixtures_path, {
        "M100": [{"fact_id": "F_ZYLO", "mode": "conveys", "confidence": 0.9, "span": "Zylo situation"}],
    })

    main(["screen", "--message", "M100", "--db", db, "--messages", str(messages_path),
          "--fixtures", str(fixtures_path), "--trace-file", str(trace_path)])
    capsys.readouterr()
    version_at_screen = 0

    # Add the fact WITHOUT auto-rescreen side effects being asserted here --
    # use a --trace-file that doesn't exist yet so ledger add's own auto
    # rescreen has nothing to do, then rescreen manually via --since.
    main(["ledger", "add", "--id", "F_ZYLO", "--summary", "Zylo situation",
          "--entities", "Zylo", "--recorded-at", "2026-07-01T00:00:00",
          "--valid-from", "2026-01-01T00:00:00", "--materiality", "high",
          "--db", db, "--trace-file", str(tmp_path / "unrelated.jsonl"),
          "--fixtures", str(fixtures_path)])
    capsys.readouterr()

    main(["rescreen", "--since", str(version_at_screen + 1), "--db", db,
          "--trace-file", str(trace_path), "--fixtures", str(fixtures_path)])
    out = capsys.readouterr().out

    assert "M100" in out
    assert "clean -> violation_upstream_leak" in out
