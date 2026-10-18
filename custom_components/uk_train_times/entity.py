"""Base entity for the UK Train Times integration."""

from rtt_io_api.models import Service

from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UKTTCoordinator


def get_delay_minutes(service: Service) -> int | None:
    """Return the whole minutes the service is running late.

    A service without a forecast is treated as on time. None if there is no schedule.
    """
    scheduled = service.departure.scheduled
    if scheduled is None:
        return None
    expected = service.departure.expected or scheduled
    return max(0, int((expected - scheduled).total_seconds() // 60))


class UKTTEntity(CoordinatorEntity[UKTTCoordinator]):
    """Base class for entities of a UK Train Times route."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UKTTCoordinator,
        subentry: ConfigSubentry,
        description: EntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._subentry_id = subentry.subentry_id
        self._attr_unique_id = f"{subentry.subentry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            translation_key="route",
            translation_placeholders={
                "from_location": subentry.data["from_location"],
                "to_location": subentry.data["to_location"],
            },
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def next_service(self) -> Service | None:
        """Return the next non-cancelled service on the route."""
        for service in self.coordinator.data[self._subentry_id]:
            if not service.is_cancelled:
                return service
        return None
