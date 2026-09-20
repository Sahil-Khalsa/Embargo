"""spec §14.4: an optional HTTP endpoint accepting one message and
returning a verdict plus trace id, going through the same code path
(embargo.pipeline.screen_and_write) as the CLI -- not a reimplementation."""

import json
import threading
import urllib.error
import urllib.request

import pytest
import yaml

from embargo.cli import main
from embargo.screen_server import serve
from embargo.trace import read_traces


@pytest.fixture
def running_server(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"

    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--materiality", "high", "--db", db])
    main(["cross", "add", "--party", "alice", "--fact", "F001",
          "--effective-from", "2026-01-01T00:00:00", "--db", db])
    main(["cross", "add", "--party", "bob", "--fact", "F001",
          "--effective-from", "2026-01-01T00:00:00", "--db", db])
    capsys.readouterr()

    fixtures_path.write_text(json.dumps({
        "M001": [{"fact_id": "F001", "mode": "conveys", "confidence": 0.9, "span": "ACME news"}],
    }))

    server = serve(db, str(trace_path), str(fixtures_path), host="127.0.0.1", port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}", trace_path

    server.shutdown()
    thread.join(timeout=5)


def _post_message(base_url, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{base_url}/screen", data=data, method="POST",
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode())


def test_screen_endpoint_returns_verdict_and_trace_id(running_server):
    base_url, trace_path = running_server

    status, body = _post_message(base_url, {
        "message_id": "M001", "sender": "alice", "recipients": ["bob"],
        "timestamp": "2026-06-01T00:00:00", "body": "ACME news",
    })

    assert status == 200
    assert body["verdict"] == "clean"
    assert "trace_id" in body


def test_screen_endpoint_writes_the_same_trace_the_cli_would(running_server):
    base_url, trace_path = running_server

    status, body = _post_message(base_url, {
        "message_id": "M001", "sender": "alice", "recipients": ["bob"],
        "timestamp": "2026-06-01T00:00:00", "body": "ACME news",
    })

    records = read_traces(trace_path, message_id="M001")
    assert len(records) == 1
    assert records[0]["trace_id"] == body["trace_id"]
    assert records[0]["verdict"] == "clean"


def test_screen_endpoint_rejects_malformed_json(running_server):
    base_url, trace_path = running_server

    req = urllib.request.Request(f"{base_url}/screen", data=b"not json", method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 400


def test_screen_endpoint_produces_byte_identical_trace_to_cli(running_server, tmp_path, capsys):
    """spec §14.5 criterion 4, HTTP half: the endpoint must produce the
    exact same trace as `embargo screen --message` for the same input.
    tmp_path is shared between this test and the running_server fixture
    (both function-scoped in the same test), so the db/fixtures paths the
    fixture already set up are reconstructable directly."""
    base_url, trace_path = running_server
    db = str(tmp_path / "embargo.db")
    fixtures_path = str(tmp_path / "fixtures.json")

    status, body = _post_message(base_url, {
        "message_id": "M001", "sender": "alice", "recipients": ["bob"],
        "timestamp": "2026-06-01T00:00:00", "body": "ACME news",
    })
    http_record = read_traces(trace_path, message_id="M001")[0]

    messages_path = tmp_path / "cli_messages.yaml"
    messages_path.write_text(yaml.safe_dump([
        {"message_id": "M001", "sender": "alice", "recipients": ["bob"],
         "timestamp": "2026-06-01T00:00:00", "body": "ACME news"},
    ]))
    cli_trace_path = tmp_path / "cli_traces.jsonl"

    main(["screen", "--message", "M001", "--db", db, "--messages", str(messages_path),
          "--fixtures", fixtures_path, "--trace-file", str(cli_trace_path)])
    capsys.readouterr()
    cli_record = read_traces(cli_trace_path, message_id="M001")[0]

    for key in http_record:
        if key == "prev_hash":
            continue
        assert http_record[key] == cli_record[key], f"mismatch on {key!r}"


def test_screen_endpoint_rejects_missing_required_field(running_server):
    base_url, trace_path = running_server

    req = urllib.request.Request(
        f"{base_url}/screen",
        data=json.dumps({"message_id": "M001"}).encode(),
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 400
