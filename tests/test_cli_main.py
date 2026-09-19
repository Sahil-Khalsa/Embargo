import json

import yaml

from embargo.cli import main


def _write_messages(path, messages):
    path.write_text(yaml.safe_dump(messages))


def _write_fixtures(path, fixtures):
    path.write_text(json.dumps(fixtures))


def test_ledger_add_list_show_round_trip(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")

    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--materiality", "high", "--db", db])
    capsys.readouterr()

    main(["ledger", "list", "--db", db])
    out = capsys.readouterr().out
    assert "F001" in out
    assert "private" in out

    main(["ledger", "show", "F001", "--db", db])
    out = capsys.readouterr().out
    assert "fact_id: F001" in out
    assert "high" in out


def test_ledger_transition_to_announced(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")
    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--db", db])
    capsys.readouterr()

    main(["ledger", "transition", "F001", "announced", "--announced-at", "2026-02-01T00:00:00", "--db", db])
    out = capsys.readouterr().out

    assert "F001 -> announced" in out


def test_cross_add_and_list(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")
    main(["cross", "add", "--party", "alice", "--fact", "F001",
          "--effective-from", "2026-01-01T00:00:00", "--db", db])
    capsys.readouterr()

    main(["cross", "list", "--db", db])
    out = capsys.readouterr().out

    assert "alice" in out
    assert "F001" in out
    assert "open-ended" in out


def test_screen_produces_verdict_and_trace_record(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"

    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--materiality", "high", "--db", db])
    main(["ledger", "transition", "F001", "announced", "--announced-at", "2026-02-01T00:00:00", "--db", db])
    main(["cross", "add", "--party", "alice", "--fact", "F001",
          "--effective-from", "2026-01-01T00:00:00", "--db", db])
    main(["cross", "add", "--party", "bob", "--fact", "F001",
          "--effective-from", "2026-01-01T00:00:00", "--db", db])
    capsys.readouterr()

    _write_messages(messages_path, [
        {"message_id": "M001", "sender": "alice", "recipients": ["bob"],
         "timestamp": "2026-06-01T00:00:00", "body": "ACME news"},
    ])
    _write_fixtures(fixtures_path, {
        "M001": [{"fact_id": "F001", "mode": "conveys", "confidence": 0.9, "span": "ACME news"}],
    })

    main(["screen", "--message", "M001", "--db", db, "--messages", str(messages_path),
          "--fixtures", str(fixtures_path), "--trace-file", str(trace_path)])
    out = capsys.readouterr().out

    assert out.strip() == "clean"
    assert trace_path.exists()
    record = json.loads(trace_path.read_text().strip())
    assert record["message_id"] == "M001"
    assert record["verdict"] == "clean"
    # 4 prior writes: fact add, transition, two crossing adds.
    assert record["ledger_version"] == 4


def test_screen_same_message_three_ways_yields_three_different_verdicts(tmp_path, capsys):
    """Acceptance criterion 1 (spec §9): same message, different --as-of/--recipients, different correct verdicts."""
    db = str(tmp_path / "embargo.db")
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"

    # Sender (alice) crossed only from 2026-03-01. Recipient bob crossed from day one.
    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--materiality", "high", "--db", db])
    main(["ledger", "transition", "F001", "announced", "--announced-at", "2026-01-02T00:00:00", "--db", db])
    main(["cross", "add", "--party", "alice", "--fact", "F001",
          "--effective-from", "2026-03-01T00:00:00", "--db", db])
    main(["cross", "add", "--party", "bob", "--fact", "F001",
          "--effective-from", "2026-01-01T00:00:00", "--db", db])
    main(["cross", "add", "--party", "carol", "--fact", "F001",
          "--effective-from", "2026-01-01T00:00:00", "--db", db])
    capsys.readouterr()

    _write_messages(messages_path, [
        {"message_id": "M001", "sender": "alice", "recipients": ["bob"],
         "timestamp": "2026-06-01T00:00:00", "body": "ACME news"},
    ])
    _write_fixtures(fixtures_path, {
        "M001": [{"fact_id": "F001", "mode": "conveys", "confidence": 0.9, "span": "ACME news"}],
    })

    # Screening 1: as-of before alice was crossed at all -> sender unauthorized -> upstream leak.
    main(["screen", "--message", "M001", "--as-of", "2026-02-01T00:00:00",
          "--db", db, "--messages", str(messages_path), "--fixtures", str(fixtures_path),
          "--trace-file", str(trace_path)])
    verdict_1 = capsys.readouterr().out.strip()

    # Screening 2: as-of after alice is crossed, recipients overridden to carol (also authorized) -> clean.
    main(["screen", "--message", "M001", "--as-of", "2026-06-01T00:00:00", "--recipients", "carol",
          "--db", db, "--messages", str(messages_path), "--fixtures", str(fixtures_path),
          "--trace-file", str(trace_path)])
    verdict_2 = capsys.readouterr().out.strip()

    # Screening 3: as-of after alice is crossed, recipients overridden to an uncrossed party -> disclosure.
    main(["screen", "--message", "M001", "--as-of", "2026-06-01T00:00:00", "--recipients", "dave",
          "--db", db, "--messages", str(messages_path), "--fixtures", str(fixtures_path),
          "--trace-file", str(trace_path)])
    verdict_3 = capsys.readouterr().out.strip()

    assert verdict_1 == "violation_upstream_leak"
    assert verdict_2 == "clean"
    assert verdict_3 == "violation_disclosure"
    assert len({verdict_1, verdict_2, verdict_3}) == 3

    records = json.loads(f"[{','.join(open(trace_path).read().strip().splitlines())}]")
    assert len(records) == 3
    assert all(r["message_id"] == "M001" for r in records)


def test_trace_show_prints_all_records_for_message(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"

    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--materiality", "none", "--db", db])
    capsys.readouterr()
    _write_messages(messages_path, [
        {"message_id": "M001", "sender": "alice", "recipients": ["bob"],
         "timestamp": "2026-06-01T00:00:00", "body": "ACME news"},
    ])
    _write_fixtures(fixtures_path, {
        "M001": [{"fact_id": "F001", "mode": "conveys", "confidence": 0.9, "span": "ACME news"}],
    })

    main(["screen", "--message", "M001", "--db", db, "--messages", str(messages_path),
          "--fixtures", str(fixtures_path), "--trace-file", str(trace_path)])
    main(["screen", "--message", "M001", "--db", db, "--messages", str(messages_path),
          "--fixtures", str(fixtures_path), "--trace-file", str(trace_path)])
    capsys.readouterr()

    main(["trace", "show", "M001", "--trace-file", str(trace_path)])
    out = capsys.readouterr().out

    assert out.count("screening 1 of 2") == 1
    assert out.count("screening 2 of 2") == 1
