"""spec §14.3: reviewer actions (confirm/dismiss/escalate) append to the
same trace chain as screenings, never overwriting anything. A separate
record_type discriminator is what keeps rescreen_stale_traces() and
current_traces() from crashing on a record shape they don't expect --
see tests/test_rescreen_ignores_reviewer_actions.py for that half."""

from datetime import datetime

import pytest

from embargo.trace import build_reviewer_action


def test_build_reviewer_action_record_type_is_reviewer_action():
    record = build_reviewer_action(
        message_id="M001", trace_id_referenced="abc123", action="confirm",
        reviewer="alice", at=datetime(2026, 6, 1),
    )

    assert record["record_type"] == "reviewer_action"
    assert record["message_id"] == "M001"
    assert record["trace_id_referenced"] == "abc123"
    assert record["action"] == "confirm"
    assert record["reviewer"] == "alice"
    assert record["at"] == "2026-06-01T00:00:00"
    assert record["reason"] is None


def test_build_reviewer_action_dismiss_carries_a_reason():
    record = build_reviewer_action(
        message_id="M001", trace_id_referenced="abc123", action="dismiss",
        reviewer="alice", at=datetime(2026, 6, 1), reason="false positive, routine report name",
    )

    assert record["action"] == "dismiss"
    assert record["reason"] == "false positive, routine report name"


def test_build_reviewer_action_rejects_invalid_action():
    with pytest.raises(ValueError, match="escalate_now"):
        build_reviewer_action(
            message_id="M001", trace_id_referenced="abc123", action="escalate_now",
            reviewer="alice", at=datetime(2026, 6, 1),
        )


def test_build_reviewer_action_has_a_content_hash_trace_id():
    record = build_reviewer_action(
        message_id="M001", trace_id_referenced="abc123", action="escalate",
        reviewer="alice", at=datetime(2026, 6, 1),
    )

    assert "trace_id" in record
    assert len(record["trace_id"]) == 64  # sha256 hex digest
