"""Backend selection (spec §14.2): config picks which Resolver implementation
runs, without the caller branching on it in code.

Only "fake" is wired to a real, working call in this build. "hosted" and
"self_hosted" are registered, return a correctly-labeled ModelResolver, and
are fully selectable via config -- but their model_call raises
NotImplementedError if actually invoked, since this environment has neither
a vendor API key nor a local model server to call. This is a deliberate,
documented partial satisfaction of V2 acceptance criterion 2 (a user
decision, not made unilaterally): the selection machinery is real and
tested; the network calls are not.
"""

from pathlib import Path

from embargo.config import Config
from embargo.resolver import FakeResolver, ModelResolver, Resolver


def _build_fake(config: Config, fixtures_path: str | Path) -> Resolver:
    return FakeResolver.from_file(fixtures_path)


def _not_implemented_call(backend_name: str):
    def _call(prompt: str) -> str:
        raise NotImplementedError(
            f"backend {backend_name!r} is selectable via config but not wired to a "
            "real model call in this build (no API key / local model server "
            "available) -- see spec §14.2 and STATUS.md"
        )

    return _call


def _build_hosted(config: Config, fixtures_path: str | Path) -> Resolver:
    return ModelResolver(
        model_call=_not_implemented_call("hosted"),
        backend_name="hosted",
        model_version="unconfigured",
    )


def _build_self_hosted(config: Config, fixtures_path: str | Path) -> Resolver:
    return ModelResolver(
        model_call=_not_implemented_call("self_hosted"),
        backend_name="self_hosted",
        model_version="unconfigured",
    )


BACKEND_FACTORIES = {
    "fake": _build_fake,
    "hosted": _build_hosted,
    "self_hosted": _build_self_hosted,
}


def build_resolver(config: Config, *, fixtures_path: str | Path) -> Resolver:
    try:
        factory = BACKEND_FACTORIES[config.backend]
    except KeyError:
        raise ValueError(
            f"unknown backend {config.backend!r}; choose one of {sorted(BACKEND_FACTORIES)}"
        ) from None
    return factory(config, fixtures_path)
