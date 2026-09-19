from pathlib import Path

from embargo.cli import main

REPO_ROOT = Path(__file__).parent.parent


def test_eval_adversarial_flag_runs_adversarial_corpus_by_default_paths(capsys, monkeypatch):
    # This test's whole point is the CLI's default (cwd-relative) path
    # resolution, so it pins cwd explicitly rather than passing absolute
    # paths -- it must still pass no matter where pytest itself is invoked
    # from.
    monkeypatch.chdir(REPO_ROOT)

    main(["eval", "--adversarial"])
    out = capsys.readouterr().out

    assert "messages evaluated: 8" in out


def test_eval_without_adversarial_flag_still_runs_v0_corpus_by_default(capsys, monkeypatch):
    monkeypatch.chdir(REPO_ROOT)

    main(["eval"])
    out = capsys.readouterr().out

    assert "messages evaluated: 30" in out
