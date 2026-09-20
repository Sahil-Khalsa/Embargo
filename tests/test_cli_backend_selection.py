"""spec §14.2 criterion 2, CLI half: the operational commands select their
resolver via config.backend, not via a hardcoded FakeResolver call."""

import json
from pathlib import Path

import yaml

from embargo.cli import main

REPO_ROOT = Path(__file__).parent.parent


def _write_config(path, **fields):
    lines = []
    for key, value in fields.items():
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\")
            lines.append(f'{key} = "{escaped}"')
        else:
            lines.append(f"{key} = {value}")
    path.write_text("\n".join(lines) + "\n")


def test_screen_still_works_with_default_fake_backend(tmp_path, capsys):
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
    out = capsys.readouterr().out.strip()

    assert out == "clean"

    from embargo.trace import read_traces
    record = read_traces(trace_path, message_id="M001")[0]
    assert record["backend"] == "fake"
    assert record["model_version"] == "fixtures"


def test_screen_with_hosted_backend_configured_fails_loudly_not_silently(tmp_path, capsys):
    """Selecting an unwired backend via config must surface clearly, not
    silently fall back to fake or fabricate a resolution."""
    db = str(tmp_path / "embargo.db")
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"
    config_path = tmp_path / "embargo.toml"

    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--db", db])
    capsys.readouterr()

    messages_path.write_text(yaml.safe_dump([
        {"message_id": "M001", "sender": "alice", "recipients": ["bob"],
         "timestamp": "2026-06-01T00:00:00", "body": "ACME news"},
    ]))
    fixtures_path.write_text(json.dumps({}))
    _write_config(config_path, backend="hosted")

    try:
        main(["--config", str(config_path), "screen", "--message", "M001", "--db", db,
              "--messages", str(messages_path), "--fixtures", str(fixtures_path),
              "--trace-file", str(trace_path)])
        raised = False
    except NotImplementedError:
        raised = True

    assert raised


def test_eval_backend_is_config_selected_with_no_code_change(tmp_path, capsys, monkeypatch):
    """spec §14.2 acceptance criterion 2, literally: 'two different model
    backends run the eval, selected by config with no code change.' Same
    `embargo eval` invocation, same code path -- only the config file
    differs. The fake backend actually runs the eval; the hosted backend
    is honestly not wired to a real call, so it fails loudly the moment a
    candidate reaches the resolver -- selection is proven either way."""
    monkeypatch.chdir(REPO_ROOT)  # `embargo eval`'s default corpus paths are cwd-relative
    fake_config = tmp_path / "fake.toml"
    hosted_config = tmp_path / "hosted.toml"
    _write_config(fake_config, backend="fake")
    _write_config(hosted_config, backend="hosted")

    main(["--config", str(fake_config), "eval"])
    out = capsys.readouterr().out
    assert "messages evaluated: 30" in out

    try:
        main(["--config", str(hosted_config), "eval"])
        raised = False
    except NotImplementedError:
        raised = True
    assert raised
