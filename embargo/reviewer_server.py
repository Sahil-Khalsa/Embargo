"""Local reviewer web UI (spec §14.3): stdlib http.server only, per the
user's explicit choice over adding a framework -- consistent with the
zero-framework discipline the rest of the stack keeps."""

import html
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from embargo.access import Access
from embargo.ledger import Ledger
from embargo.reviewer import build_evidence_chain, build_queue, record_reviewer_action
from embargo.trace import read_traces, verify_chain

_STYLE = (
    "<style>body{font-family:sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem}"
    "table{border-collapse:collapse;margin:.5rem 0}td,th{border:1px solid #ccc;padding:.25rem .6rem;"
    "text-align:left}mark{background:#ffe066}pre{background:#f5f5f5;padding:.6rem;white-space:pre-wrap}"
    ".bad{color:#b00020;font-weight:bold}.ok{color:#1b6e20}</style>"
)


def _page(title: str, body: str) -> bytes:
    return (
        f"<!doctype html><html><head><meta charset=\"utf-8\"><title>{html.escape(title)}</title>"
        f"{_STYLE}</head><body>{body}</body></html>"
    ).encode("utf-8")


def highlight_spans(body: str, spans: list[str]) -> str:
    """HTML-escaped `body` with the first occurrence of each span wrapped in
    <mark>. Overlapping/adjacent matches are merged; spans not found are
    ignored (the resolver validates spans are verbatim, but this must not
    crash on a hand-edited trace)."""
    ranges = []
    for span in spans:
        start = body.find(span) if span else -1
        if start != -1:
            ranges.append((start, start + len(span)))
    ranges.sort()

    merged: list[list[int]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    out = []
    cursor = 0
    for start, end in merged:
        out.append(html.escape(body[cursor:start]))
        out.append(f"<mark>{html.escape(body[start:end])}</mark>")
        cursor = end
    out.append(html.escape(body[cursor:]))
    return "".join(out)


def _row(label: str, value, css: str = "") -> str:
    cls = f' class="{css}"' if css else ""
    return f"<tr><th>{html.escape(label)}</th><td{cls}>{html.escape(str(value))}</td></tr>"


def _bool_cell(label: str, value: bool) -> str:
    return _row(label, value, "ok" if value else "bad")


def _render_fact_result(fact_result: dict) -> str:
    """One resolved fact: what the model said, then every deterministic
    check in the order decision.py applies them, each with its result --
    so a reviewer can tell a model error from a ledger fact."""
    rows = [
        _row("resolver mode", fact_result["mode"]),
        _row("resolver confidence", fact_result["confidence"]),
        _row("resolver span", fact_result["span"]),
        _row("passed the confidence gate", fact_result["proceeded"]),
    ]
    if fact_result.get("reason"):
        rows.append(_row("gate reason", fact_result["reason"]))

    checks = fact_result.get("checks")
    if checks:
        rows.append(_row("is_cleared", checks["is_cleared"]))
        rows.append(_row("materiality", checks["materiality"]))
        rows.append(_bool_cell("sender_authorized", checks["sender_authorized"]))
        for party, ok in checks["recipient_authorized"].items():
            rows.append(_bool_cell(f"recipient_authorized[{party}]", ok))
    rows.append(_row("per-fact verdict", fact_result.get("verdict") or "(none: did not proceed)"))

    return (
        f"<h3>Fact {html.escape(fact_result['fact_id'])}</h3><table>{''.join(rows)}</table>"
    )


def _render_fact_timeline(fact: dict) -> str:
    rows = [
        _row("state", fact["state"]),
        _row("recorded_at", fact["recorded_at"]),
        _row("announced_at", fact["announced_at"] or "-"),
        _row("cleared_at", fact["cleared_at"] or "-"),
    ]
    series = "".join(
        f"<li>{html.escape(m['effective_from'])}: {html.escape(m['level'])}</li>"
        for m in fact["materiality"]
    )
    return (
        f"<h3>{html.escape(fact['fact_id'])}: {html.escape(fact['summary'])}</h3>"
        f"<table>{''.join(rows)}</table><p>materiality series:</p><ul>{series}</ul>"
    )


def make_handler(trace_path, db_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # keep test/server output quiet; not a diagnostic tool

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._serve_queue()
            elif parsed.path.startswith("/finding/"):
                self._serve_finding(parsed.path[len("/finding/"):])
            elif parsed.path == "/trace":
                self._serve_trace_viewer()
            else:
                self.send_error(404)

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path.startswith("/finding/") and parsed.path.endswith("/action"):
                trace_id = parsed.path[len("/finding/"):-len("/action")]
                self._handle_action(trace_id)
            else:
                self.send_error(404)

        def _serve_queue(self):
            queue = build_queue(trace_path)
            rows = "".join(
                f"<tr><td>{html.escape(r['verdict'])}</td><td>{html.escape(r['message_id'])}</td>"
                f"<td><a href=\"/finding/{r['trace_id']}\">{r['trace_id'][:12]}</a></td></tr>"
                for r in queue
            )
            body = (
                "<h1>Review queue</h1><p>Most severe first.</p>"
                f"<table><tr><th>verdict</th><th>message</th><th>finding</th></tr>{rows}</table>"
                "<p><a href=\"/trace\">Trace viewer</a></p>"
            )
            self._respond(_page("Review queue", body))

        def _serve_finding(self, trace_id):
            ledger = Ledger(db_path)
            access = Access(db_path)
            try:
                chain = build_evidence_chain(trace_path, ledger, access, trace_id)
            except KeyError:
                self.send_error(404)
                return

            screening = chain["screening"]
            spans = [fr["span"] for fr in screening["fact_results"]]
            recipients = screening["recipients_override"] or screening["recipients"]

            candidates_html = "".join(
                f"<tr><td>{html.escape(c['fact_id'])}</td>"
                f"<td>{html.escape(', '.join(c['reasons']))}</td></tr>"
                for c in screening["candidates"]
            )
            results_html = "".join(_render_fact_result(fr) for fr in screening["fact_results"])
            facts_html = "".join(_render_fact_timeline(f) for f in chain["facts"])
            auth_html = "".join(
                f"<li>{html.escape(party)}: "
                + ("<span class=\"ok\">authorized</span>" if ok else "<span class=\"bad\">NOT authorized</span>")
                + "</li>"
                for party, ok in chain["authorization"].items()
            )
            actions_html = "".join(
                f"<li>{html.escape(a['action'])} by {html.escape(a['reviewer'])} at {html.escape(a['at'])}"
                + (f" -- {html.escape(a['reason'])}" if a.get("reason") else "")
                + "</li>"
                for a in chain["reviewer_actions"]
            )
            body = (
                f"<h1>Finding {html.escape(trace_id[:12])}</h1>"
                f"<p><b>verdict:</b> {html.escape(screening['verdict'])}"
                + (f" ({html.escape(screening['reason'])})" if screening.get("reason") else "")
                + "</p>"
                f"<p><b>message</b> {html.escape(screening['message_id'])} from "
                f"{html.escape(screening['sender'])} to {html.escape(', '.join(recipients))} "
                f"at {html.escape(screening['as_of_override'] or screening['timestamp'])}</p>"
                f"<pre>{highlight_spans(screening['body'], spans)}</pre>"
                f"<h2>Resolver</h2><table>"
                f"{_row('backend', screening.get('backend', 'unknown'))}"
                f"{_row('model_version', screening.get('model_version', 'unknown'))}"
                f"{_row('ledger_version', screening['ledger_version'])}</table>"
                f"<h2>Candidates (what surfaced each fact)</h2>"
                f"<table><tr><th>fact</th><th>reasons</th></tr>{candidates_html}</table>"
                f"<h2>Resolutions and checks</h2>{results_html or '<p>none</p>'}"
                f"<h2>Facts and timeline</h2>{facts_html or '<p>none</p>'}"
                f"<h2>Authorization lookup</h2><ul>{auth_html}</ul>"
                f"<h2>Reviewer actions</h2><ul>{actions_html}</ul>"
                f"<form method=\"post\" action=\"/finding/{html.escape(trace_id)}/action\">"
                "<input name=\"reviewer\" placeholder=\"your name\" required> "
                "<select name=\"action\"><option>confirm</option><option>dismiss</option>"
                "<option>escalate</option></select> "
                "<input name=\"reason\" placeholder=\"reason (for dismiss)\"> "
                "<button type=\"submit\">Submit</button></form>"
                "<p><a href=\"/\">Back to queue</a></p>"
            )
            self._respond(_page(f"Finding {trace_id[:12]}", body))

        def _handle_action(self, trace_id):
            length = int(self.headers.get("Content-Length", 0))
            fields = parse_qs(self.rfile.read(length).decode("utf-8"))
            reviewer = fields.get("reviewer", [""])[0]
            action = fields.get("action", [""])[0]
            reason = fields.get("reason", [None])[0] or None

            try:
                record_reviewer_action(trace_path, trace_id, action, reviewer=reviewer, reason=reason)
            except (KeyError, ValueError) as e:
                self.send_error(400, str(e))
                return

            self.send_response(303)
            self.send_header("Location", f"/finding/{trace_id}")
            self.end_headers()

        def _serve_trace_viewer(self):
            result = verify_chain(trace_path)
            status = "chain intact" if result.ok else f"chain broken at line {result.broken_at_line}"
            rows = []
            for line_no, record in enumerate(read_traces(trace_path), start=1):
                record_type = record.get("record_type", "screening")
                detail = record.get("verdict") if record_type == "screening" else (
                    f"{record.get('action')} by {record.get('reviewer')}"
                )
                rows.append(
                    f"<tr><td>{line_no}</td><td>{html.escape(record_type)}</td>"
                    f"<td>{html.escape(record['message_id'])}</td>"
                    f"<td>{html.escape(str(detail))}</td>"
                    f"<td>{html.escape(record['trace_id'][:12])}</td>"
                    f"<td>{html.escape((record.get('prev_hash') or '-')[:12])}</td></tr>"
                )
            body = (
                f"<h1>Trace viewer</h1><p>{html.escape(status)}</p>"
                "<table><tr><th>line</th><th>type</th><th>message</th><th>verdict / action</th>"
                f"<th>trace_id</th><th>prev_hash</th></tr>{''.join(rows)}</table>"
                "<p><a href=\"/\">Back to queue</a></p>"
            )
            self._respond(_page("Trace viewer", body))

        def _respond(self, content: bytes, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    return Handler


def serve(trace_path, db_path, *, host: str = "127.0.0.1", port: int = 8000) -> HTTPServer:
    """Builds and returns a bound HTTPServer; caller decides how to run it
    (serve_forever() for the CLI, a background thread for tests)."""
    return HTTPServer((host, port), make_handler(trace_path, db_path))
