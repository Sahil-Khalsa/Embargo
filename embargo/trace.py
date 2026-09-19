import hashlib
import json
from datetime import datetime
from pathlib import Path

from embargo.decision import FactChecks, FactDecision, MessageDecision
from embargo.models import Message, Resolution, Verdict
from embargo.prefilter import Candidate


def _checks_to_dict(checks: FactChecks) -> dict:
    return {
        "is_cleared": checks.is_cleared,
        "materiality": checks.materiality.value,
        "sender_authorized": checks.sender_authorized,
        "recipient_authorized": checks.recipient_authorized,
    }


def _finalize(record: dict) -> dict:
    # trace_id is a content hash, not a random id: two screenings with
    # identical content get the same id (relevant to V2's byte-identical-
    # traces requirement), and it doubles as the identity §13.4's hash chain
    # needs rather than introducing a second id concept.
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
    record["trace_id"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return record


def _fact_result_to_dict(resolution: Resolution, fact_decision: FactDecision) -> dict:
    return {
        "fact_id": fact_decision.fact_id,
        "mode": fact_decision.mode.value,
        "confidence": fact_decision.confidence,
        "span": resolution.span,
        "proceeded": fact_decision.proceeded,
        "verdict": fact_decision.verdict.value if fact_decision.verdict else None,
        "reason": fact_decision.reason,
        "checks": _checks_to_dict(fact_decision.checks) if fact_decision.checks else None,
    }


def build_trace(
    message: Message,
    candidates: list[Candidate],
    resolutions: list[Resolution],
    decision: MessageDecision,
    *,
    as_of_override: datetime | None = None,
    recipients_override: list[str] | None = None,
    ledger_version: int = 0,
    supersedes: str | None = None,
) -> dict:
    return _finalize({
        "message_id": message.message_id,
        "sender": message.sender,
        "recipients": message.recipients,
        "timestamp": message.timestamp.isoformat(),
        "as_of_override": as_of_override.isoformat() if as_of_override else None,
        "recipients_override": recipients_override,
        "body": message.body,
        "candidates": [
            {"fact_id": c.fact.fact_id, "reasons": sorted(c.reasons)} for c in candidates
        ],
        "fact_results": [
            _fact_result_to_dict(resolution, fact_decision)
            for resolution, fact_decision in zip(resolutions, decision.fact_decisions)
        ],
        "verdict": decision.verdict.value,
        "reason": None,
        "ledger_version": ledger_version,
        "supersedes": supersedes,
    })


def build_resolver_failure_trace(
    message: Message,
    candidates: list[Candidate],
    *,
    as_of_override: datetime | None = None,
    recipients_override: list[str] | None = None,
    ledger_version: int = 0,
    supersedes: str | None = None,
) -> dict:
    return _finalize({
        "message_id": message.message_id,
        "sender": message.sender,
        "recipients": message.recipients,
        "timestamp": message.timestamp.isoformat(),
        "as_of_override": as_of_override.isoformat() if as_of_override else None,
        "recipients_override": recipients_override,
        "body": message.body,
        "candidates": [
            {"fact_id": c.fact.fact_id, "reasons": sorted(c.reasons)} for c in candidates
        ],
        "fact_results": [],
        "verdict": Verdict.REVIEW.value,
        "reason": "resolver_output_invalid",
        "ledger_version": ledger_version,
        "supersedes": supersedes,
    })


def write_trace(path: str | Path, record: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def read_traces(path: str | Path, message_id: str | None = None) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if message_id is None or record["message_id"] == message_id:
                records.append(record)
    return records
