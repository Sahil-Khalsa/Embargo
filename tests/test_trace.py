import json
from datetime import datetime

from embargo.decision import decide
from embargo.models import Fact, FactState, MaterialityLevel, Message, Resolution, ResolutionMode
from embargo.prefilter import candidate_facts
from embargo.trace import build_resolver_failure_trace, build_trace, read_traces, write_trace

FACT = Fact(
    fact_id="F047",
    summary="Acme is acquiring Beta",
    entities=["ACME"],
    aliases=[],
    state=FactState.ANNOUNCED,
    recorded_at=datetime(2026, 1, 1),
    materiality=[(datetime(2026, 1, 1), MaterialityLevel.HIGH)],
    announced_at=datetime(2026, 1, 1),
)

MESSAGE = Message(
    message_id="M001",
    sender="alice",
    recipients=["bob"],
    timestamp=datetime(2026, 6, 1),
    body="ACME news",
)


def _built_trace(**overrides):
    candidates = candidate_facts(MESSAGE, [FACT], [])
    resolutions = [
        Resolution(fact_id="F047", mode=ResolutionMode.CONVEYS, confidence=0.9, span="ACME news")
    ]
    decision = decide(MESSAGE, resolutions, {"F047": FACT}, [])
    return build_trace(MESSAGE, candidates, resolutions, decision, **overrides)


def test_build_trace_record_type_is_screening():
    record = _built_trace()

    assert record["record_type"] == "screening"


def test_build_trace_includes_message_fields_and_ledger_version_placeholder():
    record = _built_trace(ledger_version=0)

    assert record["message_id"] == "M001"
    assert record["sender"] == "alice"
    assert record["recipients"] == ["bob"]
    assert record["timestamp"] == "2026-06-01T00:00:00"
    assert record["ledger_version"] == 0
    assert record["reason"] is None


def test_build_trace_defaults_backend_and_model_version_to_unknown():
    record = _built_trace()

    assert record["backend"] == "unknown"
    assert record["model_version"] == "unknown"


def test_build_trace_records_given_backend_and_model_version():
    record = _built_trace(backend="fake", model_version="fixtures")

    assert record["backend"] == "fake"
    assert record["model_version"] == "fixtures"


def test_build_trace_includes_candidates_with_reasons():
    record = _built_trace()

    assert record["candidates"] == [{"fact_id": "F047", "reasons": ["entity_match", "semantic_match"]}]


def test_build_trace_includes_resolution_span_and_check_details():
    record = _built_trace()

    fact_result = record["fact_results"][0]
    assert fact_result["fact_id"] == "F047"
    assert fact_result["span"] == "ACME news"
    assert fact_result["mode"] == "conveys"
    assert fact_result["verdict"] == "violation_upstream_leak"  # nobody authorized
    assert fact_result["checks"]["sender_authorized"] is False
    assert fact_result["checks"]["recipient_authorized"] == {"bob": False}


def test_build_trace_records_no_override_by_default():
    record = _built_trace()

    assert record["as_of_override"] is None
    assert record["recipients_override"] is None


def test_build_trace_records_overrides_when_given():
    record = _built_trace(
        as_of_override=datetime(2026, 7, 1), recipients_override=["carol"]
    )

    assert record["as_of_override"] == "2026-07-01T00:00:00"
    assert record["recipients_override"] == ["carol"]


def test_build_trace_assigns_a_trace_id():
    record = _built_trace()

    assert record["trace_id"]
    assert isinstance(record["trace_id"], str)


def test_build_trace_is_deterministic_for_identical_input():
    record_a = _built_trace()
    record_b = _built_trace()

    assert record_a["trace_id"] == record_b["trace_id"]


def test_build_trace_id_changes_when_content_differs():
    record_a = _built_trace()
    record_b = _built_trace(as_of_override=datetime(2026, 7, 1))

    assert record_a["trace_id"] != record_b["trace_id"]


def test_build_trace_supersedes_defaults_to_none():
    record = _built_trace()

    assert record["supersedes"] is None


def test_build_trace_records_supersedes_when_given():
    original = _built_trace()

    superseding = _built_trace(supersedes=original["trace_id"])

    assert superseding["supersedes"] == original["trace_id"]
    assert superseding["trace_id"] != original["trace_id"]


def test_build_resolver_failure_trace_is_review_with_reason():
    candidates = candidate_facts(MESSAGE, [FACT], [])
    record = build_resolver_failure_trace(MESSAGE, candidates)

    assert record["verdict"] == "review"
    assert record["reason"] == "resolver_output_invalid"
    assert record["fact_results"] == []


def test_build_resolver_failure_trace_record_type_is_screening():
    candidates = candidate_facts(MESSAGE, [FACT], [])
    record = build_resolver_failure_trace(MESSAGE, candidates)

    assert record["record_type"] == "screening"


def test_build_resolver_failure_trace_records_given_backend_and_model_version():
    candidates = candidate_facts(MESSAGE, [FACT], [])
    record = build_resolver_failure_trace(MESSAGE, candidates, backend="hosted", model_version="claude-x")

    assert record["backend"] == "hosted"
    assert record["model_version"] == "claude-x"


def test_write_trace_then_read_traces_round_trips(tmp_path):
    path = tmp_path / "traces.jsonl"
    record = _built_trace()

    write_trace(path, record)
    records = read_traces(path)

    # write_trace adds prev_hash (spec 13.4's hash chain) at write time --
    # None here since this is the first record in the file.
    expected = dict(record, prev_hash=None)
    assert records == [expected]
    # confirm it's genuinely one-JSON-object-per-line
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == expected


def test_read_traces_returns_all_records_for_repeated_screenings(tmp_path):
    path = tmp_path / "traces.jsonl"
    write_trace(path, _built_trace(as_of_override=datetime(2026, 1, 1)))
    write_trace(path, _built_trace(as_of_override=datetime(2026, 6, 1)))
    write_trace(path, _built_trace(as_of_override=datetime(2026, 12, 1)))

    records = read_traces(path, message_id="M001")

    assert len(records) == 3
    assert [r["as_of_override"] for r in records] == [
        "2026-01-01T00:00:00",
        "2026-06-01T00:00:00",
        "2026-12-01T00:00:00",
    ]


def test_read_traces_filters_by_message_id(tmp_path):
    path = tmp_path / "traces.jsonl"
    write_trace(path, _built_trace())
    other = dict(_built_trace())
    other["message_id"] = "M999"
    write_trace(path, other)

    records = read_traces(path, message_id="M999")

    assert len(records) == 1
    assert records[0]["message_id"] == "M999"


def test_read_traces_returns_empty_list_when_file_missing(tmp_path):
    assert read_traces(tmp_path / "does-not-exist.jsonl") == []
