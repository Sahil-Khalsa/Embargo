"""Real HTTP requests against a real stdlib http.server instance, run in a
background thread on an OS-assigned port -- the standard way to test
http.server-based code without a testing framework."""

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime

import pytest
import yaml

from embargo.cli import main
from embargo.reviewer_server import serve
from embargo.trace import read_traces


@pytest.fixture
def running_server(tmp_path, capsys):
    db = str(tmp_path / "embargo.db")
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"
    trace_path = tmp_path / "traces.jsonl"

    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal", "--entities", "ACME",
          "--recorded-at", "2026-01-01T00:00:00", "--materiality", "high", "--db", db])
    main(["ledger", "transition", "F001", "announced", "--announced-at", "2026-01-02T00:00:00", "--db", db])
    main(["cross", "add", "--party", "bob", "--fact", "F001",
          "--effective-from", "2026-01-01T00:00:00", "--db", db])
    # alice (sender) deliberately NOT crossed -> violation_upstream_leak

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

    trace_id = read_traces(trace_path, message_id="M001")[0]["trace_id"]

    server = serve(trace_path, db, host="127.0.0.1", port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}", trace_path, trace_id

    server.shutdown()
    thread.join(timeout=5)


def test_queue_page_lists_the_violation(running_server):
    base_url, trace_path, trace_id = running_server

    with urllib.request.urlopen(f"{base_url}/") as resp:
        body = resp.read().decode()

    assert resp.status == 200
    assert "violation_upstream_leak" in body
    assert trace_id[:12] in body


def test_finding_page_shows_evidence_chain(running_server):
    base_url, trace_path, trace_id = running_server

    with urllib.request.urlopen(f"{base_url}/finding/{trace_id}") as resp:
        body = resp.read().decode()

    assert resp.status == 200
    assert "F001" in body
    assert "Acme deal" in body
    assert "ACME news" in body  # the resolved span
    assert "alice" in body
    assert "NOT authorized" in body  # sender wasn't crossed
    assert "bob" in body


def _get(url):
    with urllib.request.urlopen(url) as resp:
        return resp.read().decode()


def test_finding_page_highlights_the_resolved_span_in_the_message_body(running_server):
    base_url, trace_path, trace_id = running_server

    body = _get(f"{base_url}/finding/{trace_id}")

    assert "<mark>ACME news</mark>" in body


def test_finding_page_shows_each_check_with_its_inputs_and_result(running_server):
    base_url, trace_path, trace_id = running_server

    body = _get(f"{base_url}/finding/{trace_id}")

    # resolver output that reached the gate
    assert "conveys" in body
    assert "0.9" in body  # confidence
    # the deterministic checks, in decision order, with results
    assert "is_cleared" in body
    assert "materiality" in body and "high" in body
    assert "sender_authorized" in body
    assert "recipient_authorized" in body
    assert "violation_upstream_leak" in body  # the per-fact verdict


def test_finding_page_shows_fact_timeline_and_materiality_series(running_server):
    base_url, trace_path, trace_id = running_server

    body = _get(f"{base_url}/finding/{trace_id}")

    assert "recorded_at" in body and "2026-01-01" in body
    assert "announced_at" in body and "2026-01-02" in body
    assert "materiality series" in body


def test_finding_page_shows_which_backend_and_model_produced_the_resolution(running_server):
    """spec §14.3: a reviewer should be able to see when the model was the
    weak link rather than the ledger -- so the resolver's provenance must be
    on the page, next to the checks that were computed from its output."""
    base_url, trace_path, trace_id = running_server

    body = _get(f"{base_url}/finding/{trace_id}")

    assert "backend" in body and "fake" in body
    assert "model_version" in body and "fixtures" in body


def test_finding_page_escapes_html_in_message_body_and_span(tmp_path):
    from embargo.reviewer_server import highlight_spans

    rendered = highlight_spans("<script>x</script> ACME news", ["ACME news"])

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<mark>ACME news</mark>" in rendered


def test_highlight_spans_handles_multiple_and_missing_spans():
    from embargo.reviewer_server import highlight_spans

    rendered = highlight_spans("alpha beta gamma", ["alpha", "gamma", "not present"])

    assert rendered == "<mark>alpha</mark> beta <mark>gamma</mark>"


def test_trace_viewer_lists_every_record_read_only(running_server):
    base_url, trace_path, trace_id = running_server
    data = "reviewer=carol&action=confirm&reason=".encode()
    urllib.request.urlopen(
        urllib.request.Request(f"{base_url}/finding/{trace_id}/action", data=data, method="POST")
    ).read()

    body = _get(f"{base_url}/trace")

    assert "chain intact" in body
    assert "screening" in body
    assert "reviewer_action" in body
    assert "<form" not in body  # read-only: no way to act from the viewer


def test_finding_page_unknown_trace_id_is_404(running_server):
    base_url, trace_path, trace_id = running_server

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{base_url}/finding/does-not-exist")

    assert exc_info.value.code == 404


def test_trace_viewer_shows_intact_chain(running_server):
    base_url, trace_path, trace_id = running_server

    with urllib.request.urlopen(f"{base_url}/trace") as resp:
        body = resp.read().decode()

    assert "chain intact" in body


def test_posting_a_reviewer_action_appends_to_the_chain_and_redirects(running_server):
    base_url, trace_path, trace_id = running_server

    data = urllib.parse_data = "reviewer=carol&action=confirm&reason=".encode()
    req = urllib.request.Request(f"{base_url}/finding/{trace_id}/action", data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        final_url = resp.geturl()

    assert resp.status == 200  # urlopen follows the 303 redirect
    assert f"/finding/{trace_id}" in final_url

    records = read_traces(trace_path, message_id="M001")
    reviewer_actions = [r for r in records if r.get("record_type") == "reviewer_action"]
    assert len(reviewer_actions) == 1
    assert reviewer_actions[0]["action"] == "confirm"
    assert reviewer_actions[0]["reviewer"] == "carol"


def test_posting_an_invalid_action_returns_400(running_server):
    base_url, trace_path, trace_id = running_server

    data = "reviewer=carol&action=not_a_real_action".encode()
    req = urllib.request.Request(f"{base_url}/finding/{trace_id}/action", data=data, method="POST")

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 400
