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
            if self.username and self.password:
                timezone = self.hass.config.time_zone or "UTC"
                temp_inverter_api = InverterAPI(self.username, self.password, timezone)
                plant_id = await temp_inverter_api.test_authenticate()
                if plant_id is not None:
                    # We have successfully logged in. Move to the next step.
                    return await self.async_step_solcast_api()
                # If we get here, the login failed. Try to authenticate again.
                errors["base"] = "invalid_solark_auth"
            else:
                errors["base"] = "missing_credentials"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA_STEP_1, errors=errors
        )

    async def async_step_solcast_api(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Handle the second step of the config flow."""
        errors: dict[Any, Any] = {}
        if user_input is not None:
            self.api_key = user_input.get("api_key")
            self.resource_id = user_input.get("resource_id")
            if self.api_key and self.resource_id:
                # Test the new credentials
                timezone = self.hass.config.time_zone or "UTC"
                solcast = SolcastAPI(self.api_key, self.resource_id, timezone)
                await solcast.refresh_data()
                if solcast.status == SolcastStatus.UNKNOWN:
                    errors["base"] = "invalid_solcast_auth"
                else:
                    # If authentication is successful, proceed to the third step
                    return await self.async_step_parameters()
            else:
                errors["base"] = "missing_solcast_credentials"

        return self.async_show_form(
            step_id="solcast_api", data_schema=DATA_SCHEMA_STEP_2, errors=errors
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
                    "boost": user_input["boost"],
                    "manual_boost_soc": user_input["manual_boost_soc"],
                    "history_days": user_input["history_days"],
                    "forecast_hours": string_to_int_list(user_input["forecast_hours"]),
                    "min_battery_soc": user_input["min_battery_soc"],
                    "percentile": user_input["percentile"],
                },
            )

        # Try to get the forecast hours from the user input. If it is not there, use the default value.
        if user_input and user_input["forecast_hours"] is not None:
            forecast_hours = int_list_to_string(user_input["forecast_hours"])
        else:
            forecast_hours = int_list_to_string([23])

        return self.async_show_form(
            step_id="parameters",
            data_schema=vol.Schema(
                {
                    vol.Required("boost"): vol.In(["automated", "manual"]),
                    # Manual Settings
                    vol.Required("manual_boost_soc", default=55): vol.All(
                        vol.Coerce(int), vol.Range(min=5, max=100)
                    ),
                    # Automated Settings
                    vol.Required("history_days"): vol.In(
                        ["1", "2", "3", "4", "5", "6", "7"]
                    ),
                    vol.Required("forecast_hours", default=forecast_hours): str,
                    vol.Required("min_battery_soc", default=15): vol.All(
                        vol.Coerce(int), vol.Range(min=5, max=100)
                    ),
                    vol.Required("percentile", default=25): vol.All(
                        vol.Coerce(int), vol.Range(min=10, max=90)
                    ),
                }
            ),
        )

    # async def old_sync_step_parameters(
    #     self, user_input=None
    # ) -> config_entries.ConfigFlowResult:
    #     """Handle the third step of the config flow."""
    #     if user_input is not None:
    #         # Save the user input and create the config entry
    #         return self.async_create_entry(
    #             title="TOU Scheduler",
    #             data={
    #                 "username": self.username,
    #                 "password": self.password,
    #                 "api_key": self.api_key,
    #                 "resource_id": self.resource_id,
    #                 "history_days": user_input["history_days"],
    #                 "forecast_hours": user_input["forecast_hours"],
    #                 "min_battery_soc": user_input["min_battery_soc"],
    #                 "percentile": user_input["percentile"],
    #                 "boost_mode": user_input["boost_mode"],
    #             },
    #         )

    #     # Try to get the forecast hours from the user input. If it is not there, use the default value.
    #     if user_input and user_input["forecast_hours"] is not None:
    #         forecast_hours = int_list_to_string(user_input["forecast_hours"])
    #     else:
    #         forecast_hours = int_list_to_string([23])

    #     return self.async_show_form(
    #         step_id="parameters",
    #         data_schema=vol.Schema(
    #             {
    #                 vol.Required("boost_mode"): vol.In(["on", "off"]),
    #                 vol.Required("history_days"): vol.In(
    #                     ["1", "2", "3", "4", "5", "6", "7"]
    #                 ),
    #                 vol.Required("forecast_hours", default=forecast_hours): str,
    #                 vol.Required("min_battery_soc", default=15): vol.All(
    #                     vol.Coerce(int), vol.Range(min=5, max=100)
    #                 ),
    #                 vol.Required("percentile", default=25): vol.All(
    #                     vol.Coerce(int), vol.Range(min=10, max=90)
    #                 ),
    #             }
    #         ),
    #     )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow."""
        return TouSchedulerOptionFlow(config_entry)


def int_list_to_string(int_list) -> str:
    """Convert a list of integers to a string."""
    return ", ".join(map(str, int_list))


def string_to_int_list(string_list) -> list[int]:
    """Convert a string containing one or more integers into a list of ints."""
    return [int(i.strip()) for i in string_list.split(",") if i.strip().isdigit()]


class TouSchedulerOptionFlow(config_entries.OptionsFlow):
    """Handle TOU Scheduler options."""

    def __init__(self, config_entry) -> None:
        """Initialize options flow."""
        # Do we do anything here?

    async def async_step_init(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Redo the parameters step of the options flow."""
        if user_input is not None:
            # Save the user input and update the config entry options
            return self.async_create_entry(
                title="",
                data={
                    "manual_boost_soc": user_input["manual_boost_soc"],
                    "history_days": user_input["history_days"],
                    "forecast_hours": string_to_int_list(user_input["forecast_hours"]),
                    "min_battery_soc": user_input["min_battery_soc"],
                    "percentile": user_input["percentile"],
                    "boost_mode": user_input["boost"],
                },
            )

        # Try to get the forecast hours from the user input. If it is not there, use the default value.
        if user_input and user_input["forecast_hours"] is not None:
            forecast_hours = int_list_to_string(user_input["forecast_hours"])
        else:
            forecast_hours = int_list_to_string([23])

        options_schema = vol.Schema(
            {
                vol.Required("boost"): vol.In(["automated", "manual"]),
                # Manual Settings
                vol.Required("manual_boost_soc", default=55): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=100)
                ),
                # Automated Settings
                vol.Required("history_days"): vol.In(
                    ["1", "2", "3", "4", "5", "6", "7"]
                ),
                vol.Required("forecast_hours", default=forecast_hours): str,
                vol.Required("min_battery_soc", default=15): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=100)
                ),
                vol.Required("percentile", default=25): vol.All(
                    vol.Coerce(int), vol.Range(min=10, max=90)
                ),
            }
        )
        return self.async_show_form(data_schema=options_schema)

    # async def old_async_step_init(self, user_input=None) -> config_entries.ConfigFlowResult:
    #     """Redo the parameters step of the options flow."""
    #     if user_input is not None:
    #         # Save the user input and update the config entry options
    #         return self.async_create_entry(
    #             title="",
    #             data={
    #                 "history_days": user_input["history_days"],
    #                 "forecast_hours": string_to_int_list(user_input["forecast_hours"]),
    #                 "min_battery_soc": user_input["min_battery_soc"],
    #                 "percentile": user_input["percentile"],
    #                 "boost_mode": user_input["boost_mode"],
    #             },
    #         )

    #     # Try to get the forecast hours from the user input. If it is not there, use the default value.
    #     if user_input and user_input["forecast_hours"] is not None:
    #         forecast_hours = int_list_to_string(user_input["forecast_hours"])
    #     else:
    #         forecast_hours = int_list_to_string([23])

    #     options_schema = vol.Schema(
    #         {
    #             vol.Required("boost_mode"): vol.In(["on", "off"]),
    #             vol.Required("history_days"): vol.In(
    #                 ["1", "2", "3", "4", "5", "6", "7"]
    #             ),
    #             vol.Required("forecast_hours", default=forecast_hours): str,
    #             vol.Required("min_battery_soc", default=15): vol.All(
    #                 vol.Coerce(int), vol.Range(min=5, max=100)
    #             ),
    #             vol.Required("percentile", default=25): vol.All(
    #                 vol.Coerce(int), vol.Range(min=10, max=90)
    #             ),
    #         }
    #     )

    #     return self.async_show_form(data_schema=options_schema)


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
