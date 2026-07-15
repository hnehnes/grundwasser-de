"""Sensor platform for the NIWIS integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfLength,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Station
from .const import (
    ATTRIBUTION,
    CONF_STATION_MESSGROESSEN,
    CONF_STATION_NAME,
    CONF_STATION_NUMMER,
    DOMAIN,
    ENTWICKLUNG_DISPLAY,
    ENTWICKLUNG_DISPLAY_OPTIONS,
    LWK_DISPLAY,
    LWK_DISPLAY_OPTIONS,
    MANUFACTURER,
    MESSGROESSE_DISPLAY,
    MG_ABFLUSS,
    MG_GRUNDWASSER,
    MG_QUELLSCHUETTUNG,
    MG_WASSERSTAND,
)
from .coordinator import NiwisConfigEntry, NiwisCoordinator


@dataclass(frozen=True, kw_only=True)
class ValueSpec:
    """Per-measurement-type configuration for the value sensor."""

    device_class: SensorDeviceClass
    unit: str
    suggested_precision: int


VALUE_SPECS: dict[str, ValueSpec] = {
    MG_GRUNDWASSER: ValueSpec(
        device_class=SensorDeviceClass.DISTANCE,
        unit=UnitOfLength.METERS,
        suggested_precision=2,
    ),
    MG_WASSERSTAND: ValueSpec(
        device_class=SensorDeviceClass.DISTANCE,
        unit=UnitOfLength.CENTIMETERS,
        suggested_precision=0,
    ),
    MG_ABFLUSS: ValueSpec(
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        unit=UnitOfVolumeFlowRate.CUBIC_METERS_PER_SECOND,
        suggested_precision=2,
    ),
    MG_QUELLSCHUETTUNG: ValueSpec(
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        unit=UnitOfVolumeFlowRate.LITERS_PER_SECOND,
        suggested_precision=1,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NiwisConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up NIWIS sensors from a config entry."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    for station in coordinator.selected_stations:
        nummer = station[CONF_STATION_NUMMER]
        name = station[CONF_STATION_NAME]
        for messgroesse in station[CONF_STATION_MESSGROESSEN]:
            entities.append(
                NiwisValueSensor(coordinator, nummer, name, messgroesse)
            )
            entities.append(
                NiwisKlasseSensor(coordinator, nummer, name, messgroesse)
            )
            entities.append(
                NiwisTrendSensor(coordinator, nummer, name, messgroesse)
            )

    async_add_entities(entities)


class NiwisBaseSensor(CoordinatorEntity[NiwisCoordinator], SensorEntity):
    """Base entity binding a sensor to one station/measurement type."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: NiwisCoordinator,
        nummer: str,
        name: str,
        messgroesse: str,
    ) -> None:
        """Initialise the base sensor."""
        super().__init__(coordinator)
        self._nummer = nummer
        self._messgroesse = messgroesse
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, nummer)},
            name=f"{name} ({nummer})",
            manufacturer=MANUFACTURER,
            model=MESSGROESSE_DISPLAY.get(messgroesse, messgroesse),
            configuration_url="https://niwis-online.de/",
        )

    @property
    def _station(self) -> Station | None:
        """Return the current station reading, if available."""
        return self.coordinator.get_station(self._messgroesse, self._nummer)

    @property
    def available(self) -> bool:
        """Return True if the coordinator has data for this station."""
        return super().available and self._station is not None


class NiwisValueSensor(NiwisBaseSensor):
    """Current measured value (level / discharge / spring flow)."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: NiwisCoordinator,
        nummer: str,
        name: str,
        messgroesse: str,
    ) -> None:
        """Initialise the value sensor with the right unit/device class."""
        super().__init__(coordinator, nummer, name, messgroesse)
        spec = VALUE_SPECS[messgroesse]
        self._attr_unique_id = f"{nummer}_{messgroesse}_value"
        self._attr_name = MESSGROESSE_DISPLAY.get(messgroesse, messgroesse)
        self._attr_device_class = spec.device_class
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_suggested_display_precision = spec.suggested_precision

    @property
    def native_value(self) -> float | None:
        """Return the current measured value."""
        station = self._station
        return station.aktueller_messwert if station else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose additional low-water context as attributes."""
        station = self._station
        if station is None:
            return {}
        return {
            "pegel_unter_glw": station.pegel_unter_glw,
            "anzahl_tage_unter_glw": station.anzahl_tage_unter_glw,
            "messstellennummer": station.nummer,
        }


class NiwisKlasseSensor(NiwisBaseSensor):
    """NIWIS low-water class as a German text state (reference 1991–2020)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = LWK_DISPLAY_OPTIONS

    def __init__(
        self,
        coordinator: NiwisCoordinator,
        nummer: str,
        name: str,
        messgroesse: str,
    ) -> None:
        """Initialise the low-water class sensor."""
        super().__init__(coordinator, nummer, name, messgroesse)
        self._attr_unique_id = f"{nummer}_{messgroesse}_niedrigwasserklasse"
        label = MESSGROESSE_DISPLAY.get(messgroesse, messgroesse)
        self._attr_name = f"Niedrigwasserklasse {label}"

    @property
    def native_value(self) -> str | None:
        """Return the localized low-water class text."""
        station = self._station
        if station is None or station.niedrigwasser_klasse is None:
            return None
        return LWK_DISPLAY.get(station.niedrigwasser_klasse)


class NiwisTrendSensor(NiwisBaseSensor):
    """Trend / development of the reading as a German text state."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ENTWICKLUNG_DISPLAY_OPTIONS

    def __init__(
        self,
        coordinator: NiwisCoordinator,
        nummer: str,
        name: str,
        messgroesse: str,
    ) -> None:
        """Initialise the trend sensor."""
        super().__init__(coordinator, nummer, name, messgroesse)
        self._attr_unique_id = f"{nummer}_{messgroesse}_trend"
        label = MESSGROESSE_DISPLAY.get(messgroesse, messgroesse)
        self._attr_name = f"Trend {label}"

    @property
    def native_value(self) -> str | None:
        """Return the localized trend text."""
        station = self._station
        if station is None or station.entwicklung is None:
            return None
        return ENTWICKLUNG_DISPLAY.get(station.entwicklung)
