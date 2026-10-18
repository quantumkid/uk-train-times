"""Binary sensor platform for the UK Train Times integration."""

from collections.abc import Callable
from dataclasses import dataclass

from rtt_io_api.models import Service

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import UKTTConfigEntry, UKTTCoordinator
from .entity import UKTTEntity, get_delay_minutes


@dataclass(frozen=True, kw_only=True)
class UKTTBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a UK Train Times binary sensor."""

    value_fn: Callable[[Service], bool | None]


def _is_delayed(service: Service) -> bool | None:
    delay = get_delay_minutes(service)
    return None if delay is None else delay > 0


BINARY_SENSORS: tuple[UKTTBinarySensorEntityDescription, ...] = (
    UKTTBinarySensorEntityDescription(
        key="delayed",
        translation_key="delayed",
        value_fn=_is_delayed,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UKTTConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up UK Train Times binary sensors from a config entry."""
    coordinator = entry.runtime_data
    for subentry in entry.get_subentries_of_type("route"):
        async_add_entities(
            [
                UKTTBinarySensor(coordinator, subentry, description)
                for description in BINARY_SENSORS
            ],
            config_subentry_id=subentry.subentry_id,
        )


class UKTTBinarySensor(UKTTEntity, BinarySensorEntity):
    """Binary sensor for the next train from an origin to a destination."""

    entity_description: UKTTBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: UKTTCoordinator,
        subentry: ConfigSubentry,
        description: UKTTBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, subentry, description)

    @property
    def is_on(self) -> bool | None:
        """Return the state of the next service."""
        service = self.next_service
        return None if service is None else self.entity_description.value_fn(service)
