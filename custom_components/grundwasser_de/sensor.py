"""Sensor platform for the groundwater integration (provider-neutral).

Per configured station: a groundwater-level value sensor. NIWIS stations
additionally get a low-water-class and a trend sensor (only NIWIS publishes
those). Values/units come from the provider's :class:`ProviderReading`.
"""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_PROVIDER,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    DOMAIN,
    ENTWICKLUNG_DISPLAY,
    ENTWICKLUNG_DISPLAY_OPTIONS,
    LWK_DISPLAY,
    LWK_DISPLAY_OPTIONS,
)
from .coordinator import GwConfigEntry, GwCoordinator
from .providers import ProviderReading
from .providers.niwis import DOMAIN as NIWIS_DOMAIN
from .providers.niwis import LABEL as NIWIS_LABEL

# Human-readable manufacturer label per provider (device "manufacturer" field).
_PROVIDER_LABELS = {NIWIS_DOMAIN: NIWIS_LABEL}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GwConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up groundwater sensors from a config entry."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    for descriptor in coordinator.selected_stations:
        provider = descriptor[CONF_PROVIDER]
        station_id = descriptor[CONF_STATION_ID]
        name = descriptor.get(CONF_STATION_NAME) or station_id
        entities.append(GwValueSensor(coordinator, provider, station_id, name))
        # Low-water class and trend are NIWIS-only metadata.
        if provider == NIWIS_DOMAIN:
            entities.append(GwKlasseSensor(coordinator, provider, station_id, name))
            entities.append(GwTrendSensor(coordinator, provider, station_id, name))

    async_add_entities(entities)


class GwBaseSensor(CoordinatorEntity[GwCoordinator], SensorEntity):
    """Base entity binding a sensor to one provider station."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: GwCoordinator, provider: str, station_id: str, name: str
    ) -> None:
        """Initialise the base sensor."""
        super().__init__(coordinator)
        self._provider = provider
        self._station_id = station_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{provider}:{station_id}")},
            name=name,
            serial_number=station_id,
            manufacturer=_PROVIDER_LABELS.get(provider, provider),
            model="Grundwassermessstelle",
        )

    @property
    def _reading(self) -> ProviderReading | None:
        """Return the current reading for this station, if available."""
        return self.coordinator.get_reading(self._provider, self._station_id)

    @property
    def available(self) -> bool:
        """Return True if the coordinator has a reading for this station."""
        return super().available and self._reading is not None

    @property
    def attribution(self) -> str | None:
        """Return the provider's attribution string."""
        reading = self._reading
        return reading.attribution if reading else None


class GwValueSensor(GwBaseSensor):
    """Current groundwater level (m ü. NHN)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_suggested_display_precision = 2

    def __init__(
        self, coordinator: GwCoordinator, provider: str, station_id: str, name: str
    ) -> None:
        """Initialise the value sensor."""
        super().__init__(coordinator, provider, station_id, name)
        self._attr_unique_id = f"{provider}_{station_id}_grundwasserstand"
        self._attr_name = "Grundwasserstand"

    @property
    def native_value(self) -> float | None:
        """Return the current groundwater level."""
        reading = self._reading
        return reading.value if reading else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the measurement timestamp and station id."""
        reading = self._reading
        if reading is None:
            return {}
        return {
            "messzeitpunkt": reading.timestamp.isoformat()
            if reading.timestamp
            else None,
            "messstelle": self._station_id,
        }


class GwKlasseSensor(GwBaseSensor):
    """NIWIS low-water class as a German text state (reference 1991–2020)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = LWK_DISPLAY_OPTIONS

    def __init__(
        self, coordinator: GwCoordinator, provider: str, station_id: str, name: str
    ) -> None:
        """Initialise the low-water class sensor."""
        super().__init__(coordinator, provider, station_id, name)
        self._attr_unique_id = f"{provider}_{station_id}_niedrigwasserklasse"
        self._attr_name = "Niedrigwasserklasse"

    @property
    def native_value(self) -> str | None:
        """Return the localized low-water class text."""
        reading = self._reading
        if reading is None or reading.niedrigwasser_klasse is None:
            return None
        return LWK_DISPLAY.get(reading.niedrigwasser_klasse)


class GwTrendSensor(GwBaseSensor):
    """Trend / development of the reading as a German text state."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ENTWICKLUNG_DISPLAY_OPTIONS

    def __init__(
        self, coordinator: GwCoordinator, provider: str, station_id: str, name: str
    ) -> None:
        """Initialise the trend sensor."""
        super().__init__(coordinator, provider, station_id, name)
        self._attr_unique_id = f"{provider}_{station_id}_trend"
        self._attr_name = "Trend"

    @property
    def native_value(self) -> str | None:
        """Return the localized trend text."""
        reading = self._reading
        if reading is None or reading.entwicklung is None:
            return None
        return ENTWICKLUNG_DISPLAY.get(reading.entwicklung)
