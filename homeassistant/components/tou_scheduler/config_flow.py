"""Config flow for Time of Use Scheduler."""

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import callback

from .const import (  # Changed to relative import
    BOOST_OPTIONS,
    DEBUGGING,
    DEFAULT_GRID_BOOST_HISTORY,
    DEFAULT_GRID_BOOST_MIDNIGHT_SOC,
    DEFAULT_GRID_BOOST_ON,
    DEFAULT_SOLCAST_PERCENTILE,
    DEFAULT_SOLCAST_UPDATE_HOURS,
    DOMAIN,
    GRID_BOOST_HISTORY,
    GRID_BOOST_HISTORY_OPTIONS,
    GRID_BOOST_MIDNIGHT_SOC,
    GRID_BOOST_ON,
    GRID_BOOST_ON_OPTIONS,
    GRID_BOOST_SOC_HIGH,
    GRID_BOOST_SOC_LOW,
    SOLCAST_API_KEY,
    SOLCAST_PERCENTILE,
    SOLCAST_PERCENTILE_HIGH,
    SOLCAST_PERCENTILE_LOW,
    SOLCAST_RESOURCE_ID,
    SOLCAST_UPDATE_HOURS,
)
from .solark_inverter_api import InverterAPI  # Add this import
from .solcast_api import SolcastAPI, SolcastStatus

_logger = logging.getLogger(__name__)
if DEBUGGING:
    _logger.setLevel(logging.DEBUG)
else:
    _logger.setLevel(logging.INFO)


DATA_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,
    }
)


class TouSchedulerOptionFlow(OptionsFlow):
    """Handle options flow for our component."""

    def __init__(self) -> None:
        """Initialize options flow."""
        # Nothing to do here

    async def get_error_message(self, error_key):
        """Retrieve the error message associated with error_key from strings.json."""
        strings = await self.hass.helpers.translation.async_get_integration_strings(
            DOMAIN
        )
        return strings["error"][error_key]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the Grid Boost options."""

        _logger.debug("The async_step_init user input was: %s", user_input)
        errors: dict[str, str] = {}

        if user_input is not None:
            # TEMP: Check the user input for grid boost on/off
            grid_boost_on = user_input.get(GRID_BOOST_ON)
            # Check that both an api key and a resource id are present
            if not (api_key := user_input.get(SOLCAST_API_KEY)):
                errors[SOLCAST_API_KEY] = "invalid_keys"
            if not (resource_id := user_input.get(SOLCAST_RESOURCE_ID)):
                errors[SOLCAST_RESOURCE_ID] = "invalid_keys"
            # Check that the update hours are valid
            if solcast_hours := user_input.get(SOLCAST_UPDATE_HOURS):
                try:
                    sorted_hours = validate_update_hours(solcast_hours)
                    user_input[SOLCAST_UPDATE_HOURS] = string_to_int_list(sorted_hours)
                    solcast_hours = sorted_hours
                except ValueError:
                    errors[SOLCAST_UPDATE_HOURS] = "invalid_update_hours"
            # If we are good so far, check if the login credentials are valid
            if not errors:
                # Test the new credentials
                solcast = SolcastAPI()
                solcast.api_key = api_key
                solcast.resource_id = resource_id
                # If the credentials are good, make the temporary solcast instance the permanent one and update the other options
                await solcast.refresh_data()
                if solcast.status == SolcastStatus.UNKNOWN:
                    errors[SOLCAST_API_KEY] = "invalid_keys"
                    errors[SOLCAST_RESOURCE_ID] = "invalid_keys"
            # Last error check
            if not errors:
                # All is in order. Save the user input for the next time we need it.
                # Return the data.
                return self.async_create_entry(
                    title=BOOST_OPTIONS,
                    data=user_input,
                )

            # If we get here, there were errors. Show the form again with the user input and errors.
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {
                        vol.Optional(
                            SOLCAST_API_KEY, default=user_input.get(SOLCAST_API_KEY)
                        ): str,
                        vol.Optional(
                            SOLCAST_RESOURCE_ID,
                            default=user_input.get(SOLCAST_RESOURCE_ID),
                        ): str,
                        vol.Required(
                            SOLCAST_UPDATE_HOURS,
                            default=int_list_to_string(
                                user_input.get(SOLCAST_UPDATE_HOURS)
                            ),
                        ): str,
                        vol.Required(
                            GRID_BOOST_MIDNIGHT_SOC,
                            default=user_input.get(GRID_BOOST_MIDNIGHT_SOC),
                        ): vol.All(
                            vol.Coerce(int),
                            vol.Range(min=GRID_BOOST_SOC_LOW, max=GRID_BOOST_SOC_HIGH),
                        ),
                        vol.Required(
                            GRID_BOOST_HISTORY,
                            default=user_input.get(GRID_BOOST_HISTORY),
                        ): vol.In(GRID_BOOST_HISTORY_OPTIONS),
                        vol.Required(
                            SOLCAST_PERCENTILE,
                            default=user_input.get(SOLCAST_PERCENTILE),
                        ): vol.All(
                            vol.Coerce(int),
                            vol.Range(
                                min=SOLCAST_PERCENTILE_LOW, max=SOLCAST_PERCENTILE_HIGH
                            ),
                        ),
                        vol.Required(
                            GRID_BOOST_ON, default=user_input.get(GRID_BOOST_ON)
                        ): vol.In(GRID_BOOST_ON_OPTIONS),
                    }
                ),
                errors=errors,
            )
        # Initialize our variables.
        options = (
            self.config_entry.options if self.config_entry.options is not None else {}
        )
        api_key = options.get(SOLCAST_API_KEY, "")
        resource_id = options.get(SOLCAST_RESOURCE_ID, "")
        solcast_hours = int_list_to_string(
            self.config_entry.data.get(
                SOLCAST_UPDATE_HOURS, DEFAULT_SOLCAST_UPDATE_HOURS
            )
        )
        grid_boost_on = options.get(GRID_BOOST_ON, DEFAULT_GRID_BOOST_ON)
        grid_boost_history = options.get(GRID_BOOST_HISTORY, DEFAULT_GRID_BOOST_HISTORY)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(SOLCAST_API_KEY, default=api_key): str,
                    vol.Optional(SOLCAST_RESOURCE_ID, default=resource_id): str,
                    vol.Required(SOLCAST_UPDATE_HOURS, default=solcast_hours): str,
                    vol.Required(
                        GRID_BOOST_MIDNIGHT_SOC, default=DEFAULT_GRID_BOOST_MIDNIGHT_SOC
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=GRID_BOOST_SOC_LOW, max=GRID_BOOST_SOC_HIGH),
                    ),
                    vol.Required(
                        GRID_BOOST_HISTORY, default=grid_boost_history
                    ): vol.In(GRID_BOOST_HISTORY_OPTIONS),
                    vol.Required(
                        SOLCAST_PERCENTILE, default=DEFAULT_SOLCAST_PERCENTILE
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=SOLCAST_PERCENTILE_LOW, max=SOLCAST_PERCENTILE_HIGH
                        ),
                    ),
                    vol.Required(GRID_BOOST_ON, default=grid_boost_on): vol.In(
                        GRID_BOOST_ON_OPTIONS
                    ),
                }
            ),
            errors=errors,
        )


class TOUSchedulerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TOU Scheduler.

    Notes:
    Need to set up the config flow for the TOU Scheduler integration. This includes getting the solark login credentials,
    the solcast api key and resource id, etc.

    """

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TouSchedulerOptionFlow:
        """Get the options flow."""
        _logger.debug("Passing handler to TouSchedulerOptionFlow")
        # return TouSchedulerOptionFlow(config_entry)
        return TouSchedulerOptionFlow()

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.username: str | None = None
        self.password: str | None = None
        self.plant_id: str | None = None

    async def async_step_user(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Start here. Allow only one instance of the cloud."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        # First time in present the user with a form to enter their username and password.
        errors: dict[Any, Any] = {}
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=DATA_SCHEMA, errors=errors
            )

        # Now that we have a username and password, we can try to authenticate with the inverter cloud and get the plant list.
        temp_inverter_api = InverterAPI()
        temp_inverter_api.username = user_input.get("username")
        temp_inverter_api.password = user_input.get("password")
        if await temp_inverter_api.authenticate():
            # We have successfully logged in. Get the plant list.
            return self.async_create_entry(
                title="Sol-Ark Plant",
                data={
                    "username": self.username,
                    "password": self.password,
                },
            )
        # If we get here, the login failed. Try to authenticate again.
        errors["base"] = "login_failed"
        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_plant(
        self, plants, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Ask the user to select which plant to use. We only get here if there is more than one plant in the cloud account."""
        errors: dict[str, str] = {}
        # First time in, present the user with a form to select the plant they want to monitor.
        if user_input is None:
            # Create a schema for the form and show the form
            plant_schema = vol.Schema({vol.Required("plant"): vol.In(plants)})
            return self.async_show_form(
                step_id="plant", data_schema=plant_schema, errors=errors
            )

        # Second time in this function, we grab the plant id and return it.
        return self.async_create_entry(
            title="Sol-Ark Plant",
            data={
                "username": self.username,
                "password": self.password,
                "plant_id": user_input.get("plant", None),
            },
        )


def validate_update_hours(value):
    """Validate the update hours list since voluptous cannot work with a list."""
    hours = string_to_int_list(value)
    hours.sort()
    if len(hours) < 1 or len(hours) > 10:
        raise vol.Invalid("Invalid number of hours (must be between 1 and 10)")
    for hour in hours:
        if hour < 0 or hour > 23:
            raise vol.Invalid("Invalid hour value")
    # Return back in the same format
    return int_list_to_string(hours)


def int_list_to_string(int_list) -> str:
    """Convert a list of integers to a string."""
    return ", ".join(map(str, int_list))


def string_to_int_list(string_list) -> list[int]:
    """Convert a string containing one or more integers into a list of ints."""
    return [int(i.strip()) for i in string_list.split(",") if i.strip().isdigit()]
