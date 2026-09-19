import math
import re
from collections import Counter
from dataclasses import dataclass, field

from embargo.access import authorized
from embargo.models import Crossing, Fact, Message

DEFAULT_SIMILARITY_THRESHOLD = 0.3
_WORD_RE = re.compile(r"[a-z0-9]+")


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


def _tokenize(text: str) -> Counter:
    return Counter(_WORD_RE.findall(text.lower()))


def _cosine_similarity(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(count * b[token] for token, count in a.items() if token in b)
    norm_a = math.sqrt(sum(count * count for count in a.values()))
    norm_b = math.sqrt(sum(count * count for count in b.values()))
    return dot / (norm_a * norm_b)


def _fact_text(fact: Fact) -> str:
    return " ".join([fact.summary, *fact.entities, *fact.aliases])


def similarity_candidates(
    message: Message, facts: list[Fact], *, threshold: float = DEFAULT_SIMILARITY_THRESHOLD
) -> set[str]:
    """Bag-of-words cosine similarity between the message body and each
    fact's summary/entities/aliases text.

    Spec 13.5 asks for embedding-based retrieval; this is a deliberate SHOULD
    deviation (spec 0) -- no ML dependency, no network embedding call, kept
    stdlib-only and fully deterministic for tests. It only catches literal
    vocabulary overlap, not paraphrase or true semantic similarity, so a real
    embedding backend can replace this function's body without any caller
    change (same signature: message + facts in, fact_id set out).
    """
    message_vec = _tokenize(message.body)
    return {
        fact.fact_id
        for fact in facts
        if _cosine_similarity(message_vec, _tokenize(_fact_text(fact))) >= threshold
    }


def candidate_facts(
    message: Message,
    facts: list[Fact],
    crossings: list[Crossing],
    *,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[Candidate]:
    parties = [message.sender, *message.recipients]
    semantic_matches = similarity_candidates(message, facts, threshold=similarity_threshold)
    candidates = []
    for fact in facts:
        reasons = _keyword_match_reasons(message.body, fact)

        if fact.fact_id in semantic_matches:
            reasons.add("semantic_match")

        if any(
            authorized(crossings, party, fact.fact_id, message.timestamp)
            for party in parties
        ):
            reasons.add("party_authorization")

        if reasons:
            candidates.append(Candidate(fact=fact, reasons=reasons))

    return candidates
