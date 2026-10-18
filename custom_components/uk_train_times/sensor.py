"""Sensor platform for the UK Train Times integration."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from rtt_io_api.models import Service

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.dt import utcnow

from .coordinator import UKTTConfigEntry, UKTTCoordinator
from .entity import UKTTEntity, get_delay_minutes


@dataclass(frozen=True, kw_only=True)
class UKTTSensorEntityDescription(SensorEntityDescription):
    """Describes a UK Train Times sensor."""

    value_fn: Callable[[Service], datetime | int | None]


SENSORS: tuple[UKTTSensorEntityDescription, ...] = (
    UKTTSensorEntityDescription(
        key="expected_departure",
        translation_key="expected_departure",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda service: (
            service.departure.expected or service.departure.scheduled
        ),
    ),
    UKTTSensorEntityDescription(
        key="scheduled_departure",
        translation_key="scheduled_departure",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda service: service.departure.scheduled,
    ),
    UKTTSensorEntityDescription(
        key="delay",
        translation_key="delay",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=get_delay_minutes,
    ),
)


SERVICES_NEXT_HOUR_DESCRIPTION = SensorEntityDescription(
    key="services_next_hour",
    translation_key="services_next_hour",
    state_class=SensorStateClass.MEASUREMENT,
)

SERVICES_WINDOW = timedelta(hours=1)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UKTTConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up UK Train Times from a config entry."""
    coordinator = entry.runtime_data
    for subentry in entry.get_subentries_of_type("route"):
        async_add_entities(
            [
                *(
                    UKTTSensor(coordinator, subentry, description)
                    for description in SENSORS
                ),
                UKTTServicesNextHourSensor(
                    coordinator, subentry, SERVICES_NEXT_HOUR_DESCRIPTION
                ),
            ],
            config_subentry_id=subentry.subentry_id,
        )


class UKTTSensor(UKTTEntity, SensorEntity):
    """Sensor for the next train from an origin to a destination."""

    entity_description: UKTTSensorEntityDescription

    def __init__(
        self,
        coordinator: UKTTCoordinator,
        subentry: ConfigSubentry,
        description: UKTTSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, subentry, description)

    @property
    def native_value(self) -> datetime | int | None:
        """Return the value for the next non-cancelled service."""
        service = self.next_service
        return None if service is None else self.entity_description.value_fn(service)


class UKTTServicesNextHourSensor(UKTTEntity, SensorEntity):
    """Sensor counting the services leaving in the next hour."""

    _unrecorded_attributes = frozenset({"services"})

    def _services_next_hour(self) -> list[Service]:
        cutoff = utcnow() + SERVICES_WINDOW
        return [
            service
            for service in self.coordinator.data[self._subentry_id]
            if (departure := service.departure.expected or service.departure.scheduled)
            and departure <= cutoff
        ]

    @property
    def native_value(self) -> int:
        """Return the number of non-cancelled services in the next hour."""
        return sum(not service.is_cancelled for service in self._services_next_hour())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the services in the next hour, including cancelled ones."""
        return {
            "services": [
                {
                    "scheduled_departure": _isoformat(service.departure.scheduled),
                    "expected_departure": _isoformat(service.departure.expected),
                    "delay": get_delay_minutes(service),
                    "platform": service.platform,
                    "operator": service.operator_name,
                    "destination": ", ".join(service.destination),
                    "cancelled": service.is_cancelled,
                }
                for service in self._services_next_hour()
            ]
        }


def _isoformat(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
