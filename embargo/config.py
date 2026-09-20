import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_THRESHOLD = 0.6
DEFAULT_BACKEND = "fake"
DEFAULT_DB_PATH = "embargo.db"
# Deliberately not auto-applied anywhere: spec §12 flags "fixed policy vs.
# per-event" as an open question not to be decided unilaterally. This field
# exists so that decision has somewhere to live once made, the same way V0
# stored recorded_at/ledger_version unused until a later tier needed them.
DEFAULT_DIGESTION_WINDOW_DAYS: int | None = None


@dataclass(frozen=True)
class Config:
    threshold: float = DEFAULT_THRESHOLD
    digestion_window_days: int | None = DEFAULT_DIGESTION_WINDOW_DAYS
    backend: str = DEFAULT_BACKEND
    db_path: str = DEFAULT_DB_PATH


def load_config(path: str | Path | None = None) -> Config:
    """Loads config from a TOML file. No path, or a path that doesn't
    exist, is not an error -- falls back to built-in defaults, consistent
    with every other optional setting in this project."""
    if path is None:
        return Config()
    path = Path(path)
    if not path.exists():
        return Config()

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    return Config(
        threshold=raw.get("threshold", DEFAULT_THRESHOLD),
        digestion_window_days=raw.get("digestion_window_days", DEFAULT_DIGESTION_WINDOW_DAYS),
        backend=raw.get("backend", DEFAULT_BACKEND),
        db_path=raw.get("db_path", DEFAULT_DB_PATH),
    )
