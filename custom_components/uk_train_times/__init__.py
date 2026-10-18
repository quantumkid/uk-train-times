"""The UK Train Times integration."""

import logging

from rtt_io_api import RTTClient

from homeassistant.const import CONF_API_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import AnyDeviceEntry

from .const import DOMAIN, RTT_API_BASE_URL
from .coordinator import UKTTConfigEntry, UKTTCoordinator

_PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UKTTConfigEntry,
) -> bool:
    """Set up UK Train Times from a config entry."""
    client = RTTClient(
        refresh_token=entry.data[CONF_API_TOKEN], base_url=RTT_API_BASE_URL
    )
    coordinator = UKTTCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: UKTTConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: UKTTConfigEntry, device_entry: AnyDeviceEntry
) -> bool:
    """Allow removing a device only if its route no longer exists."""
    return not any(
        (DOMAIN, subentry_id) in device_entry.identifiers
        for subentry_id in entry.subentries
    )


async def _async_update_listener(hass: HomeAssistant, entry: UKTTConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
