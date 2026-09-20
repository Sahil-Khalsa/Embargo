"""spec §14.2: multiple resolver implementations behind the unchanged
Resolver Protocol, selected by config -- not by changing which code path
runs. Per an explicit user decision (not the implementer's to make
unilaterally): only the selection machinery is built here. Neither "hosted"
nor "self_hosted" makes a real network call in this build -- there is no API
key or local model server available in this environment. That is a
deliberate, documented partial satisfaction of V2 acceptance criterion 2,
not an oversight."""

import json
from datetime import datetime

import pytest

from embargo.backends import build_resolver
from embargo.config import Config
from embargo.models import Message
from embargo.resolver import FakeResolver, ModelResolver


def test_fake_backend_returns_a_working_fake_resolver(tmp_path):
    fixtures_path = tmp_path / "fixtures.json"
    fixtures_path.write_text(json.dumps({}))
    config = Config(backend="fake")

    resolver = build_resolver(config, fixtures_path=fixtures_path)

    assert isinstance(resolver, FakeResolver)
    assert resolver.backend_name == "fake"


def test_hosted_backend_returns_a_model_resolver_with_correct_backend_name(tmp_path):
    config = Config(backend="hosted")

    resolver = build_resolver(config, fixtures_path=tmp_path / "unused.json")

    assert isinstance(resolver, ModelResolver)
    assert resolver.backend_name == "hosted"


def test_self_hosted_backend_returns_a_model_resolver_with_correct_backend_name(tmp_path):
    config = Config(backend="self_hosted")

    resolver = build_resolver(config, fixtures_path=tmp_path / "unused.json")

    assert isinstance(resolver, ModelResolver)
    assert resolver.backend_name == "self_hosted"


def test_hosted_backend_is_honestly_not_wired_to_a_real_call(tmp_path):
    """Selecting "hosted" must not silently fabricate a response -- it must
    fail loudly and clearly if actually asked to resolve something, since no
    real vendor call is implemented in this build."""
    config = Config(backend="hosted")
    resolver = build_resolver(config, fixtures_path=tmp_path / "unused.json")
    message = Message(
        message_id="M1", sender="alice", recipients=["bob"],
        timestamp=datetime(2026, 6, 1), body="hello",
    )

    with pytest.raises(NotImplementedError):
        resolver.resolve(message, candidates=[])


def test_unknown_backend_raises_a_clear_error(tmp_path):
    config = Config(backend="not_a_real_backend")

    with pytest.raises(ValueError, match="not_a_real_backend"):
        build_resolver(config, fixtures_path=tmp_path / "unused.json")


def test_switching_backend_is_purely_a_config_change(tmp_path):
    """The whole point of criterion 2: selection is data (config.backend),
    not a code branch the caller has to write."""
    fixtures_path = tmp_path / "fixtures.json"
    fixtures_path.write_text(json.dumps({}))

    configs = [Config(backend="fake"), Config(backend="hosted"), Config(backend="self_hosted")]
    resolvers = [build_resolver(c, fixtures_path=fixtures_path) for c in configs]

    assert [r.backend_name for r in resolvers] == ["fake", "hosted", "self_hosted"]
