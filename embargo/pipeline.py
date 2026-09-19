from datetime import datetime

from embargo.decision import decide
from embargo.models import Crossing, Fact, Message, Verdict
from embargo.prefilter import candidate_facts
from embargo.resolver import Resolver, ResolverOutputInvalid
from embargo.trace import build_resolver_failure_trace, build_trace

DEFAULT_THRESHOLD = 0.6


def screen_message(
    message: Message,
    facts: list[Fact],
    crossings: list[Crossing],
    resolver: Resolver,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    as_of_override: datetime | None = None,
    recipients_override: list[str] | None = None,
    ledger_version: int = 0,
    supersedes: str | None = None,
) -> tuple[dict, Verdict]:
    candidates = candidate_facts(message, facts, crossings)
    candidate_facts_only = [c.fact for c in candidates]

    try:
        resolutions = resolver.resolve(message, candidate_facts_only)
    except ResolverOutputInvalid:
        record = build_resolver_failure_trace(
            message,
            candidates,
            as_of_override=as_of_override,
            recipients_override=recipients_override,
            ledger_version=ledger_version,
            supersedes=supersedes,
        )
        return record, Verdict.REVIEW

    facts_by_id = {fact.fact_id: fact for fact in candidate_facts_only}
    decision = decide(message, resolutions, facts_by_id, crossings, threshold=threshold)
    record = build_trace(
        message,
        candidates,
        resolutions,
        decision,
        as_of_override=as_of_override,
        recipients_override=recipients_override,
        ledger_version=ledger_version,
        supersedes=supersedes,
    )
    return record, decision.verdict
