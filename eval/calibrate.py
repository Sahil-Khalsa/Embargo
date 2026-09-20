import argparse
from dataclasses import dataclass
from pathlib import Path

from embargo.decision import decide
from embargo.models import ResolutionMode, Verdict
from embargo.prefilter import candidate_facts
from embargo.resolver import FakeResolver

from eval.run_eval import _message_from_dict, load_crossings, load_facts, load_messages_raw

DEFAULT_THRESHOLDS = [round(i * 0.05, 2) for i in range(21)]


@dataclass
class CalibrationPoint:
    threshold: float
    resolver_precision: float
    resolver_recall: float
    review_share: float
    verdict_accuracy: float


def _metrics_at_threshold(raw_messages, facts, crossings, resolver, threshold: float) -> CalibrationPoint:
    facts_by_id = {fact.fact_id: fact for fact in facts}

    true_positives = false_positives = missed = 0
    review_count = 0
    correct = 0
    total = len(raw_messages)

    for item in raw_messages:
        message = _message_from_dict(item)
        expected_verdict = item["expected_verdict"]
        expected_fact_ids = set(item.get("expected_fact_ids", []))

        candidates = candidate_facts(message, facts, crossings)
        candidate_fact_objs = [c.fact for c in candidates]
        resolutions = resolver.resolve(message, candidate_fact_objs)

        # A fact counts as correctly identified only if it actually clears
        # the gate (conveys + confidence >= threshold) -- that's the set
        # that reaches an automatic decision at this threshold. Everything
        # else (mentions, or conveys below threshold) is not a match here,
        # so precision/recall genuinely move as the threshold sweeps.
        accepted = {
            r.fact_id
            for r in resolutions
            if r.mode == ResolutionMode.CONVEYS and r.confidence >= threshold
        }

        true_positives += len(accepted & expected_fact_ids)
        false_positives += len(accepted - expected_fact_ids)
        missed += len(expected_fact_ids - accepted)

        decision = decide(message, resolutions, facts_by_id, crossings, threshold=threshold)
        if decision.verdict == Verdict.REVIEW:
            review_count += 1
        if decision.verdict.value == expected_verdict:
            correct += 1

    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives)
        else 1.0
    )
    recall = (
        true_positives / (true_positives + missed)
        if (true_positives + missed)
        else 1.0
    )
    review_share = review_count / total if total else 0.0
    accuracy = correct / total if total else 1.0

    return CalibrationPoint(
        threshold=threshold,
        resolver_precision=precision,
        resolver_recall=recall,
        review_share=review_share,
        verdict_accuracy=accuracy,
    )


def sweep_thresholds(
    facts_path: str | Path,
    crossings_path: str | Path,
    messages_path: str | Path,
    fixtures_path: str | Path,
    thresholds: list[float] | None = None,
    resolver=None,
) -> list[CalibrationPoint]:
    """`resolver`, if given, is used instead of building a FakeResolver from
    fixtures_path -- lets a different backend (spec §14.2) run the
    calibration sweep without any code change here."""
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    facts = load_facts(facts_path)
    crossings = load_crossings(crossings_path)
    raw_messages = load_messages_raw(messages_path)
    if resolver is None:
        resolver = FakeResolver.from_file(fixtures_path)

    return [
        _metrics_at_threshold(raw_messages, facts, crossings, resolver, threshold)
        for threshold in thresholds
    ]


def best_threshold_for_budget(points: list[CalibrationPoint], budget: float) -> CalibrationPoint | None:
    """Among points whose review_share fits the budget, the one that
    maximizes resolver recall (ties broken toward the lower threshold).

    Note (confirmed, not a bug): recall(t) = TP(t) / |expected fact ids| is
    monotone non-increasing in t (TP(t) only shrinks as the gate tightens),
    and review_share(0.0) is always 0.0 -- so this always returns the
    smallest threshold in `points` for any non-negative budget. The budget
    does not bind here; format_calibration_report says so explicitly rather
    than presenting one silent number as if a real trade-off were made.
    """
    eligible = [p for p in points if p.review_share <= budget]
    if not eligible:
        return None
    return max(eligible, key=lambda p: (p.resolver_recall, -p.threshold))


def best_threshold_for_accuracy(points: list[CalibrationPoint]) -> CalibrationPoint:
    """The threshold with the highest end-to-end verdict accuracy, ties
    broken toward the lower threshold. Unlike resolver recall, accuracy
    reflects the decision layer's authorization checks too, so it is not
    monotone in threshold and is a genuinely informative second reference
    point for choosing an operating threshold."""
    return max(points, key=lambda p: (p.verdict_accuracy, -p.threshold))


def format_calibration_report(points: list[CalibrationPoint], *, budget: float | None = None) -> str:
    header = "threshold".ljust(12) + "precision".ljust(12) + "recall".ljust(12) + "review_share".ljust(14) + "accuracy"
    lines = [header]
    for p in points:
        lines.append(
            f"{p.threshold:.2f}".ljust(12)
            + f"{p.resolver_precision:.3f}".ljust(12)
            + f"{p.resolver_recall:.3f}".ljust(12)
            + f"{p.review_share:.3f}".ljust(14)
            + f"{p.verdict_accuracy:.3f}"
        )

    if budget is not None:
        lines.append("")
        best = best_threshold_for_budget(points, budget)
        if best is None:
            lines.append(f"no threshold keeps review_share <= {budget:.3f}")
        else:
            lines.append(
                f"best threshold for review budget <= {budget:.3f}: "
                f"{best.threshold:.2f} (recall={best.resolver_recall:.3f}, "
                f"review_share={best.review_share:.3f})"
            )
        lines.append(
            "note: resolver recall is monotone non-increasing in threshold and "
            "review_share(0.0) is always 0.0, so the recall-maximizing choice "
            "under any non-negative budget is always the lowest threshold in "
            "the sweep -- the budget does not bind here, this pick reflects "
            "the metric definition, not a genuine trade-off."
        )
        accuracy_best = best_threshold_for_accuracy(points)
        lines.append(
            f"best threshold for verdict accuracy: {accuracy_best.threshold:.2f} "
            f"(accuracy={accuracy_best.verdict_accuracy:.3f}) -- accuracy reflects "
            "the decision layer's authorization checks too, so unlike recall it "
            "is not monotone in threshold and is a genuinely informative "
            "operating point to consider alongside the recall-maximizing one."
        )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="calibrate")
    parser.add_argument("--facts", default="corpus/facts.yaml")
    parser.add_argument("--crossings", default="corpus/crossings.yaml")
    parser.add_argument("--messages", default="corpus/messages.yaml")
    parser.add_argument("--fixtures", default="eval/fixtures/resolutions.json")
    parser.add_argument("--budget", type=float, default=None)
    args = parser.parse_args(argv)

    points = sweep_thresholds(args.facts, args.crossings, args.messages, args.fixtures)
    print(format_calibration_report(points, budget=args.budget))


if __name__ == "__main__":
    main()
