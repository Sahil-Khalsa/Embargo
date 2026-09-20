"""Optional HTTP endpoint (spec §14.4): accepts one message, returns a
verdict plus trace id, for wiring into a real message pipeline. Goes
through embargo.pipeline.screen_and_write -- the exact same code path the
CLI's --message and --batch screening use, not a reimplementation, so
spec §14.5 criterion 4 (byte-identical traces) holds across all three."""

import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from embargo.access import Access
from embargo.backends import build_resolver
from embargo.config import Config, DEFAULT_THRESHOLD
from embargo.ledger import Ledger
from embargo.models import Message
from embargo.pipeline import screen_and_write

_REQUIRED_FIELDS = ("message_id", "sender", "recipients", "timestamp", "body")


def _message_from_json(payload: dict) -> Message:
    missing = [f for f in _REQUIRED_FIELDS if f not in payload]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")
    return Message(
        message_id=payload["message_id"],
        sender=payload["sender"],
        recipients=list(payload["recipients"]),
        timestamp=datetime.fromisoformat(payload["timestamp"]),
        body=payload["body"],
    )


def make_handler(db_path, trace_file, fixtures_path, config: Config, threshold: float):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            if self.path != "/screen":
                self.send_error(404)
                return

            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw)
                message = _message_from_json(payload)
            except (json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
                self._respond_json({"error": str(e)}, status=400)
                return

            ledger = Ledger(db_path)
            access = Access(db_path)
            resolver = build_resolver(config, fixtures_path=fixtures_path)

            record, verdict = screen_and_write(
                message,
                ledger.list_facts(),
                access.list_crossings(),
                resolver,
                threshold=threshold,
                trace_file=trace_file,
                ledger_version=ledger.current_version(),
            )

            self._respond_json({"verdict": verdict.value, "trace_id": record["trace_id"]})

        def _respond_json(self, payload: dict, status: int = 200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve(
    db_path,
    trace_file,
    fixtures_path,
    *,
    config: Config | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    host: str = "127.0.0.1",
    port: int = 8001,
) -> HTTPServer:
    """Builds and returns a bound HTTPServer; caller decides how to run it
    (serve_forever() for the CLI, a background thread for tests)."""
    if config is None:
        config = Config()
    handler = make_handler(db_path, trace_file, fixtures_path, config, threshold)
    return HTTPServer((host, port), handler)
