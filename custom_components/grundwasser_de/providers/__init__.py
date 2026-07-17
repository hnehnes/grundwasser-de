"""Groundwater data providers for the (future) ``grundwasser_de`` integration.

Germany's groundwater monitoring is federal: the BfG's nationwide NIWIS network
(which additionally publishes a low-water *class*) plus one dense state network
per Bundesland. The long-term goal (see ``docs/PROJECT_BRIEF.md``) is a single
integration with interchangeable **providers** behind one common interface, so
the config flow can offer the genuinely nearest station across all sources.

This subpackage introduces that interface (:mod:`.base`) and the first
state-network provider, LfU Brandenburg (:mod:`.lfu_bb`). The existing NIWIS
client (``custom_components/niwis/api.py``) will be adapted to the same interface
in a later step; it is intentionally left untouched for now so the shipping
integration stays stable.
"""

from __future__ import annotations

from .base import (
    Provider,
    ProviderCapabilityError,
    ProviderError,
    ProviderReading,
    ProviderStation,
)
from .bukea_hh import BukeaHhProvider
from .lfu_bb import LfuBbProvider
from .niwis import NiwisProvider

__all__ = [
    "BukeaHhProvider",
    "LfuBbProvider",
    "NiwisProvider",
    "Provider",
    "ProviderCapabilityError",
    "ProviderError",
    "ProviderReading",
    "ProviderStation",
]
