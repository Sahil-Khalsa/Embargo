import json
import logging
from pathlib import Path
from typing import Callable, Protocol

from embargo.models import Fact, Message, Resolution, ResolutionMode

logger = logging.getLogger(__name__)


class ResolverOutputInvalid(Exception):
    """Raised when the model's output fails schema validation twice in a row
    (the original attempt plus one retry). The caller is expected to turn
    this into a `review` verdict with reason `resolver_output_invalid` —
    the resolver itself never emits a verdict."""


class Resolver(Protocol):
    def resolve(self, message: Message, candidates: list[Fact]) -> list[Resolution]: ...


def _reject_non_verbatim_spans(message: Message, resolutions: list[Resolution]) -> list[Resolution]:
    kept = []
    for resolution in resolutions:
        if resolution.span in message.body:
            kept.append(resolution)
        else:
            logger.warning(
                "rejecting resolution for fact_id=%s: span %r not verbatim in message %s body",
                resolution.fact_id,
                resolution.span,
                message.message_id,
            )
    return kept


def _resolutions_from_json(data: list[dict]) -> list[Resolution]:
    return [
        Resolution(
            fact_id=item["fact_id"],
            mode=ResolutionMode(item["mode"]),
            confidence=float(item["confidence"]),
            span=item["span"],
        )
        for item in data
    ]


class FakeResolver:
    def __init__(self, fixtures: dict[str, list[dict]]):
        self._fixtures = fixtures

    @classmethod
    def from_file(cls, path: str | Path) -> "FakeResolver":
        with open(path) as f:
            return cls(json.load(f))

    def resolve(self, message: Message, candidates: list[Fact]) -> list[Resolution]:
        raw = self._fixtures.get(message.message_id, [])
        resolutions = _resolutions_from_json(raw)
        return _reject_non_verbatim_spans(message, resolutions)


class ModelResolver:
    def __init__(self, model_call: Callable[[str], str]):
        self._model_call = model_call

    def resolve(self, message: Message, candidates: list[Fact]) -> list[Resolution]:
        prompt = self._build_prompt(message, candidates)

        for attempt in range(2):
            raw = self._model_call(prompt)
            try:
                resolutions = _resolutions_from_json(json.loads(raw))
                break
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                continue
        else:
            raise ResolverOutputInvalid(message.message_id)

        return _reject_non_verbatim_spans(message, resolutions)

    def _build_prompt(self, message: Message, candidates: list[Fact]) -> str:
        candidate_lines = "\n".join(
            f"- id: {fact.fact_id}\n"
            f"  summary: {fact.summary}\n"
            f"  entities: {', '.join(fact.entities)}\n"
            f"  aliases: {', '.join(fact.aliases)}"
            for fact in candidates
        )
        return (
            "A message was sent. For each candidate fact below, determine whether "
            "the message conveys that fact (communicates it) or merely mentions it "
            "(names an entity or topic the fact concerns without communicating the "
            "fact itself). Do not assess materiality, seriousness, or whether this "
            "is a violation — that is not your task.\n\n"
            f"Message:\n{message.body}\n\n"
            f"Candidate facts:\n{candidate_lines}\n\n"
            'Respond with JSON: a list of {"fact_id", "mode" ("conveys" or '
            '"mentions"), "confidence" (0-1), "span" (the exact substring of the '
            "message that triggered this resolution)}."
        )
