import re
from dataclasses import dataclass, field

from embargo.access import authorized
from embargo.models import Crossing, Fact, Message


@dataclass
class Candidate:
    fact: Fact
    reasons: set[str] = field(default_factory=set)


def _keyword_match_reasons(body: str, fact: Fact) -> set[str]:
    reasons = set()
    if any(re.search(rf"\b{re.escape(entity)}\b", body, re.IGNORECASE) for entity in fact.entities):
        reasons.add("entity_match")
    if any(re.search(rf"\b{re.escape(alias)}\b", body, re.IGNORECASE) for alias in fact.aliases):
        reasons.add("alias_match")
    return reasons


def candidate_facts(
    message: Message, facts: list[Fact], crossings: list[Crossing]
) -> list[Candidate]:
    parties = [message.sender, *message.recipients]
    candidates = []
    for fact in facts:
        reasons = _keyword_match_reasons(message.body, fact)

        if any(
            authorized(crossings, party, fact.fact_id, message.timestamp)
            for party in parties
        ):
            reasons.add("party_authorization")

        if reasons:
            candidates.append(Candidate(fact=fact, reasons=reasons))

    return candidates
