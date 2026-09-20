from embargo.config import Config, DEFAULT_THRESHOLD, load_config


def test_load_config_with_no_path_returns_defaults():
    config = load_config(None)

    assert config == Config()
    assert config.threshold == DEFAULT_THRESHOLD
    assert config.digestion_window_days is None
    assert config.backend == "fake"
    assert config.db_path == "embargo.db"


def test_load_config_with_missing_file_returns_defaults(tmp_path):
    config = load_config(tmp_path / "does_not_exist.toml")

    assert config == Config()


def test_load_config_reads_threshold_from_file(tmp_path):
    path = tmp_path / "embargo.toml"
    path.write_text("threshold = 0.8\n")

    config = load_config(path)

    assert config.threshold == 0.8


def test_load_config_reads_all_fields_from_file(tmp_path):
    path = tmp_path / "embargo.toml"
    path.write_text(
        "threshold = 0.75\n"
        "digestion_window_days = 30\n"
        "backend = \"hosted\"\n"
        "db_path = \"/var/lib/embargo/embargo.db\"\n"
    )

    config = load_config(path)

    assert config.threshold == 0.75
    assert config.digestion_window_days == 30
    assert config.backend == "hosted"
    assert config.db_path == "/var/lib/embargo/embargo.db"


def test_load_config_partial_file_falls_back_to_defaults_for_missing_fields(tmp_path):
    path = tmp_path / "embargo.toml"
    path.write_text("threshold = 0.9\n")

    config = load_config(path)

    assert config.threshold == 0.9
    assert config.backend == "fake"
    assert config.db_path == "embargo.db"
