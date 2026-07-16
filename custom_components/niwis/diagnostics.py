"""Diagnostics support for the groundwater integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import GwConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GwConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    All data is public (NIWIS/BfG, LfU-BB); no redaction is required.
    """
    coordinator = entry.runtime_data
    readings = {
        f"{provider}:{station_id}": {
            "value": reading.value,
            "unit": reading.unit,
            "timestamp": reading.timestamp.isoformat() if reading.timestamp else None,
            "history_points": len(reading.history),
            "niedrigwasser_klasse": reading.niedrigwasser_klasse,
            "entwicklung": reading.entwicklung,
        }
        for (provider, station_id), reading in (coordinator.data or {}).items()
    }
    return {
        "entry": {
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "readings": readings,
    }
