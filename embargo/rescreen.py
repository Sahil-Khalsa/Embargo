from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from embargo.models import Crossing, Fact, Message
from embargo.pipeline import screen_message
from embargo.resolver import Resolver
from embargo.trace import read_traces, write_trace


def current_traces(records: list[dict]) -> list[dict]:
    """Traces not superseded by any other record in the list."""
    superseded_ids = {r["supersedes"] for r in records if r.get("supersedes")}
    return [r for r in records if r["trace_id"] not in superseded_ids]


def _message_from_trace(record: dict) -> Message:
    return Message(
        message_id=record["message_id"],
        sender=record["sender"],
        recipients=list(record["recipients"]),
        timestamp=datetime.fromisoformat(record["timestamp"]),
        body=record["body"],
    )


@dataclass
class RescreenChange:
    message_id: str
    old_trace_id: str
    new_trace_id: str
    old_verdict: str
    new_verdict: str


def rescreen_stale_traces(
    trace_path: str | Path,
    facts: list[Fact],
    crossings: list[Crossing],
    resolver: Resolver,
    *,
    max_version: int,
    current_version: int,
    timestamp_from: datetime | None = None,
    threshold: float = 0.6,
) -> list[RescreenChange]:
    """Re-screens every current (non-superseded) trace recorded at
    ledger_version < max_version, against the given (current) facts/
    crossings. A new superseding trace is written for every affected
    message, whether or not its verdict changed; only the ones whose
    verdict changed are returned, matching spec §13.1's "report of
    verdicts that changed" (the write is unconditional -- the report
    is not)."""
    records = read_traces(trace_path)
    stale = [
        record
        for record in current_traces(records)
        if record["ledger_version"] < max_version
        and (
            timestamp_from is None
            or datetime.fromisoformat(record["timestamp"]) >= timestamp_from
        )
    ]

    changes = []
    for old_record in stale:
        message = _message_from_trace(old_record)
        new_record, new_verdict = screen_message(
            message,
            facts,
            crossings,
            resolver,
            threshold=threshold,
            ledger_version=current_version,
            supersedes=old_record["trace_id"],
        )
        write_trace(trace_path, new_record)

        if new_verdict.value != old_record["verdict"]:
            changes.append(
                RescreenChange(
                    message_id=old_record["message_id"],
                    old_trace_id=old_record["trace_id"],
                    new_trace_id=new_record["trace_id"],
                    old_verdict=old_record["verdict"],
                    new_verdict=new_verdict.value,
                )
            )

    return changes
