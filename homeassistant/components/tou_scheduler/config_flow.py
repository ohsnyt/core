"""Config flow for Time of Use Scheduler."""

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN
from .solark_inverter_api import InverterAPI  # Add this import
from .solcast_api import SolcastAPI, SolcastStatus

_logger = logging.getLogger(__name__)


def validate_forecast_hours(value):
    """Validate that the value is a list of 1-4 integers in the range 0-23."""
    if not isinstance(value, list):
        raise vol.Invalid("Must be a list")
    if not (1 <= len(value) <= 4):
        raise vol.Invalid("List must contain between 1 and 4 items")
    for item in value:
        if not isinstance(item, int) or not (0 <= item <= 23):
            raise vol.Invalid("Each item must be an integer between 0 and 23")
    return value


DATA_SCHEMA_STEP_1 = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,
    }
)

DATA_SCHEMA_STEP_2 = vol.Schema(
    {
        vol.Required("api_key"): str,
        vol.Required("resource_id"): str,
    }
)

DATA_SCHEMA_STEP_3 = vol.Schema(
    {
        vol.Required("boost_calculation"): vol.In(["on", "off"]),
        vol.Required("history_days"): vol.In(["1", "2", "3", "4", "5", "6", "7"]),
        vol.Required("forecast_hours"): vol.All(
            vol.Coerce(list), validate_forecast_hours
        ),
        vol.Required("min_battery_soc", default=15): vol.All(
            vol.Coerce(int), vol.Range(min=5, max=100)
        ),
        vol.Required("percentile", default=25): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=90)
        ),
    }
)


class TOUSchedulerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TOU Scheduler."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.username: str | None = None
        self.password: str | None = None
        self.api_key: str | None = None
        self.resource_id: str | None = None

    async def async_step_user(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Handle the first step of the config flow."""
        errors: dict[Any, Any] = {}
        if user_input is not None:
            # Try to authenticate and get the plant id. If we get the plant id, we are good to go.
            self.username = user_input.get("username")
            self.password = user_input.get("password")
            temp_inverter_api = InverterAPI()
            temp_inverter_api.username = self.username
            temp_inverter_api.password = self.password
            plant_id = await temp_inverter_api.test_authenticate()
            if plant_id is not None:
                # We have successfully logged in. Move to the next step.
                return await self.async_step_solcast_api()
            # If we get here, the login failed. Try to authenticate again.
            errors["invalid_solark_auth"] = "MySolark login_failed"
            return self.async_show_form(
                step_id="user", data_schema=DATA_SCHEMA_STEP_1, errors=errors
            )

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA_STEP_1)

    async def async_step_solcast_api(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Handle the second step of the config flow."""
        errors: dict[Any, Any] = {}
        if user_input is not None:
            self.api_key = user_input["api_key"]
            self.resource_id = user_input["resource_id"]
            # Test the new credentials
            solcast = SolcastAPI()
            solcast.api_key = self.api_key
            solcast.resource_id = self.resource_id
            # If the credentials are good, make the temporary solcast instance the permanent one and update the other options
            await solcast.refresh_data()
            if solcast.status == SolcastStatus.UNKNOWN:
                errors["invalid_solcast_auth"] = "Solcast API login failed"

            # If authentication is successful, proceed to the third step
            return await self.async_step_parameters()

        return self.async_show_form(
            step_id="solcast_api", data_schema=DATA_SCHEMA_STEP_2
        )

    async def async_step_parameters(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Handle the third step of the config flow."""
        if user_input is not None:
            # Save the user input and create the config entry
            return self.async_create_entry(
                title="TOU Scheduler",
                data={
                    "username": self.username,
                    "password": self.password,
                    "api_key": self.api_key,
                    "resource_id": self.resource_id,
                    "forecast_hours": user_input["forecast_hours"],
                    "min_battery_soc": user_input["min_battery_soc"],
                    "percentile": user_input["percentile"],
                    "boost_calculation": user_input["boost_calculation"],
                },
            )

        return self.async_show_form(
            step_id="parameters", data_schema=DATA_SCHEMA_STEP_3
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow."""
        return TouSchedulerOptionFlow(config_entry)


class TouSchedulerOptionFlow(config_entries.OptionsFlow):
    """Handle TOU Scheduler options."""

    def __init__(self, config_entry) -> None:
        """Initialize options flow."""
        # Do we do anything here?

    async def async_step_init(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "grid_boost_on",
                        default=self.config_entry.options.get("grid_boost_on", "off"),
                    ): vol.In(["on", "off"]),
                }
            ),
        )
