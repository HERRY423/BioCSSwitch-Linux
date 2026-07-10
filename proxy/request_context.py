"""Typed request/runtime context shared by proxy routing and Ultra.

The proxy used to keep one dataclass while task routing and Ultra passed a
second, loosely related ``dict`` shape.  ``RequestContext`` is now the single
context contract across those paths.  Provider-specific settings live in the
``prov`` snapshot; routing metadata has explicit fields and can be added with
``routed()`` without mutating the server's active context.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping


@dataclass(slots=True)
class RequestContext:
    """One coherent provider, credential, model-policy, and route snapshot."""

    prov_name: str
    prov: dict[str, Any]
    key: str
    auth_secret: str | None = None
    shim_mode: str = "off"
    ultra_mode: str = "off"
    ultra_ledger: str | None = None
    relay_models: list[str] = field(default_factory=list)
    relay_force_model: str | None = None
    relay_thinking: str | None = None
    profile_id: str = "active"
    profile_name: str = ""
    template_id: str = ""
    base_url: str = ""
    route_source: str = ""
    probe_results: tuple[Mapping[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.prov_name:
            raise ValueError("prov_name is required")
        if not isinstance(self.prov, dict):
            raise TypeError("prov must be a provider configuration dict")
        if not self.profile_name:
            self.profile_name = self.prov_name
        if not self.template_id:
            self.template_id = self.prov_name

    @property
    def provider(self) -> str:
        return self.prov_name

    @property
    def mode(self) -> str:
        return str(self.prov.get("mode") or "anthropic")

    @property
    def url(self) -> str:
        return str(self.prov.get("url") or "")

    @property
    def models_url(self) -> str:
        return str(self.prov.get("models_url") or "")

    @property
    def auth_style(self) -> str:
        return str(self.prov.get("auth_style") or "x-api-key")

    @property
    def key_env(self) -> str:
        return str(self.prov.get("key_env") or "")

    @property
    def model(self) -> str:
        return self.relay_force_model or ""

    @property
    def thinking_policy(self) -> str:
        return self.relay_thinking or ""

    def routed(
        self,
        source: str,
        probes: Iterable[Mapping[str, str]] = (),
    ) -> "RequestContext":
        """Return a route-decorated copy without mutating provider state."""

        return replace(
            self,
            route_source=str(source or ""),
            probe_results=tuple(dict(item) for item in probes),
        )

    def identity_key(self) -> tuple[str, str, str, str]:
        return (self.profile_id, self.provider, self.url, self.model)

    def safe_route_summary(self) -> dict[str, Any]:
        """Serialize route metadata without credentials or provider secrets."""

        return {
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
            "provider": self.provider,
            "model": self.model,
            "route_source": self.route_source,
            "probes": [dict(item) for item in self.probe_results],
        }
