import json

import yaml

from embargo.cli import main


def _write_config(path, **fields):
    lines = []
    for key, value in fields.items():
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\")
            lines.append(f'{key} = "{escaped}"')
        else:
            lines.append(f"{key} = {value}")
    path.write_text("\n".join(lines) + "\n")


def test_screen_uses_configured_threshold_when_no_explicit_flag(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"
    config_path = tmp_path / "embargo.toml"

    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--materiality", "high", "--db", db])
    main(["ledger", "transition", "F001", "announced", "--announced-at", "2026-02-01T00:00:00", "--db", db])
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
        "M001": [{"fact_id": "F001", "mode": "conveys", "confidence": 0.7, "span": "ACME news"}],
    }))

    # Configured threshold (0.9) is above the resolution's confidence (0.7),
    # so with no explicit --threshold flag this should route to review
    # rather than the default (0.6) proceeding to an automatic clean.
    _write_config(config_path, threshold=0.9)

    main(["--config", str(config_path), "screen", "--message", "M001", "--db", db,
          "--messages", str(messages_path), "--fixtures", str(fixtures_path),
          "--trace-file", str(trace_path)])
    out = capsys.readouterr().out.strip()

    assert out == "review"


def test_explicit_threshold_flag_overrides_config(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"
    config_path = tmp_path / "embargo.toml"

    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--materiality", "high", "--db", db])
    main(["ledger", "transition", "F001", "announced", "--announced-at", "2026-02-01T00:00:00", "--db", db])
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
        "M001": [{"fact_id": "F001", "mode": "conveys", "confidence": 0.7, "span": "ACME news"}],
    }))

    # Config says 0.9 (would route to review), but an explicit --threshold
    # flag of 0.5 must win, letting the 0.7-confidence resolution proceed.
    _write_config(config_path, threshold=0.9)

    main(["--config", str(config_path), "screen", "--message", "M001", "--db", db,
          "--messages", str(messages_path), "--fixtures", str(fixtures_path),
          "--trace-file", str(trace_path), "--threshold", "0.5"])
    out = capsys.readouterr().out.strip()

    assert out == "clean"


def test_ledger_list_uses_configured_db_path_when_no_explicit_flag(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "configured.db"
    config_path = tmp_path / "embargo.toml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"
    fixtures_path.write_text("{}")
    _write_config(config_path, db_path=str(db_path))

    monkeypatch.chdir(tmp_path)

    main(["--config", str(config_path), "ledger", "add", "--id", "F001", "--summary", "Acme deal",
          "--entities", "ACME", "--recorded-at", "2026-01-01T00:00:00",
          "--fixtures", str(fixtures_path), "--trace-file", str(trace_path)])
    capsys.readouterr()

    main(["--config", str(config_path), "ledger", "list"])
    out = capsys.readouterr().out

    assert "F001" in out
    assert db_path.exists()


def test_no_config_flag_falls_back_to_built_in_defaults(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")

    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--db", db])
    out = capsys.readouterr().out

    assert "added fact F001" in out
