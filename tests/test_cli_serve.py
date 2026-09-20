from unittest.mock import MagicMock, patch

from embargo.cli import main


def _run(tmp_path, extra=(), config_args=()):
    fake_server = MagicMock()
    fake_server.serve_forever.side_effect = KeyboardInterrupt()  # as Ctrl+C would
    with patch("embargo.screen_server.serve", return_value=fake_server) as mock_serve:
        main([*config_args, "serve", "--db", str(tmp_path / "e.db"),
              "--trace-file", str(tmp_path / "t.jsonl"),
              "--fixtures", str(tmp_path / "f.json"), *extra])
    return mock_serve, fake_server


def test_serve_command_starts_the_screening_endpoint_on_localhost_8001_by_default(tmp_path):
    mock_serve, fake_server = _run(tmp_path)

    _args, kwargs = mock_serve.call_args
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8001
    fake_server.serve_forever.assert_called_once()
    fake_server.server_close.assert_called_once()


def test_serve_command_passes_host_port_and_configured_threshold_and_backend(tmp_path):
    config_path = tmp_path / "embargo.toml"
    config_path.write_text('threshold = 0.85\nbackend = "fake"\n')

    mock_serve, _ = _run(
        tmp_path, extra=["--host", "0.0.0.0", "--port", "9002"],
        config_args=["--config", str(config_path)],
    )

    _args, kwargs = mock_serve.call_args
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 9002
    assert kwargs["threshold"] == 0.85
    assert kwargs["config"].backend == "fake"
