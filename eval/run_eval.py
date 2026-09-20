import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from embargo.config import DEFAULT_THRESHOLD
from embargo.decision import decide
from embargo.models import Crossing, Fact, FactState, MaterialityLevel, Message, ResolutionMode, Verdict
from embargo.prefilter import candidate_facts
from embargo.resolver import FakeResolver


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def load_facts(path: str | Path) -> list[Fact]:
    with open(path) as f:
        raw = yaml.safe_load(f) or []
    return [
        Fact(
            fact_id=item["fact_id"],
            summary=item["summary"],
            entities=item.get("entities", []),
            aliases=item.get("aliases", []),
            state=FactState(item["state"]),
            recorded_at=_parse_dt(item["recorded_at"]),
            materiality=[
                (_parse_dt(m["effective_from"]), MaterialityLevel(m["level"]))
                for m in item["materiality"]
            ],
            announced_at=_parse_dt(item["announced_at"]) if item.get("announced_at") else None,
            cleared_at=_parse_dt(item["cleared_at"]) if item.get("cleared_at") else None,
        )
        for item in raw
    ]


def load_crossings(path: str | Path) -> list[Crossing]:
    with open(path) as f:
        raw = yaml.safe_load(f) or []
    return [
        Crossing(
            party_id=item["party_id"],
            fact_id=item["fact_id"],
            effective_from=_parse_dt(item["effective_from"]),
            effective_until=_parse_dt(item["effective_until"]) if item.get("effective_until") else None,
        )
        for item in raw
    ]


def load_messages_raw(path: str | Path) -> list[dict]:
    with open(path) as f:
        return yaml.safe_load(f) or []


def _message_from_dict(item: dict) -> Message:
    return Message(
        message_id=item["message_id"],
        sender=item["sender"],
        recipients=list(item["recipients"]),
        timestamp=_parse_dt(item["timestamp"]),
        body=item["body"],
    )


@dataclass
class EvalReport:
    total_messages: int
    resolver_precision: float
    resolver_recall: float
    conveys_mentions_confusion: int
    verdict_accuracy: float
    confusion_matrix: dict[str, dict[str, int]]
    prefilter_recall: float


def run_eval(
    facts_path: str | Path,
    crossings_path: str | Path,
    messages_path: str | Path,
    fixtures_path: str | Path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    resolver=None,
) -> EvalReport:
    """`resolver`, if given, is used instead of building a FakeResolver from
    fixtures_path -- this is what lets a different backend (spec §14.2) run
    the eval via `embargo.backends.build_resolver()` without any code change
    here. fixtures_path is still required as the corpus's expected-behavior
    source when no resolver is given (the default, fixture-run path)."""
    facts = load_facts(facts_path)
    crossings = load_crossings(crossings_path)
    raw_messages = load_messages_raw(messages_path)
    if resolver is None:
        resolver = FakeResolver.from_file(fixtures_path)
    facts_by_id = {fact.fact_id: fact for fact in facts}

    verdict_labels = [v.value for v in Verdict]
    confusion = {expected: {actual: 0 for actual in verdict_labels} for expected in verdict_labels}

    true_positives = false_positives = missed = confused = 0
    correct = 0
    prefilter_reached = prefilter_total = 0

    for item in raw_messages:
        message = _message_from_dict(item)
        expected_verdict = item["expected_verdict"]
        expected_fact_ids = set(item.get("expected_fact_ids", []))

        candidates = candidate_facts(message, facts, crossings)
        candidate_fact_objs = [c.fact for c in candidates]
        candidate_ids = {c.fact.fact_id for c in candidates}

        # Computed from prefilter output alone, never from resolutions: a
        # fact the resolver never even saw must count as a miss here, since
        # it's invisible to every resolver-level metric and looks clean.
        prefilter_total += len(expected_fact_ids)
        prefilter_reached += len(expected_fact_ids & candidate_ids)

        resolutions = resolver.resolve(message, candidate_fact_objs)

        conveyed = {r.fact_id for r in resolutions if r.mode == ResolutionMode.CONVEYS}
        mentioned = {r.fact_id for r in resolutions if r.mode == ResolutionMode.MENTIONS}

        true_positives += len(conveyed & expected_fact_ids)
        false_positives += len(conveyed - expected_fact_ids)
        confused += len(mentioned & expected_fact_ids)
        missed += len(expected_fact_ids - conveyed - mentioned)

        decision = decide(message, resolutions, facts_by_id, crossings, threshold=threshold)
        confusion[expected_verdict][decision.verdict.value] += 1
        if decision.verdict.value == expected_verdict:
            correct += 1

    resolver_precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives)
        else 1.0
    )
    resolver_recall = (
        true_positives / (true_positives + missed + confused)
        if (true_positives + missed + confused)
        else 1.0
    )
    total = len(raw_messages)
    verdict_accuracy = correct / total if total else 1.0
    prefilter_recall = prefilter_reached / prefilter_total if prefilter_total else 1.0

    return EvalReport(
        total_messages=total,
        resolver_precision=resolver_precision,
        resolver_recall=resolver_recall,
        conveys_mentions_confusion=confused,
        verdict_accuracy=verdict_accuracy,
        confusion_matrix=confusion,
        prefilter_recall=prefilter_recall,
    )


def format_report(report: EvalReport) -> str:
    labels = list(report.confusion_matrix.keys())
    lines = [
        f"messages evaluated: {report.total_messages}",
        "",
        "-- resolver metrics (fact-id attribution) --",
        f"precision: {report.resolver_precision:.3f}",
        f"recall: {report.resolver_recall:.3f}",
        f"conveys/mentions confusion (expected conveys, predicted mentions): {report.conveys_mentions_confusion}",
        "",
        "-- prefilter metrics --",
        f"prefilter recall (expected fact reached the resolver at all): {report.prefilter_recall:.3f}",
        "",
        "-- end-to-end verdict accuracy --",
        f"accuracy: {report.verdict_accuracy:.3f}",
        "confusion matrix (rows=expected, cols=actual):",
        "expected\\actual".ljust(24) + "".join(label.ljust(24) for label in labels),
    ]
    for expected in labels:
        row = expected.ljust(24) + "".join(
            str(report.confusion_matrix[expected][actual]).ljust(24) for actual in labels
        )
        lines.append(row)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="run_eval")
    parser.add_argument("--facts", default="corpus/facts.yaml")
    parser.add_argument("--crossings", default="corpus/crossings.yaml")
    parser.add_argument("--messages", default="corpus/messages.yaml")
    parser.add_argument("--fixtures", default="eval/fixtures/resolutions.json")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)

    report = run_eval(args.facts, args.crossings, args.messages, args.fixtures, threshold=args.threshold)
    print(format_report(report))


if __name__ == "__main__":
    main()
