"""Config flow for the UK Train Times integration."""

from collections.abc import Mapping
import logging
from types import MappingProxyType
from typing import Any

import httpx2
import probatio
from rtt_io_api import RTTClient
from rtt_io_api.exceptions import RTTAPIError, RTTAuthenticationError, RTTRateLimitError

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_TOKEN, UnitOfTime
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TimeSelector,
)

from .const import (
    CONF_END_TIME,
    CONF_HOURS_OF_INTEREST,
    CONF_START_TIME,
    DEFAULT_END_TIME,
    DEFAULT_START_TIME,
    DOMAIN,
    MAX_TIME_OFFSET,
    RTT_API_BASE_URL,
)

_LOGGER = logging.getLogger(__name__)

STEP_API_TOKEN_SCHEMA = probatio.Schema({probatio.Required(CONF_API_TOKEN): str})


async def validate_input(hass: HomeAssistant, data: Mapping[str, Any]) -> None:
    """Validate the API token by exchanging it for an access token."""
    client = RTTClient(
        refresh_token=data[CONF_API_TOKEN],
        base_url=RTT_API_BASE_URL,
        http_client=get_async_client(hass),
    )
    try:
        await client.get_access_token()
    except RTTAuthenticationError as err:
        raise InvalidAuth from err
    except RTTRateLimitError as err:
        raise RateLimited from err
    except (RTTAPIError, httpx2.HTTPError) as err:
        raise CannotConnect from err


class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UK Train Times."""

    VERSION = 1

    async def _async_validate_token(self, data: Mapping[str, Any]) -> str | None:
        """Return an error key if the API token can't be used."""
        try:
            await validate_input(self.hass, data)
        except InvalidAuth:
            return "invalid_auth"
        except RateLimited:
            return "rate_limited"
        except CannotConnect:
            return "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            return "unknown"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := await self._async_validate_token(user_input):
                errors["base"] = error
            else:
                await self.async_set_unique_id(user_input[CONF_API_TOKEN][:16])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="UK Train Times", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_API_TOKEN_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle the API token being rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := await self._async_validate_token(user_input):
                errors["base"] = error
            else:
                return self.async_update_and_abort(
                    self._get_reauth_entry(), data_updates=user_input
                )

        return self.async_show_form(
            step_id="reauth_confirm", data_schema=STEP_API_TOKEN_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the API token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := await self._async_validate_token(user_input):
                errors["base"] = error
            else:
                await self.async_set_unique_id(user_input[CONF_API_TOKEN][:16])
                return self.async_update_and_abort(
                    self._get_reconfigure_entry(),
                    unique_id=self.unique_id,
                    data_updates=user_input,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_API_TOKEN_SCHEMA, self._get_reconfigure_entry().data
            ),
            errors=errors,
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return a list of supported subentry types for this config entry."""
        return {"route": UKTTRouteSubentryFlowHandler}


class UKTTRouteSubentryFlowHandler(ConfigSubentryFlow):
    """Handle a subentry flow for UK Train Times routes."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle the initial step of the subentry flow."""
        return await self._async_route_step("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of a route."""
        return await self._async_route_step("reconfigure", user_input)

    async def _async_route_step(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        subentry = (
            self._get_reconfigure_subentry() if step_id == "reconfigure" else None
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            unique_id = _route_unique_id(user_input)
            if user_input["from_location"] == user_input["to_location"]:
                errors["base"] = "same_station"
            elif subentry is not None and unique_id == subentry.unique_id:
                return self.async_update_and_abort(entry, subentry, data=user_input)
            elif any(
                other.unique_id == unique_id for other in entry.subentries.values()
            ):
                errors["base"] = "route_already_configured"
            elif subentry is None:
                return self.async_create_entry(
                    title=_route_title(user_input),
                    data=user_input,
                    unique_id=unique_id,
                )
            else:
                # Different stations are a new route. A reconfigure flow can't
                # create a subentry, so replace it directly.
                self.hass.config_entries.async_add_subentry(
                    entry,
                    ConfigSubentry(
                        data=MappingProxyType(user_input),
                        subentry_type="route",
                        title=_route_title(user_input),
                        unique_id=unique_id,
                    ),
                )
                self.hass.config_entries.async_remove_subentry(
                    entry, subentry.subentry_id
                )
                return self.async_abort(
                    reason="reconfigure_successful",
                    translation_domain=HOMEASSISTANT_DOMAIN,
                )

        try:
            schema = await self._async_route_schema(entry)
        except RateLimited:
            return self.async_abort(reason="rate_limited")
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")
        if subentry is not None:
            schema = self.add_suggested_values_to_schema(schema, subentry.data)
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    async def _async_route_schema(self, entry: ConfigEntry) -> probatio.Schema:
        try:
            stops = await entry.runtime_data.client.get_stops()
        except RTTRateLimitError as err:
            raise RateLimited from err
        except (RTTAPIError, httpx2.HTTPError) as err:
            raise CannotConnect from err
        stop_options = [
            SelectOptionDict(value=stop.short_code, label=stop.description)
            for stop in stops
            if stop.short_code
        ]
        return probatio.Schema(
            {
                probatio.Required("from_location"): SelectSelector(
                    SelectSelectorConfig(
                        options=stop_options,
                        mode=SelectSelectorMode.DROPDOWN,
                        sort=True,
                        custom_value=False,
                    )
                ),
                probatio.Required("to_location"): SelectSelector(
                    SelectSelectorConfig(
                        options=stop_options,
                        mode=SelectSelectorMode.DROPDOWN,
                        sort=True,
                        custom_value=False,
                    )
                ),
                probatio.Required("time_offset", default=0): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=MAX_TIME_OFFSET,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement=UnitOfTime.MINUTES,
                    )
                ),
                probatio.Required(CONF_HOURS_OF_INTEREST, default={}): section(
                    probatio.Schema(
                        {
                            probatio.Optional(
                                CONF_START_TIME, default=DEFAULT_START_TIME.isoformat()
                            ): TimeSelector(),
                            probatio.Optional(
                                CONF_END_TIME, default=DEFAULT_END_TIME.isoformat()
                            ): TimeSelector(),
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )


def _route_unique_id(data: dict[str, Any]) -> str:
    return f"{data['from_location']}_{data['to_location']}"


def _route_title(data: dict[str, Any]) -> str:
    return f"Route from {data['from_location']} to {data['to_location']}"


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class RateLimited(Exception):
    """Error to indicate the API rate limit was hit."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""
