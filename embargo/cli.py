import argparse
import dataclasses
import sys
from datetime import datetime
from pathlib import Path

import yaml

from embargo.access import Access
from embargo.decision import decide
from embargo.ledger import Ledger
from embargo.models import Crossing, Fact, FactState, MaterialityLevel, Message, Verdict
from embargo.prefilter import candidate_facts
from embargo.resolver import FakeResolver, Resolver, ResolverOutputInvalid
from embargo.trace import build_resolver_failure_trace, build_trace, read_traces, write_trace

DEFAULT_DB = "embargo.db"
DEFAULT_MESSAGES = "corpus/messages.yaml"
DEFAULT_FIXTURES = "eval/fixtures/resolutions.json"
DEFAULT_TRACE_FILE = "traces/trace.jsonl"
DEFAULT_THRESHOLD = 0.6


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _split_csv(s: str) -> list[str]:
    return [item for item in (part.strip() for part in s.split(",")) if item]


# --- core pipeline (testable without any file I/O) --------------------------


def screen_message(
    message: Message,
    facts: list[Fact],
    crossings: list[Crossing],
    resolver: Resolver,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    as_of_override: datetime | None = None,
    recipients_override: list[str] | None = None,
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
    )
    return record, decision.verdict


# --- YAML loading -------------------------------------------------------------


def load_messages_raw(path: str | Path) -> list[dict]:
    with open(path) as f:
        return yaml.safe_load(f) or []


def message_from_dict(item: dict) -> Message:
    return Message(
        message_id=item["message_id"],
        sender=item["sender"],
        recipients=list(item["recipients"]),
        timestamp=_parse_dt(item["timestamp"]),
        body=item["body"],
    )


# --- ledger commands ----------------------------------------------------------


def cmd_ledger_add(args: argparse.Namespace) -> None:
    ledger = Ledger(args.db)
    recorded_at = _parse_dt(args.recorded_at)
    fact = Fact(
        fact_id=args.id,
        summary=args.summary,
        entities=_split_csv(args.entities),
        aliases=_split_csv(args.aliases),
        state=FactState.PRIVATE,
        recorded_at=recorded_at,
        materiality=[(recorded_at, MaterialityLevel(args.materiality))],
    )
    ledger.add_fact(fact)
    print(f"added fact {fact.fact_id}")


def cmd_ledger_list(args: argparse.Namespace) -> None:
    ledger = Ledger(args.db)
    for fact in ledger.list_facts():
        print(f"{fact.fact_id}\t{fact.state.value}\t{fact.summary}")


def cmd_ledger_show(args: argparse.Namespace) -> None:
    ledger = Ledger(args.db)
    fact = ledger.get_fact(args.id)
    print(f"fact_id: {fact.fact_id}")
    print(f"summary: {fact.summary}")
    print(f"entities: {', '.join(fact.entities)}")
    print(f"aliases: {', '.join(fact.aliases)}")
    print(f"state: {fact.state.value}")
    print(f"recorded_at: {fact.recorded_at.isoformat()}")
    print(f"announced_at: {fact.announced_at.isoformat() if fact.announced_at else ''}")
    print(f"cleared_at: {fact.cleared_at.isoformat() if fact.cleared_at else ''}")
    print("materiality:")
    for effective_from, level in fact.materiality:
        print(f"  {effective_from.isoformat()}: {level.value}")


def cmd_ledger_transition(args: argparse.Namespace) -> None:
    ledger = Ledger(args.db)
    updated = ledger.transition(
        args.id,
        FactState(args.state),
        announced_at=_parse_dt(args.announced_at) if args.announced_at else None,
        cleared_at=_parse_dt(args.cleared_at) if args.cleared_at else None,
        now=_parse_dt(args.now) if args.now else None,
    )
    print(f"{updated.fact_id} -> {updated.state.value}")


# --- cross commands -----------------------------------------------------------


def cmd_cross_add(args: argparse.Namespace) -> None:
    access = Access(args.db)
    crossing = Crossing(
        party_id=args.party,
        fact_id=args.fact,
        effective_from=_parse_dt(args.effective_from),
        effective_until=_parse_dt(args.effective_until) if args.effective_until else None,
    )
    access.add_crossing(crossing)
    print(f"added crossing {crossing.party_id} -> {crossing.fact_id}")


def cmd_cross_list(args: argparse.Namespace) -> None:
    access = Access(args.db)
    for crossing in access.list_crossings():
        until = crossing.effective_until.isoformat() if crossing.effective_until else "open-ended"
        print(f"{crossing.party_id}\t{crossing.fact_id}\t{crossing.effective_from.isoformat()}\t{until}")


# --- screen command -------------------------------------------------------------


def cmd_screen(args: argparse.Namespace) -> None:
    ledger = Ledger(args.db)
    access = Access(args.db)

    messages = {item["message_id"]: message_from_dict(item) for item in load_messages_raw(args.messages)}
    if args.message_id not in messages:
        print(f"no such message: {args.message_id}", file=sys.stderr)
        sys.exit(1)
    original = messages[args.message_id]

    as_of = _parse_dt(args.as_of) if args.as_of else None
    recipients_override = _split_csv(args.recipients) if args.recipients else None

    effective = dataclasses.replace(
        original,
        timestamp=as_of or original.timestamp,
        recipients=recipients_override or original.recipients,
    )

    resolver = FakeResolver.from_file(args.fixtures)
    record, verdict = screen_message(
        effective,
        ledger.list_facts(),
        access.list_crossings(),
        resolver,
        threshold=args.threshold,
        as_of_override=as_of,
        recipients_override=recipients_override,
    )

    Path(args.trace_file).parent.mkdir(parents=True, exist_ok=True)
    write_trace(args.trace_file, record)
    print(verdict.value)


# --- trace command --------------------------------------------------------------


def cmd_trace_show(args: argparse.Namespace) -> None:
    records = read_traces(args.trace_file, message_id=args.message_id)
    if not records:
        print(f"no trace records for {args.message_id}")
        return
    for i, record in enumerate(records):
        print(f"--- screening {i + 1} of {len(records)} ---")
        print(f"verdict: {record['verdict']}" + (f" ({record['reason']})" if record["reason"] else ""))
        print(f"as_of_override: {record['as_of_override']}")
        print(f"recipients_override: {record['recipients_override']}")
        print(f"candidates: {record['candidates']}")
        print(f"fact_results: {record['fact_results']}")


# --- eval command ---------------------------------------------------------------


def cmd_eval(args: argparse.Namespace) -> None:
    from eval.run_eval import format_report, run_eval

    report = run_eval(args.facts, args.crossings, args.messages, args.fixtures, threshold=args.threshold)
    print(format_report(report))


# --- argparse wiring --------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="embargo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ledger_parser = subparsers.add_parser("ledger")
    ledger_sub = ledger_parser.add_subparsers(dest="ledger_command", required=True)

    add_parser = ledger_sub.add_parser("add")
    add_parser.add_argument("--id", required=True)
    add_parser.add_argument("--summary", required=True)
    add_parser.add_argument("--entities", default="")
    add_parser.add_argument("--aliases", default="")
    add_parser.add_argument("--recorded-at", required=True)
    add_parser.add_argument("--materiality", default="none")
    add_parser.add_argument("--db", default=DEFAULT_DB)
    add_parser.set_defaults(func=cmd_ledger_add)

    list_parser = ledger_sub.add_parser("list")
    list_parser.add_argument("--db", default=DEFAULT_DB)
    list_parser.set_defaults(func=cmd_ledger_list)

    show_parser = ledger_sub.add_parser("show")
    show_parser.add_argument("id")
    show_parser.add_argument("--db", default=DEFAULT_DB)
    show_parser.set_defaults(func=cmd_ledger_show)

    transition_parser = ledger_sub.add_parser("transition")
    transition_parser.add_argument("id")
    transition_parser.add_argument("state", choices=["announced", "abandoned", "cleared"])
    transition_parser.add_argument("--announced-at")
    transition_parser.add_argument("--cleared-at")
    transition_parser.add_argument("--now")
    transition_parser.add_argument("--db", default=DEFAULT_DB)
    transition_parser.set_defaults(func=cmd_ledger_transition)

    cross_parser = subparsers.add_parser("cross")
    cross_sub = cross_parser.add_subparsers(dest="cross_command", required=True)

    cross_add_parser = cross_sub.add_parser("add")
    cross_add_parser.add_argument("--party", required=True)
    cross_add_parser.add_argument("--fact", required=True)
    cross_add_parser.add_argument("--effective-from", required=True)
    cross_add_parser.add_argument("--effective-until")
    cross_add_parser.add_argument("--db", default=DEFAULT_DB)
    cross_add_parser.set_defaults(func=cmd_cross_add)

    cross_list_parser = cross_sub.add_parser("list")
    cross_list_parser.add_argument("--db", default=DEFAULT_DB)
    cross_list_parser.set_defaults(func=cmd_cross_list)

    screen_parser = subparsers.add_parser("screen")
    screen_parser.add_argument("--message", required=True, dest="message_id")
    screen_parser.add_argument("--as-of")
    screen_parser.add_argument("--recipients")
    screen_parser.add_argument("--db", default=DEFAULT_DB)
    screen_parser.add_argument("--messages", default=DEFAULT_MESSAGES)
    screen_parser.add_argument("--fixtures", default=DEFAULT_FIXTURES)
    screen_parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    screen_parser.add_argument("--trace-file", default=DEFAULT_TRACE_FILE)
    screen_parser.set_defaults(func=cmd_screen)

    eval_parser = subparsers.add_parser("eval")
    eval_parser.add_argument("--facts", default="corpus/facts.yaml")
    eval_parser.add_argument("--crossings", default="corpus/crossings.yaml")
    eval_parser.add_argument("--messages", default="corpus/messages.yaml")
    eval_parser.add_argument("--fixtures", default=DEFAULT_FIXTURES)
    eval_parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    eval_parser.set_defaults(func=cmd_eval)

    trace_parser = subparsers.add_parser("trace")
    trace_sub = trace_parser.add_subparsers(dest="trace_command", required=True)
    trace_show_parser = trace_sub.add_parser("show")
    trace_show_parser.add_argument("message_id")
    trace_show_parser.add_argument("--trace-file", default=DEFAULT_TRACE_FILE)
    trace_show_parser.set_defaults(func=cmd_trace_show)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
