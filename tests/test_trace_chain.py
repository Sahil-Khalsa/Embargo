import hashlib
import json

from embargo.trace import verify_chain, write_trace


def _raw_lines(path):
    with open(path, "r", newline="") as f:
        content = f.read()
    return [line for line in content.split("\n") if line]


def test_first_record_has_null_prev_hash(tmp_path):
    path = tmp_path / "traces.jsonl"
    write_trace(path, {"message_id": "M1", "verdict": "clean"})

    lines = _raw_lines(path)
    assert len(lines) == 1
    assert json.loads(lines[0])["prev_hash"] is None


def test_second_record_prev_hash_is_sha256_of_first_raw_line(tmp_path):
    path = tmp_path / "traces.jsonl"
    write_trace(path, {"message_id": "M1", "verdict": "clean"})
    write_trace(path, {"message_id": "M2", "verdict": "review"})

    lines = _raw_lines(path)
    assert len(lines) == 2
    expected = hashlib.sha256(lines[0].encode("utf-8")).hexdigest()
    assert json.loads(lines[1])["prev_hash"] == expected


def test_verify_chain_ok_for_untampered_file(tmp_path):
    path = tmp_path / "traces.jsonl"
    write_trace(path, {"message_id": "M1", "verdict": "clean"})
    write_trace(path, {"message_id": "M2", "verdict": "review"})
    write_trace(path, {"message_id": "M3", "verdict": "clean"})

    result = verify_chain(path)

    assert result.ok is True
    assert result.broken_at_line is None


def test_verify_chain_ok_for_missing_file(tmp_path):
    path = tmp_path / "does_not_exist.jsonl"

    result = verify_chain(path)

    assert result.ok is True
    assert result.broken_at_line is None


def test_verify_chain_detects_hand_edited_record(tmp_path):
    path = tmp_path / "traces.jsonl"
    write_trace(path, {"message_id": "M1", "verdict": "clean"})
    write_trace(path, {"message_id": "M2", "verdict": "review"})
    write_trace(path, {"message_id": "M3", "verdict": "clean"})

    lines = _raw_lines(path)
    tampered = json.loads(lines[1])
    tampered["verdict"] = "violation_disclosure"  # hand-edit the middle record
    lines[1] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", newline="")

    result = verify_chain(path)

    assert result.ok is False
    # Line 3's stored prev_hash was computed against the original line 2;
    # it no longer matches the (now-edited) line 2, so the break surfaces
    # at line 3 -- the first point verification actually fails.
    assert result.broken_at_line == 3
