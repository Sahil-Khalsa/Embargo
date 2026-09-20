from datetime import datetime
from pathlib import Path

from embargo.config import DEFAULT_THRESHOLD
from embargo.decision import decide
from embargo.models import Crossing, Fact, Message, Verdict
from embargo.prefilter import candidate_facts
from embargo.resolver import Resolver, ResolverOutputInvalid
from embargo.trace import build_resolver_failure_trace, build_trace, write_trace


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

    # Duck-typed rather than part of the Resolver Protocol (spec §7 says the
    # Protocol's shape MUST NOT change): every concrete resolver carries
    # these two attributes, but a hand-rolled test double need not.
    backend = getattr(resolver, "backend_name", "unknown")
    model_version = getattr(resolver, "model_version", "unknown")

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
            backend=backend,
            model_version=model_version,
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
        backend=backend,
        model_version=model_version,
    )
    return record, decision.verdict


def screen_and_write(
    message: Message,
    facts: list[Fact],
    crossings: list[Crossing],
    resolver: Resolver,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    trace_file: str | Path,
    as_of_override: datetime | None = None,
    recipients_override: list[str] | None = None,
    ledger_version: int = 0,
    supersedes: str | None = None,
) -> tuple[dict, Verdict]:
    """screen_message() + write_trace(): the single code path every
    screening entry point (CLI --message, --batch, the optional HTTP
    endpoint) goes through. Spec §14.4's byte-identical-traces requirement
    depends on there being exactly one such path, not several that happen
    to agree -- so this exists precisely to be the only place that pairs
    the two calls."""
    record, verdict = screen_message(
        message,
        facts,
        crossings,
        resolver,
        threshold=threshold,
        as_of_override=as_of_override,
        recipients_override=recipients_override,
        ledger_version=ledger_version,
        supersedes=supersedes,
    )
    Path(trace_file).parent.mkdir(parents=True, exist_ok=True)
    write_trace(trace_file, record)
    return record, verdict
