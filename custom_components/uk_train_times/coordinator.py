"""Data update coordinator for the UK Train Times integration."""

from collections.abc import Mapping
from datetime import datetime, time, timedelta
import logging
import math
from typing import Any

import httpx2
from rtt_io_api import RTTClient
from rtt_io_api.client import MAX_SERVICES_WINDOW
from rtt_io_api.exceptions import RTTAPIError, RTTAuthenticationError, RTTRateLimitError
from rtt_io_api.models import Service, Stop

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_END_TIME,
    CONF_HOURS_OF_INTEREST,
    CONF_START_TIME,
    DEFAULT_END_TIME,
    DEFAULT_START_TIME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

MIN_UPDATE_INTERVAL = timedelta(minutes=1)
UPDATE_INTERVAL_PER_ROUTE = timedelta(minutes=1)
MAX_UPDATE_INTERVAL = timedelta(minutes=30)
UPDATE_INTERVAL_FACTOR = 0.5
DEFAULT_RATE_LIMIT_BACKOFF = timedelta(minutes=5)

type UKTTConfigEntry = ConfigEntry[UKTTCoordinator]


def parse_hours(data: Mapping[str, Any]) -> tuple[time, time]:
    """Return the start and end of the daily hours of interest.

    Missing values fall back to the defaults.
    """
    hours = data.get(CONF_HOURS_OF_INTEREST) or {}
    start = hours.get(CONF_START_TIME)
    end = hours.get(CONF_END_TIME)
    return (
        time.fromisoformat(start) if start else DEFAULT_START_TIME,
        time.fromisoformat(end) if end else DEFAULT_END_TIME,
    )


def find_period(
    at: datetime, start: time, end: time
) -> tuple[datetime, datetime, bool]:
    """Return the period containing `at`, or the next one, and whether `at` is inside.

    A period whose end is not after its start runs into the next day, so equal times
    cover the whole day.
    """
    for days in (-1, 0, 1):
        day = at + timedelta(days=days)
        period_start = day.replace(
            hour=start.hour, minute=start.minute, second=start.second, microsecond=0
        )
        end_day = day if end > start else day + timedelta(days=1)
        period_end = end_day.replace(
            hour=end.hour, minute=end.minute, second=end.second, microsecond=0
        )
        if period_end > at:
            return period_start, period_end, period_start <= at
    raise AssertionError("unreachable")


def _to_ha_error(err: RTTAPIError | httpx2.HTTPError) -> Exception:
    """Convert a client error into a Home Assistant error with a translated message."""
    if isinstance(err, RTTAuthenticationError):
        return ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="invalid_auth"
        )
    if isinstance(err, RTTRateLimitError):
        return UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="rate_limit_exceeded",
            retry_after=err.retry_after or DEFAULT_RATE_LIMIT_BACKOFF.total_seconds(),
        )
    return UpdateFailed(
        translation_domain=DOMAIN,
        translation_key="update_failed",
        translation_placeholders={"error": str(err)},
    )


class UKTTCoordinator(DataUpdateCoordinator[dict[str, list[Service]]]):
    """Fetch the upcoming services for every route subentry.

    Data is keyed by subentry ID.
    """

    config_entry: UKTTConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: UKTTConfigEntry, client: RTTClient
    ) -> None:
        """Initialize the coordinator."""
        route_count = len(config_entry.get_subentries_of_type("route"))
        self._base_update_interval = max(
            MIN_UPDATE_INTERVAL, UPDATE_INTERVAL_PER_ROUTE * route_count
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=self._base_update_interval,
        )
        self.client = client
        self._stops: dict[str, Stop] = {}
        self._next_starts: dict[str, datetime] = {}

    async def _async_setup(self) -> None:
        """Load the stops so route short codes can be resolved."""
        try:
            stops = await self.client.get_stops()
        except (RTTAPIError, httpx2.HTTPError) as err:
            raise _to_ha_error(err) from err
        self._stops = {stop.short_code: stop for stop in stops if stop.short_code}

    def _next_update_interval(self, data: dict[str, list[Service]] | None) -> timedelta:
        """Return the interval to the next update.

        Slower while the next service is far away. Never later than the start of the
        next hours of interest of a route outside them.
        """
        now = dt_util.now()
        interval = self._interval_for_services(now, data)
        if starts := [start for start in self._next_starts.values() if start > now]:
            interval = min(interval, min(starts) - now)
        return interval

    def _interval_for_services(
        self, now: datetime, data: dict[str, list[Service]] | None
    ) -> timedelta:
        if not data:
            return self._base_update_interval
        departures = [
            departure
            for services in data.values()
            for service in services
            if not service.is_cancelled
            and (departure := service.departure.expected or service.departure.scheduled)
            and departure > now
        ]
        if not departures:
            return MAX_UPDATE_INTERVAL
        return min(
            MAX_UPDATE_INTERVAL,
            max(
                self._base_update_interval,
                (min(departures) - now) * UPDATE_INTERVAL_FACTOR,
            ),
        )

    async def _async_fetch_route(
        self, subentry_id: str, route: Mapping[str, Any]
    ) -> list[Service]:
        """Fetch the services of a route, only within its hours of interest.

        Outside them, the first services of the next period are fetched once and
        reused until that period starts.
        """
        offset = int(route.get("time_offset", 0))
        window = MAX_SERVICES_WINDOW
        next_start: datetime | None = None
        hours = parse_hours(route)
        now = dt_util.now()
        from_time = now + timedelta(minutes=offset)
        period_start, period_end, inside = find_period(from_time, *hours)
        if inside:
            window = min(window, period_end - from_time)
        else:
            if self._next_starts.get(subentry_id) == period_start and (
                self.data and subentry_id in self.data
            ):
                return self.data[subentry_id]
            next_start = period_start
            offset = math.ceil((period_start - now).total_seconds() / 60)
            window = min(window, period_end - period_start)

        try:
            services = await self.client.get_services(
                self._stops[route["from_location"]],
                self._stops[route["to_location"]],
                window=window,
                time_offset=offset,
            )
        except (RTTAPIError, httpx2.HTTPError) as err:
            raise _to_ha_error(err) from err

        if next_start is None:
            self._next_starts.pop(subentry_id, None)
        else:
            self._next_starts[subentry_id] = next_start
        return services

    async def _async_update_data(self) -> dict[str, list[Service]]:
        """Fetch the upcoming services for each route."""
        data: dict[str, list[Service]] = {}
        try:
            for subentry in self.config_entry.get_subentries_of_type("route"):
                data[subentry.subentry_id] = await self._async_fetch_route(
                    subentry.subentry_id, subentry.data
                )
        finally:
            self.update_interval = self._next_update_interval(data or self.data)
        return data
