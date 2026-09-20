from unittest.mock import MagicMock, patch

from embargo.cli import main


def test_review_command_starts_server_with_configured_host_and_port(tmp_path):
    fake_server = MagicMock()
    fake_server.serve_forever.side_effect = KeyboardInterrupt()  # stop immediately, as Ctrl+C would

    with patch("embargo.reviewer_server.serve", return_value=fake_server) as mock_serve:
        main(["review", "--db", str(tmp_path / "e.db"), "--trace-file", str(tmp_path / "t.jsonl"),
              "--host", "0.0.0.0", "--port", "9001"])

    args, kwargs = mock_serve.call_args
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 9001
    fake_server.serve_forever.assert_called_once()
    fake_server.server_close.assert_called_once()


def test_review_command_defaults_to_localhost_port_8000(tmp_path):
    fake_server = MagicMock()
    fake_server.serve_forever.side_effect = KeyboardInterrupt()

    with patch("embargo.reviewer_server.serve", return_value=fake_server) as mock_serve:
        main(["review", "--db", str(tmp_path / "e.db"), "--trace-file", str(tmp_path / "t.jsonl")])

    args, kwargs = mock_serve.call_args
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8000
