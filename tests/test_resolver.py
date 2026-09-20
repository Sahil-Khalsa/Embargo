import json
from datetime import datetime

import pytest

from embargo.models import Fact, FactState, MaterialityLevel, Message
from embargo.resolver import FakeResolver, ModelResolver, ResolverOutputInvalid


def _fact(fact_id="F047", state=FactState.PRIVATE, announced_at=None, cleared_at=None):
    return Fact(
        fact_id=fact_id,
        summary="Acme is acquiring Beta",
        entities=["ACME"],
        aliases=["Project Falcon"],
        state=state,
        recorded_at=datetime(2026, 1, 1),
        materiality=[(datetime(2026, 1, 1), MaterialityLevel.HIGH)],
        announced_at=announced_at,
        cleared_at=cleared_at,
    )


def _message(body="the thing from the other day", message_id="M001"):
    return Message(
        message_id=message_id,
        sender="alice",
        recipients=["bob"],
        timestamp=datetime(2026, 6, 1),
        body=body,
    )


# --- FakeResolver -----------------------------------------------------------


def test_fake_resolver_returns_fixture_resolutions_for_known_message_id():
    fixtures = {
        "M001": [
            {"fact_id": "F047", "mode": "conveys", "confidence": 0.82, "span": "the thing from the other day"}
        ]
    }
    resolver = FakeResolver(fixtures)

    resolutions = resolver.resolve(_message(), [_fact()])

    assert len(resolutions) == 1
    assert resolutions[0].fact_id == "F047"
    assert resolutions[0].mode.value == "conveys"
    assert resolutions[0].confidence == 0.82


def test_fake_resolver_returns_empty_list_for_unknown_message_id():
    resolver = FakeResolver({})

    assert resolver.resolve(_message(message_id="unknown"), [_fact()]) == []


def test_fake_resolver_rejects_resolution_for_fact_not_among_candidates():
    fixtures = {
        "M001": [
            {"fact_id": "F999", "mode": "conveys", "confidence": 0.9, "span": "the thing from the other day"}
        ]
    }
    resolver = FakeResolver(fixtures)

    # F999 isn't in the candidates list passed to resolve() -- simulates a
    # fixture/model referencing a fact the resolver was never shown.
    assert resolver.resolve(_message(), [_fact(fact_id="F047")]) == []


def test_fake_resolver_rejects_resolution_whose_span_is_not_verbatim_in_body():
    fixtures = {
        "M001": [
            {"fact_id": "F047", "mode": "conveys", "confidence": 0.9, "span": "not in the body anywhere"}
        ]
    }
    resolver = FakeResolver(fixtures)

    assert resolver.resolve(_message(), [_fact()]) == []


def test_fake_resolver_reports_fake_backend_name_and_version():
    resolver = FakeResolver({})

    assert resolver.backend_name == "fake"
    assert resolver.model_version == "fixtures"


def test_fake_resolver_from_file_loads_json_fixture(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    fixture_path.write_text(
        json.dumps(
            {
                "M001": [
                    {
                        "fact_id": "F047",
                        "mode": "mentions",
                        "confidence": 0.5,
                        "span": "the thing from the other day",
                    }
                ]
            }
        )
    )

    resolver = FakeResolver.from_file(fixture_path)
    resolutions = resolver.resolve(_message(), [_fact()])

    assert resolutions[0].mode.value == "mentions"


# --- ModelResolver ------------------------------------------------------------


def _valid_response(span="the thing from the other day"):
    return json.dumps(
        [{"fact_id": "F047", "mode": "conveys", "confidence": 0.82, "span": span}]
    )


def test_model_resolver_parses_valid_json_response():
    resolver = ModelResolver(model_call=lambda prompt: _valid_response())

    resolutions = resolver.resolve(_message(), [_fact()])

    assert len(resolutions) == 1
    assert resolutions[0].fact_id == "F047"
    assert resolutions[0].confidence == 0.82


def test_model_resolver_retries_once_on_invalid_json_then_succeeds():
    calls = []

    def model_call(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return "not json"
        return _valid_response()

    resolver = ModelResolver(model_call=model_call)
    resolutions = resolver.resolve(_message(), [_fact()])

    assert len(calls) == 2
    assert len(resolutions) == 1


def test_model_resolver_raises_after_two_invalid_outputs():
    resolver = ModelResolver(model_call=lambda prompt: "not json")

    with pytest.raises(ResolverOutputInvalid):
        resolver.resolve(_message(), [_fact()])


def test_model_resolver_rejects_resolution_with_non_verbatim_span():
    resolver = ModelResolver(model_call=lambda prompt: _valid_response(span="never said this"))

    assert resolver.resolve(_message(), [_fact()]) == []


def test_model_resolver_prompt_excludes_fact_state_and_timestamps():
    captured = {}

    def model_call(prompt):
        captured["prompt"] = prompt
        return _valid_response()

    resolver = ModelResolver(model_call=model_call)
    fact = _fact(
        state=FactState.ANNOUNCED,
        announced_at=datetime(2026, 3, 14, 9, 30),
        cleared_at=datetime(2026, 4, 1),
    )

    resolver.resolve(_message(), [fact])

    prompt = captured["prompt"]
    assert "announced" not in prompt.lower()
    assert "2026-03-14" not in prompt
    assert "2026-04-01" not in prompt


def test_model_resolver_reports_configured_backend_name_and_model_version():
    resolver = ModelResolver(
        model_call=lambda prompt: _valid_response(),
        backend_name="hosted",
        model_version="claude-x",
    )

    assert resolver.backend_name == "hosted"
    assert resolver.model_version == "claude-x"


def test_model_resolver_defaults_backend_name_and_model_version_to_unknown():
    resolver = ModelResolver(model_call=lambda prompt: _valid_response())

    assert resolver.backend_name == "unknown"
    assert resolver.model_version == "unknown"


def test_model_resolver_prompt_includes_candidate_id_summary_entities_aliases():
    captured = {}

    def model_call(prompt):
        captured["prompt"] = prompt
        return _valid_response()

    resolver = ModelResolver(model_call=model_call)
    resolver.resolve(_message(), [_fact()])

    prompt = captured["prompt"]
    assert "F047" in prompt
    assert "Acme is acquiring Beta" in prompt
    assert "ACME" in prompt
    assert "Project Falcon" in prompt
