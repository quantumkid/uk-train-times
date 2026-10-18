"""Config flow for the UK Train Times integration."""

import logging
from typing import Any

import probatio
from rtt_io_api import RTTClient
from rtt_io_api.exceptions import RTTAPIError

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_TOKEN, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
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


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> bool:
    """Validate the user input contains a usable API token."""
    client = RTTClient(refresh_token=data[CONF_API_TOKEN], base_url=RTT_API_BASE_URL)

    try:
        await client.get_access_token()  # Ensure we have a valid access token
    except RTTAPIError as e:
        raise InvalidAuth from e

    return True


class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UK Train Times."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_API_TOKEN][:16])
                return self.async_create_entry(title="UK Train Status", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_API_TOKEN_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the API token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
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
        errors: dict[str, str] = {}
        if user_input is not None:
            unique_id = _route_unique_id(user_input)
            if self._unique_id_in_use(unique_id):
                errors["base"] = "route_already_configured"
            else:
                return self.async_create_entry(
                    title=_route_title(user_input),
                    data=user_input,
                    unique_id=unique_id,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=await self._async_route_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of a route."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            unique_id = _route_unique_id(user_input)
            if unique_id == subentry.unique_id:
                return self.async_update_and_abort(
                    self._get_entry(), subentry, data=user_input
                )
            if self._unique_id_in_use(unique_id):
                errors["base"] = "route_already_configured"
            else:
                self.hass.config_entries.async_remove_subentry(
                    self._get_entry(), subentry.subentry_id
                )
                return self.async_create_entry(
                    title=_route_title(user_input),
                    data=user_input,
                    unique_id=unique_id,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                await self._async_route_schema(), subentry.data
            ),
            errors=errors,
        )

    def _unique_id_in_use(self, unique_id: str) -> bool:
        return any(
            other.unique_id == unique_id
            for other in self._get_entry().subentries.values()
        )

    async def _async_route_schema(self) -> probatio.Schema:
        client = self._get_entry().runtime_data.client
        stop_options = [
            SelectOptionDict(value=s.short_code, label=s.description)
            for s in await client.get_stops()
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


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""
