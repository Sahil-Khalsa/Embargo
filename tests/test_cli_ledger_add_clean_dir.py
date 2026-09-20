"""Regression test for a real bug found running the README demo verbatim in
a genuinely clean directory: `ledger add` crashed with FileNotFoundError on
its default --fixtures path, even though there was no trace file at all to
rescreen -- the auto-rescreen side effect was unconditionally requiring a
fixtures file to exist, regardless of whether there was any work to do."""

from embargo.cli import main


def test_ledger_add_does_not_require_fixtures_when_no_trace_file_exists(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "demo.db")

    # No --fixtures, no --trace-file, no such files anywhere on disk --
    # this must not crash just because ledger add always checks for
    # rescreening work.
    main(["ledger", "add", "--id", "F001", "--summary", "Acme deal",
          "--entities", "Acme", "--recorded-at", "2026-01-01T00:00:00",
          "--materiality", "high", "--db", db])
    out = capsys.readouterr().out

    assert "added fact F001" in out
