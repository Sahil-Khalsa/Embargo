"""Business logic for the reviewer UI (spec §14.3), kept independent of any
HTTP mechanics so it's directly testable. embargo/reviewer_server.py wraps
this in stdlib http.server."""

from datetime import datetime
from pathlib import Path

from embargo.access import Access
from embargo.ledger import Ledger
from embargo.models import Verdict
from embargo.rescreen import current_traces
from embargo.trace import build_reviewer_action, read_traces, write_trace


def build_queue(trace_path: str | Path) -> list[dict]:
    """Current (non-superseded) screening records with a non-clean verdict,
    most severe first. Python's sort is stable, so sorting by trace_id
    first and then by verdict gives a deterministic tie-break without a
    combined sort key."""
    records = read_traces(trace_path)
    findings = [r for r in current_traces(records) if r["verdict"] != Verdict.CLEAN.value]
    findings.sort(key=lambda r: r["trace_id"])
    findings.sort(key=lambda r: Verdict(r["verdict"]), reverse=True)
    return findings


def get_finding(trace_path: str | Path, trace_id: str) -> dict | None:
    for record in read_traces(trace_path):
        if record.get("record_type", "screening") == "screening" and record["trace_id"] == trace_id:
            return record
    return None


def build_evidence_chain(trace_path: str | Path, ledger: Ledger, access: Access, trace_id: str) -> dict:
    """The complete evidence chain for one finding (spec §14.3): the
    screening record, every fact it resolved with its state/timeline from
    the ledger, the authorization lookup for every party (surfaced from the
    per-fact checks already recorded in the trace, not recomputed), and any
    reviewer actions already taken on it."""
    screening = get_finding(trace_path, trace_id)
    if screening is None:
        raise KeyError(f"no screening trace found for trace_id={trace_id!r}")

    facts = []
    authorization: dict[str, bool] = {}
    for fact_result in screening["fact_results"]:
        fact = ledger.get_fact(fact_result["fact_id"])
        facts.append({
            "fact_id": fact.fact_id,
            "summary": fact.summary,
            "state": fact.state.value,
            "recorded_at": fact.recorded_at.isoformat(),
            "announced_at": fact.announced_at.isoformat() if fact.announced_at else None,
            "cleared_at": fact.cleared_at.isoformat() if fact.cleared_at else None,
            "materiality": [
                {"effective_from": effective_from.isoformat(), "level": level.value}
                for effective_from, level in fact.materiality
            ],
        })
        checks = fact_result.get("checks")
        if checks:
            authorization.setdefault(screening["sender"], checks["sender_authorized"])
            for recipient, ok in checks["recipient_authorized"].items():
                authorization.setdefault(recipient, ok)

    reviewer_actions = [
        record
        for record in read_traces(trace_path, message_id=screening["message_id"])
        if record.get("record_type") == "reviewer_action" and record["trace_id_referenced"] == trace_id
    ]

    return {
        "screening": screening,
        "facts": facts,
        "authorization": authorization,
        "reviewer_actions": reviewer_actions,
    }


def record_reviewer_action(
    trace_path: str | Path,
    trace_id: str,
    action: str,
    *,
    reviewer: str,
    at: datetime | None = None,
    reason: str | None = None,
) -> dict:
    screening = get_finding(trace_path, trace_id)
    if screening is None:
        raise KeyError(f"no screening trace found for trace_id={trace_id!r}")

    record = build_reviewer_action(
        message_id=screening["message_id"],
        trace_id_referenced=trace_id,
        action=action,
        reviewer=reviewer,
        at=at or datetime.now(),
        reason=reason,
    )
    write_trace(trace_path, record)
    return record
