from dataclasses import dataclass

from embargo.access import authorized
from embargo.config import DEFAULT_THRESHOLD
from embargo.ledger import materiality_at
from embargo.models import (
    Crossing,
    Fact,
    FactState,
    MaterialityLevel,
    Message,
    Resolution,
    ResolutionMode,
    Verdict,
)


@dataclass
class FactChecks:
    is_cleared: bool
    materiality: MaterialityLevel
    sender_authorized: bool
    recipient_authorized: dict[str, bool]


@dataclass
class FactDecision:
    fact_id: str
    mode: ResolutionMode
    confidence: float
    proceeded: bool
    verdict: Verdict | None
    reason: str | None
    checks: FactChecks | None


@dataclass
class MessageDecision:
    message_id: str
    verdict: Verdict
    fact_decisions: list[FactDecision]


def _decide_fact(fact: Fact, message: Message, crossings: list[Crossing]) -> tuple[FactChecks, Verdict]:
    is_cleared = (
        fact.state == FactState.CLEARED
        and fact.cleared_at is not None
        and message.timestamp >= fact.cleared_at
    )
    materiality = materiality_at(fact, message.timestamp)
    sender_authorized = authorized(crossings, message.sender, fact.fact_id, message.timestamp)
    recipient_authorized = {
        recipient: authorized(crossings, recipient, fact.fact_id, message.timestamp)
        for recipient in message.recipients
    }

    if is_cleared:
        verdict = Verdict.CLEAN
    elif materiality == MaterialityLevel.NONE:
        verdict = Verdict.CLEAN
    elif not sender_authorized:
        verdict = Verdict.VIOLATION_UPSTREAM_LEAK
    elif not all(recipient_authorized.values()):
        verdict = Verdict.VIOLATION_DISCLOSURE
    else:
        verdict = Verdict.CLEAN

    checks = FactChecks(
        is_cleared=is_cleared,
        materiality=materiality,
        sender_authorized=sender_authorized,
        recipient_authorized=recipient_authorized,
    )
    return checks, verdict


def decide(
    message: Message,
    resolutions: list[Resolution],
    facts: dict[str, Fact],
    crossings: list[Crossing],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> MessageDecision:
    fact_decisions = []

    for resolution in resolutions:
        if resolution.mode == ResolutionMode.MENTIONS:
            fact_decisions.append(
                FactDecision(
                    fact_id=resolution.fact_id,
                    mode=resolution.mode,
                    confidence=resolution.confidence,
                    proceeded=False,
                    verdict=None,
                    reason=None,
                    checks=None,
                )
            )
            continue

        if resolution.confidence < threshold:
            fact_decisions.append(
                FactDecision(
                    fact_id=resolution.fact_id,
                    mode=resolution.mode,
                    confidence=resolution.confidence,
                    proceeded=False,
                    verdict=Verdict.REVIEW,
                    reason="low_confidence",
                    checks=None,
                )
            )
            continue

        fact = facts[resolution.fact_id]
        checks, verdict = _decide_fact(fact, message, crossings)
        fact_decisions.append(
            FactDecision(
                fact_id=resolution.fact_id,
                mode=resolution.mode,
                confidence=resolution.confidence,
                proceeded=True,
                verdict=verdict,
                reason=None,
                checks=checks,
            )
        )

    contributing = [fd.verdict for fd in fact_decisions if fd.verdict is not None]
    message_verdict = max(contributing) if contributing else Verdict.CLEAN

    return MessageDecision(
        message_id=message.message_id,
        verdict=message_verdict,
        fact_decisions=fact_decisions,
    )
