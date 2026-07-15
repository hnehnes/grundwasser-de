"""Diagnostics support for the NIWIS integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import NiwisConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NiwisConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    All NIWIS data is public; no redaction is required.
    """
    coordinator = entry.runtime_data
    data = {
        messgroesse: {
            nummer: station.raw for nummer, station in stations.items()
        }
        for messgroesse, stations in (coordinator.data or {}).items()
    }
    return {
        "entry": {
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "needed_messgroessen": sorted(
            {
                mg
                for s in entry.data.get("stations", [])
                for mg in s.get("messgroessen", [])
            }
        ),
        "data": data,
    }
