from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .client import NapCatClient
from .protocol_catalog import PROTOCOL_BY_KEY, ProtocolSpec


class QQPetProtocolAdapter(Protocol):
    def spec(self, key: str) -> ProtocolSpec: ...

    def list_specs(self) -> tuple[ProtocolSpec, ...]: ...


@dataclass(frozen=True)
class CatalogAdapter:
    """Lightweight protocol metadata adapter for the pure-PC stack."""

    def spec(self, key: str) -> ProtocolSpec:
        try:
            return PROTOCOL_BY_KEY[key]
        except KeyError as exc:
            raise KeyError(f"unknown protocol key: {key}") from exc

    def list_specs(self) -> tuple[ProtocolSpec, ...]:
        return tuple(PROTOCOL_BY_KEY.values())


class QQPetClientAdapter:
    """Bridge the catalog to the existing client implementation."""

    def __init__(self, client: NapCatClient) -> None:
        self.client = client

    def query_own_pet(self):
        return self.client.query_own_pet_profile()

    def query_story_status(self):
        return self.client.query_story()

    def query_values(self):
        return self.client.query_values()

