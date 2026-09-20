import json

import yaml

from embargo.resolver import FakeResolver
from eval.calibrate import best_threshold_for_accuracy, best_threshold_for_budget, sweep_thresholds

FACTS = [
    {
        "fact_id": "F1", "summary": "Acme fact", "entities": ["Acme"], "aliases": [],
        "state": "announced", "recorded_at": "2026-01-01T00:00:00",
        "announced_at": "2026-01-01T00:00:00",
        "materiality": [{"effective_from": "2026-01-01T00:00:00", "level": "high"}],
    },
]

CROSSINGS = [
    {"party_id": "alice", "fact_id": "F1", "effective_from": "2026-01-01T00:00:00"},
    {"party_id": "bob", "fact_id": "F1", "effective_from": "2026-01-01T00:00:00"},
]

# Both messages are about the same fully-authorized fact (so acceptance is
# clean when accepted); confidence differs, so the sweep moves predictably.
MESSAGES = [
    {
        "message_id": "M1", "sender": "alice", "recipients": ["bob"],
        "timestamp": "2026-06-01T00:00:00", "body": "Acme update, high confidence",
        "expected_verdict": "clean", "expected_fact_ids": ["F1"],
    },
    {
        "message_id": "M2", "sender": "alice", "recipients": ["bob"],
        "timestamp": "2026-06-01T00:00:00", "body": "Acme update, low confidence",
        "expected_verdict": "clean", "expected_fact_ids": ["F1"],
    },
]

FIXTURES = {
    "M1": [{"fact_id": "F1", "mode": "conveys", "confidence": 0.8, "span": "Acme update, high confidence"}],
    "M2": [{"fact_id": "F1", "mode": "conveys", "confidence": 0.3, "span": "Acme update, low confidence"}],
}


def _write_corpus(tmp_path):
    facts_path = tmp_path / "facts.yaml"
    crossings_path = tmp_path / "crossings.yaml"
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"

    facts_path.write_text(yaml.safe_dump(FACTS))
    crossings_path.write_text(yaml.safe_dump(CROSSINGS))
    messages_path.write_text(yaml.safe_dump(MESSAGES))
    fixtures_path.write_text(json.dumps(FIXTURES))

    return facts_path, crossings_path, messages_path, fixtures_path


def test_sweep_produces_one_point_per_threshold(tmp_path):
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)

    points = sweep_thresholds(
        facts_path, crossings_path, messages_path, fixtures_path, thresholds=[0.0, 0.5, 1.0]
    )

    assert [p.threshold for p in points] == [0.0, 0.5, 1.0]


def test_sweep_at_threshold_zero_accepts_both_resolutions(tmp_path):
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)

    points = sweep_thresholds(
        facts_path, crossings_path, messages_path, fixtures_path, thresholds=[0.0]
    )
    point = points[0]

    assert point.resolver_recall == 1.0
    assert point.review_share == 0.0
    assert point.verdict_accuracy == 1.0


def test_sweep_thresholds_accepts_an_explicit_resolver(tmp_path):
    """spec §14.2 criterion 2: a different backend must be able to run the
    calibration sweep too, not just embargo eval."""
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)
    explicit_resolver = FakeResolver.from_file(fixtures_path)

    points = sweep_thresholds(
        facts_path, crossings_path, messages_path, fixtures_path,
        thresholds=[0.0], resolver=explicit_resolver,
    )

    assert points[0].resolver_recall == 1.0


def test_sweep_at_threshold_half_routes_low_confidence_to_review(tmp_path):
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)

    points = sweep_thresholds(
        facts_path, crossings_path, messages_path, fixtures_path, thresholds=[0.5]
    )
    point = points[0]

    # M2's 0.3-confidence resolution no longer clears the 0.5 gate.
    assert point.resolver_recall == 0.5
    assert point.review_share == 0.5
    assert point.verdict_accuracy == 0.5


def test_sweep_at_threshold_one_routes_everything_to_review(tmp_path):
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)

    points = sweep_thresholds(
        facts_path, crossings_path, messages_path, fixtures_path, thresholds=[1.0]
    )
    point = points[0]

    assert point.resolver_recall == 0.0
    assert point.review_share == 1.0
    assert point.verdict_accuracy == 0.0


def test_sweep_recall_is_monotonically_non_increasing(tmp_path):
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)

    points = sweep_thresholds(
        facts_path, crossings_path, messages_path, fixtures_path,
        thresholds=[0.0, 0.25, 0.5, 0.75, 1.0],
    )

    recalls = [p.resolver_recall for p in points]
    assert recalls == sorted(recalls, reverse=True)


def test_sweep_review_share_is_monotonically_non_decreasing(tmp_path):
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)

    points = sweep_thresholds(
        facts_path, crossings_path, messages_path, fixtures_path,
        thresholds=[0.0, 0.25, 0.5, 0.75, 1.0],
    )

    shares = [p.review_share for p in points]
    assert shares == sorted(shares)


def test_best_threshold_for_budget_picks_max_recall_within_budget(tmp_path):
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)
    points = sweep_thresholds(
        facts_path, crossings_path, messages_path, fixtures_path, thresholds=[0.0, 0.5, 1.0]
    )

    best = best_threshold_for_budget(points, budget=0.5)

    assert best.threshold == 0.0  # recall 1.0 beats recall 0.5 at threshold 0.5


def test_best_threshold_for_budget_returns_none_when_nothing_fits(tmp_path):
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)
    points = sweep_thresholds(
        facts_path, crossings_path, messages_path, fixtures_path, thresholds=[0.5, 1.0]
    )

    # Nothing has review_share <= -0.1
    assert best_threshold_for_budget(points, budget=-0.1) is None


def test_best_threshold_for_budget_ties_break_toward_lower_threshold(tmp_path):
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)
    points = sweep_thresholds(
        facts_path, crossings_path, messages_path, fixtures_path, thresholds=[0.0, 0.1, 0.2]
    )
    # All three thresholds below 0.3 accept both resolutions -> identical recall (1.0).

    best = best_threshold_for_budget(points, budget=1.0)

    assert best.threshold == 0.0


def test_best_threshold_for_budget_always_picks_the_floor_because_recall_is_monotone(tmp_path):
    """Documents a real, confirmed property (not a bug to fix): recall(t) =
    TP(t) / |expected| is monotone non-increasing in t, and review_share(0.0)
    is always 0.0, so the recall-maximizing threshold under ANY non-negative
    budget is always the smallest threshold in the sweep. The "budget" does
    not bind here -- format_calibration_report must say so explicitly rather
    than presenting this as a genuine trade-off."""
    facts_path, crossings_path, messages_path, fixtures_path = _write_corpus(tmp_path)
    points = sweep_thresholds(
        facts_path, crossings_path, messages_path, fixtures_path,
        thresholds=[0.0, 0.25, 0.5, 0.75, 1.0],
    )

    for budget in (0.0, 0.3, 0.6, 1.0):
        best = best_threshold_for_budget(points, budget=budget)
        assert best.threshold == 0.0


def test_best_threshold_for_accuracy_is_not_always_the_floor(tmp_path):
    """Unlike recall, verdict accuracy is not monotone in threshold -- it
    reflects the decision layer, not just the gate -- so it's a genuinely
    useful second reference point in the report."""
    facts_path = tmp_path / "facts.yaml"
    crossings_path = tmp_path / "crossings.yaml"
    messages_path = tmp_path / "messages.yaml"
    fixtures_path = tmp_path / "fixtures.json"

    facts_path.write_text(yaml.safe_dump(FACTS))
    crossings_path.write_text(yaml.safe_dump(CROSSINGS))
    # A single message the ground truth says should go to review -- at low
    # threshold the low-confidence resolution is accepted and (fully
    # authorized) auto-decided clean, which is wrong; at higher threshold it
    # correctly falls below the gate and routes to review.
    messages_path.write_text(yaml.safe_dump([
        {"message_id": "M3", "sender": "alice", "recipients": ["bob"],
         "timestamp": "2026-06-01T00:00:00", "body": "Acme update, uncertain",
         "expected_verdict": "review", "expected_fact_ids": ["F1"]},
    ]))
    fixtures_path.write_text(json.dumps({
        "M3": [{"fact_id": "F1", "mode": "conveys", "confidence": 0.4, "span": "Acme update, uncertain"}],
    }))

    points = sweep_thresholds(
        facts_path, crossings_path, messages_path, fixtures_path, thresholds=[0.0, 0.5, 1.0]
    )

    best = best_threshold_for_accuracy(points)

    assert best.threshold == 0.5  # ties with 1.0 at accuracy=1.0, breaks toward lower
