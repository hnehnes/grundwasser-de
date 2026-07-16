"""Common, source-neutral provider interface for groundwater data.

A *provider* wraps one data source (NIWIS/BfG, a state network, …) behind two
operations used by the integration:

* **search** – find candidate stations, either around a location
  (:meth:`Provider.async_search_radius`) or by a free-text query
  (:meth:`Provider.async_search_query`). Not every source can do both cheaply;
  a provider raises :class:`ProviderCapabilityError` for a mode it cannot serve.
* **fetch** – read the current value (and history) of one station
  (:meth:`Provider.async_fetch`).

The dataclasses below are deliberately close to the existing NIWIS
:class:`~custom_components.niwis.api.Station`, but carry a ``provider`` tag and an
opaque ``extra`` handle so each source can stash whatever it needs to fetch later
(e.g. LfU-BB stores the internal ``msid`` + parameter id there).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


class ProviderError(Exception):
    """Base error for any provider failure (network, parsing, …)."""


class ProviderCapabilityError(ProviderError):
    """Raised when a provider is asked for a search mode it does not support."""


@dataclass(slots=True)
class ProviderStation:
    """A station discovered via a provider's search.

    ``station_id`` is the provider-native, user-facing id (NIWIS ``nummer``,
    LfU-BB Messstellenkennzahl). ``extra`` is an opaque, provider-specific handle
    carried through to :meth:`Provider.async_fetch` (e.g. the resolved internal
    id) so a fetch need not repeat the resolution work.
    """

    provider: str
    station_id: str
    name: str
    latitude: float | None = None
    longitude: float | None = None
    distance_km: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderReading:
    """A single station reading plus optional history and low-water metadata."""

    value: float | None
    unit: str
    timestamp: datetime | None = None
    #: chronological ``(timestamp, value)`` samples, oldest first.
    history: list[tuple[datetime, float]] = field(default_factory=list)
    #: NIWIS-style Niedrigwasserklasse, if the source publishes one.
    niedrigwasser_klasse: str | None = None
    #: trend/Entwicklung, if published.
    entwicklung: str | None = None
    attribution: str = ""


@runtime_checkable
class Provider(Protocol):
    """The interface every groundwater source implements."""

    #: stable machine name, e.g. ``"niwis"`` / ``"lfu_bb"``.
    domain: str
    #: human-readable source label for UI/attribution.
    label: str

    async def async_search_radius(
        self, latitude: float, longitude: float, radius_km: float
    ) -> list[ProviderStation]:
        """Return stations within ``radius_km`` of the point, nearest first."""
        ...

    async def async_search_query(self, query: str) -> list[ProviderStation]:
        """Return stations whose name or id matches ``query``."""
        ...

    async def async_fetch(self, station: ProviderStation) -> ProviderReading:
        """Return the current reading (and history) for ``station``."""
        ...
