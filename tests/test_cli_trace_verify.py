import json

from embargo.cli import main
from embargo.trace import write_trace


def test_trace_verify_reports_intact_chain(tmp_path, capsys):
    trace_path = tmp_path / "traces.jsonl"
    write_trace(trace_path, {"message_id": "M1", "verdict": "clean"})
    write_trace(trace_path, {"message_id": "M2", "verdict": "review"})

    main(["trace", "verify", "--trace-file", str(trace_path)])
    out = capsys.readouterr().out

    assert "intact" in out.lower()


def test_trace_verify_reports_break_line_for_tampered_file(tmp_path, capsys):
    trace_path = tmp_path / "traces.jsonl"
    write_trace(trace_path, {"message_id": "M1", "verdict": "clean"})
    write_trace(trace_path, {"message_id": "M2", "verdict": "review"})
    write_trace(trace_path, {"message_id": "M3", "verdict": "clean"})

    lines = trace_path.read_text().strip().split("\n")
    tampered = json.loads(lines[1])
    tampered["verdict"] = "violation_disclosure"
    lines[1] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    trace_path.write_text("\n".join(lines) + "\n", newline="")

    main(["trace", "verify", "--trace-file", str(trace_path)])
    out = capsys.readouterr().out

    assert "broken" in out.lower()
    assert "line 3" in out.lower()


def test_trace_verify_missing_file_reports_intact(tmp_path, capsys):
    trace_path = tmp_path / "nope.jsonl"

    main(["trace", "verify", "--trace-file", str(trace_path)])
    out = capsys.readouterr().out

    assert "intact" in out.lower()
