import argparse
import dataclasses
import sys
from datetime import datetime
from pathlib import Path

import yaml

from embargo.access import Access
from embargo.backends import build_resolver
from embargo.config import load_config
from embargo.ledger import Ledger
from embargo.models import Crossing, Fact, FactState, MaterialityLevel, Message
from embargo.pipeline import DEFAULT_THRESHOLD, screen_and_write
from embargo.rescreen import rescreen_stale_traces
from embargo.trace import read_traces, verify_chain, write_trace

DEFAULT_DB = "embargo.db"
DEFAULT_MESSAGES = "corpus/messages.yaml"
DEFAULT_FIXTURES = "eval/fixtures/resolutions.json"
DEFAULT_TRACE_FILE = "traces/trace.jsonl"


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _split_csv(s: str) -> list[str]:
    return [item for item in (part.strip() for part in s.split(",")) if item]


def _resolve_threshold(args: argparse.Namespace) -> float:
    return args.threshold if args.threshold is not None else args.config_obj.threshold


def _resolve_db(args: argparse.Namespace) -> str:
    return args.db if args.db is not None else args.config_obj.db_path


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
    db = _resolve_db(args)
    ledger = Ledger(db)
    access = Access(db)
    recorded_at = _parse_dt(args.recorded_at)
    valid_from = _parse_dt(args.valid_from) if args.valid_from else recorded_at
    fact = Fact(
        fact_id=args.id,
        summary=args.summary,
        entities=_split_csv(args.entities),
        aliases=_split_csv(args.aliases),
        state=FactState.PRIVATE,
        recorded_at=recorded_at,
        # Materiality is anchored at valid_from, not recorded_at: for a
        # backdated fact, the level applied when the fact became true, not
        # merely when the ledger learned about it -- otherwise messages sent
        # between valid_from and recorded_at have no materiality to look up.
        materiality=[(valid_from, MaterialityLevel(args.materiality))],
        valid_from=valid_from,
    )
    ledger.add_fact(fact)
    version_at_entry = ledger.current_version()
    print(f"added fact {fact.fact_id} (ledger version {version_at_entry})")

    # Auto-rescreen (spec §13.1): any current trace older than this entry,
    # for a message sent at or after this fact's valid_from, may now resolve
    # differently. Skipped entirely (not merely a no-op) when there's no
    # trace file yet -- a brand-new ledger add must not require a fixtures
    # file to exist just to check for rescreening work that can't exist.
    if not Path(args.trace_file).exists():
        return
    resolver = build_resolver(args.config_obj, fixtures_path=args.fixtures)
    changes = rescreen_stale_traces(
        args.trace_file,
        ledger.list_facts(),
        access.list_crossings(),
        resolver,
        max_version=version_at_entry,
        current_version=version_at_entry,
        timestamp_from=fact.valid_from,
    )
    if changes:
        print(f"re-screened {len(changes)} message(s) with changed verdicts:")
        for change in changes:
            print(f"  {change.message_id}: {change.old_verdict} -> {change.new_verdict}")


def cmd_ledger_list(args: argparse.Namespace) -> None:
    ledger = Ledger(_resolve_db(args))
    for fact in ledger.list_facts():
        print(f"{fact.fact_id}\t{fact.state.value}\t{fact.summary}")


def cmd_ledger_show(args: argparse.Namespace) -> None:
    ledger = Ledger(_resolve_db(args))
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
    ledger = Ledger(_resolve_db(args))
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
    access = Access(_resolve_db(args))
    crossing = Crossing(
        party_id=args.party,
        fact_id=args.fact,
        effective_from=_parse_dt(args.effective_from),
        effective_until=_parse_dt(args.effective_until) if args.effective_until else None,
    )
    access.add_crossing(crossing)
    print(f"added crossing {crossing.party_id} -> {crossing.fact_id}")


def cmd_cross_list(args: argparse.Namespace) -> None:
    access = Access(_resolve_db(args))
    for crossing in access.list_crossings():
        until = crossing.effective_until.isoformat() if crossing.effective_until else "open-ended"
        print(f"{crossing.party_id}\t{crossing.fact_id}\t{crossing.effective_from.isoformat()}\t{until}")


# --- screen command -------------------------------------------------------------


def _screen_and_write(message, ledger, access, resolver, threshold, trace_file, **screen_kwargs):
    # Thin adapter: the actual screen_message()+write_trace() pairing lives
    # in embargo.pipeline.screen_and_write, the one place every screening
    # entry point (CLI here, the HTTP endpoint) goes through -- spec §14.4.
    return screen_and_write(
        message,
        ledger.list_facts(),
        access.list_crossings(),
        resolver,
        threshold=threshold,
        trace_file=trace_file,
        ledger_version=ledger.current_version(),
        **screen_kwargs,
    )


def cmd_screen(args: argparse.Namespace) -> None:
    if bool(args.message_id) == bool(args.batch):
        print("specify exactly one of --message or --batch", file=sys.stderr)
        sys.exit(2)

    db = _resolve_db(args)
    ledger = Ledger(db)
    access = Access(db)
    resolver = build_resolver(args.config_obj, fixtures_path=args.fixtures)
    threshold = _resolve_threshold(args)

    if args.batch:
        messages = [message_from_dict(item) for item in load_messages_raw(args.batch)]
        counts: dict[str, int] = {}
        for message in messages:
            _record, verdict = _screen_and_write(message, ledger, access, resolver, threshold, args.trace_file)
            counts[verdict.value] = counts.get(verdict.value, 0) + 1
        print(f"screened {len(messages)} message(s):")
        for verdict_name, count in sorted(counts.items()):
            print(f"  {verdict_name}: {count}")
        return

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

    _record, verdict = _screen_and_write(
        effective, ledger, access, resolver, threshold, args.trace_file,
        as_of_override=as_of, recipients_override=recipients_override,
    )
    print(verdict.value)


# --- rescreen command ------------------------------------------------------------


def cmd_rescreen(args: argparse.Namespace) -> None:
    db = _resolve_db(args)
    ledger = Ledger(db)
    access = Access(db)
    resolver = build_resolver(args.config_obj, fixtures_path=args.fixtures)

    changes = rescreen_stale_traces(
        args.trace_file,
        ledger.list_facts(),
        access.list_crossings(),
        resolver,
        max_version=args.since,
        current_version=ledger.current_version(),
        threshold=_resolve_threshold(args),
    )
    if not changes:
        print("no verdicts changed")
        return
    print(f"{len(changes)} verdict(s) changed:")
    for change in changes:
        print(f"  {change.message_id}: {change.old_verdict} -> {change.new_verdict}")


# --- trace command --------------------------------------------------------------


def cmd_trace_show(args: argparse.Namespace) -> None:
    records = read_traces(args.trace_file, message_id=args.message_id)
    if not records:
        print(f"no trace records for {args.message_id}")
        return
    # Old (pre-§14.3) records have no record_type and are screenings.
    screenings = [r for r in records if r.get("record_type", "screening") == "screening"]
    actions = [r for r in records if r.get("record_type") == "reviewer_action"]
    for i, record in enumerate(screenings):
        print(f"--- screening {i + 1} of {len(screenings)} ---")
        print(f"verdict: {record['verdict']}" + (f" ({record['reason']})" if record["reason"] else ""))
        print(f"as_of_override: {record['as_of_override']}")
        print(f"recipients_override: {record['recipients_override']}")
        print(f"candidates: {record['candidates']}")
        print(f"fact_results: {record['fact_results']}")
    for action in actions:
        line = f"reviewer action: {action['action']} by {action['reviewer']} at {action['at']}"
        if action.get("reason"):
            line += f" -- {action['reason']}"
        print(line)


def cmd_trace_verify(args: argparse.Namespace) -> None:
    result = verify_chain(args.trace_file)
    if result.ok:
        print("chain intact")
    else:
        print(f"chain broken at line {result.broken_at_line}")


# --- review command (spec §14.3) -------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> None:
    from embargo.screen_server import serve

    server = serve(
        _resolve_db(args),
        args.trace_file,
        args.fixtures,
        config=args.config_obj,
        threshold=_resolve_threshold(args),
        host=args.host,
        port=args.port,
    )
    print(f"screening endpoint listening on http://{args.host}:{args.port}/screen (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def cmd_review(args: argparse.Namespace) -> None:
    from embargo.reviewer_server import serve

    db = _resolve_db(args)
    server = serve(args.trace_file, db, host=args.host, port=args.port)
    print(f"reviewer UI listening on http://{args.host}:{args.port}/ (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# --- eval command ---------------------------------------------------------------


def cmd_eval(args: argparse.Namespace) -> None:
    from eval.run_eval import format_report, run_eval

    if args.adversarial:
        facts = args.facts or "corpus/adversarial/facts.yaml"
        crossings = args.crossings or "corpus/adversarial/crossings.yaml"
        messages = args.messages or "corpus/adversarial/messages.yaml"
        fixtures = args.fixtures or "eval/fixtures/adversarial.json"
    else:
        facts = args.facts or "corpus/facts.yaml"
        crossings = args.crossings or "corpus/crossings.yaml"
        messages = args.messages or "corpus/messages.yaml"
        fixtures = args.fixtures or DEFAULT_FIXTURES

    resolver = build_resolver(args.config_obj, fixtures_path=fixtures)
    report = run_eval(facts, crossings, messages, fixtures, threshold=_resolve_threshold(args), resolver=resolver)
    print(format_report(report))


# --- calibrate command ------------------------------------------------------------


def cmd_calibrate(args: argparse.Namespace) -> None:
    from eval.calibrate import format_calibration_report, sweep_thresholds

    resolver = build_resolver(args.config_obj, fixtures_path=args.fixtures)
    points = sweep_thresholds(args.facts, args.crossings, args.messages, args.fixtures, resolver=resolver)
    print(format_calibration_report(points, budget=args.budget))


# --- argparse wiring --------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="embargo")
    parser.add_argument("--config", default=None, help="path to a TOML config file (spec 14.1)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ledger_parser = subparsers.add_parser("ledger")
    ledger_sub = ledger_parser.add_subparsers(dest="ledger_command", required=True)

    add_parser = ledger_sub.add_parser("add")
    add_parser.add_argument("--id", required=True)
    add_parser.add_argument("--summary", required=True)
    add_parser.add_argument("--entities", default="")
    add_parser.add_argument("--aliases", default="")
    add_parser.add_argument("--recorded-at", required=True)
    add_parser.add_argument("--valid-from")
    add_parser.add_argument("--materiality", default="none")
    add_parser.add_argument("--db", default=None)
    add_parser.add_argument("--trace-file", default=DEFAULT_TRACE_FILE)
    add_parser.add_argument("--fixtures", default=DEFAULT_FIXTURES)
    add_parser.set_defaults(func=cmd_ledger_add)

    list_parser = ledger_sub.add_parser("list")
    list_parser.add_argument("--db", default=None)
    list_parser.set_defaults(func=cmd_ledger_list)

    show_parser = ledger_sub.add_parser("show")
    show_parser.add_argument("id")
    show_parser.add_argument("--db", default=None)
    show_parser.set_defaults(func=cmd_ledger_show)

    transition_parser = ledger_sub.add_parser("transition")
    transition_parser.add_argument("id")
    transition_parser.add_argument("state", choices=["announced", "abandoned", "cleared"])
    transition_parser.add_argument("--announced-at")
    transition_parser.add_argument("--cleared-at")
    transition_parser.add_argument("--now")
    transition_parser.add_argument("--db", default=None)
    transition_parser.set_defaults(func=cmd_ledger_transition)

    cross_parser = subparsers.add_parser("cross")
    cross_sub = cross_parser.add_subparsers(dest="cross_command", required=True)

    cross_add_parser = cross_sub.add_parser("add")
    cross_add_parser.add_argument("--party", required=True)
    cross_add_parser.add_argument("--fact", required=True)
    cross_add_parser.add_argument("--effective-from", required=True)
    cross_add_parser.add_argument("--effective-until")
    cross_add_parser.add_argument("--db", default=None)
    cross_add_parser.set_defaults(func=cmd_cross_add)

    cross_list_parser = cross_sub.add_parser("list")
    cross_list_parser.add_argument("--db", default=None)
    cross_list_parser.set_defaults(func=cmd_cross_list)

    screen_parser = subparsers.add_parser("screen")
    screen_parser.add_argument("--message", dest="message_id", default=None)
    screen_parser.add_argument("--batch", default=None, help="bulk-screen every message in this file")
    screen_parser.add_argument("--as-of")
    screen_parser.add_argument("--recipients")
    screen_parser.add_argument("--db", default=None)
    screen_parser.add_argument("--messages", default=DEFAULT_MESSAGES)
    screen_parser.add_argument("--fixtures", default=DEFAULT_FIXTURES)
    screen_parser.add_argument("--threshold", type=float, default=None)
    screen_parser.add_argument("--trace-file", default=DEFAULT_TRACE_FILE)
    screen_parser.set_defaults(func=cmd_screen)

    eval_parser = subparsers.add_parser("eval")
    eval_parser.add_argument("--facts", default=None)
    eval_parser.add_argument("--crossings", default=None)
    eval_parser.add_argument("--messages", default=None)
    eval_parser.add_argument("--fixtures", default=None)
    eval_parser.add_argument("--adversarial", action="store_true")
    eval_parser.add_argument("--threshold", type=float, default=None)
    eval_parser.set_defaults(func=cmd_eval)

    calibrate_parser = subparsers.add_parser("calibrate")
    calibrate_parser.add_argument("--facts", default="corpus/facts.yaml")
    calibrate_parser.add_argument("--crossings", default="corpus/crossings.yaml")
    calibrate_parser.add_argument("--messages", default="corpus/messages.yaml")
    calibrate_parser.add_argument("--fixtures", default=DEFAULT_FIXTURES)
    calibrate_parser.add_argument("--budget", type=float, default=None)
    calibrate_parser.set_defaults(func=cmd_calibrate)

    rescreen_parser = subparsers.add_parser("rescreen")
    rescreen_parser.add_argument("--since", type=int, required=True)
    rescreen_parser.add_argument("--db", default=None)
    rescreen_parser.add_argument("--trace-file", default=DEFAULT_TRACE_FILE)
    rescreen_parser.add_argument("--fixtures", default=DEFAULT_FIXTURES)
    rescreen_parser.add_argument("--threshold", type=float, default=None)
    rescreen_parser.set_defaults(func=cmd_rescreen)

    trace_parser = subparsers.add_parser("trace")
    trace_sub = trace_parser.add_subparsers(dest="trace_command", required=True)
    trace_show_parser = trace_sub.add_parser("show")
    trace_show_parser.add_argument("message_id")
    trace_show_parser.add_argument("--trace-file", default=DEFAULT_TRACE_FILE)
    trace_show_parser.set_defaults(func=cmd_trace_show)

    trace_verify_parser = trace_sub.add_parser("verify")
    trace_verify_parser.add_argument("--trace-file", default=DEFAULT_TRACE_FILE)
    trace_verify_parser.set_defaults(func=cmd_trace_verify)

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--db", default=None)
    serve_parser.add_argument("--trace-file", default=DEFAULT_TRACE_FILE)
    serve_parser.add_argument("--fixtures", default=DEFAULT_FIXTURES)
    serve_parser.add_argument("--threshold", type=float, default=None)
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8001)
    serve_parser.set_defaults(func=cmd_serve)

    review_parser = subparsers.add_parser("review")
    review_parser.add_argument("--db", default=None)
    review_parser.add_argument("--trace-file", default=DEFAULT_TRACE_FILE)
    review_parser.add_argument("--host", default="127.0.0.1")
    review_parser.add_argument("--port", type=int, default=8000)
    review_parser.set_defaults(func=cmd_review)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.config_obj = load_config(args.config)
    args.func(args)


if __name__ == "__main__":
    main()
