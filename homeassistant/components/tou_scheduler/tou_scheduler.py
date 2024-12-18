"""TOU Scheduler for Home Assistant."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import logging
from math import ceil
from zoneinfo import ZoneInfo

from homeassistant.components.recorder import get_instance, statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DEBUGGING,
    DEFAULT_GRID_BOOST_HISTORY,
    DEFAULT_GRID_BOOST_MIDNIGHT_SOC,
    DEFAULT_GRID_BOOST_ON,
    DEFAULT_GRID_BOOST_START,
    DEFAULT_GRID_BOOST_STARTING_SOC,
    DEFAULT_SOLCAST_UPDATE_HOURS,
    GRID_BOOST_HISTORY,
    GRID_BOOST_MIDNIGHT_SOC,
    GRID_BOOST_ON,
    GRID_BOOST_STARTING_SOC,
    ON,
    SOLCAST_API_KEY,
    SOLCAST_RESOURCE_ID,
    SOLCAST_UPDATE_HOURS,
)
from .solark_inverter_api import InverterAPI
from .solcast_api import SolcastAPI, SolcastStatus

logger = logging.getLogger(__name__)
if DEBUGGING:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


class TOUScheduler:
    """Class to manage Time of Use (TOU) scheduling for Home Assistant."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the TOU Scheduler."""
        self.hass = hass
        self.data = entry
        # self.dashboard_card = DashboardCard()
        self.timezone = hass.config.time_zone or "UTC"

        # Here is the inverter info
        self.inverter_api: InverterAPI = InverterAPI()
        self.load_estimates: dict[str, dict[int, float]] = {}
        self.load_estimates_updated: date | None = None
        self.daily_load_averages: dict[int, float] = {}

        # Here is the solcast info
        self.solcast_api: SolcastAPI = SolcastAPI()
        self.solcast_api_key: str | None = None
        self.solcast_resource_id: str | None = None

        # Here is the pv estimate info
        self.pv_estimate: dict[str, float] = {}

        # Here is the shading info: default to 0.0 for each hour of the day and no last update date
        self.shading: dict[int, float] = {hour: 0.0 for hour in range(24)}
        self.shading_updated: date | None = None

        # Here is the TOU boost info we will monitor and update
        self.batt_minutes_remaining: int = 0
        self.grid_boost_starting_soc: int = DEFAULT_GRID_BOOST_STARTING_SOC
        self.grid_boost_start: str = DEFAULT_GRID_BOOST_START
        self.grid_boost_on: str = DEFAULT_GRID_BOOST_ON

    def to_dict(self) -> dict[str, float | str]:
        """Return this sensor data as a dictionary.

        This method provides expected battery life statistics and the grid boost value for the upcoming day.
        It also returns the inverter_api data and the solcast_api data.

        Returns:
            dict[str, Any]: A dictionary containing the sensor data.

        """
        logger.debug("Returning ToU sensor data as dict")

        # Get the current hour
        if self.inverter_api and self.inverter_api.timezone:
            hour = datetime.now(ZoneInfo(self.inverter_api.timezone)).hour
        else:
            logger.error("Inverter API or timezone is not set")
            return {}

        # Get the current hour
        now = datetime.now(ZoneInfo(self.timezone))
        current_hour = f"{now.date()}-{now.hour}"

        return {
            "battery_minutes": self.batt_minutes_remaining,
            "grid_boost_soc": self.grid_boost_starting_soc,
            "grid_boost_start": self.grid_boost_start,
            "grid_boost_on": self.grid_boost_on,
            "load_estimate": self.load_estimates.get(str(hour), {}).get(hour, 0),
            # Inverter data
            "data_updated": self.inverter_api.data_updated
            if self.inverter_api.data_updated
            else "unknown",
            "cloud_name": self.inverter_api.cloud_name,
            "batt_wh_usable": self.inverter_api.batt_wh_usable or "0",
            "batt_soc": self.inverter_api.realtime_battery_soc,
            "power_battery": self.inverter_api.realtime_battery_power,
            "power_grid": self.inverter_api.realtime_grid_power,
            "power_load": self.inverter_api.realtime_load_power,
            "power_pv": self.inverter_api.realtime_pv_power,
            # Inverter info
            "inverter_model": self.inverter_api.inverter_model or "unknown",
            "inverter_status": str(self.inverter_api.inverter_status),
            "inverter_serial_number": self.inverter_api.inverter_serial_number
            or "unknown",
            # Plant info
            "plant_id": self.inverter_api.plant_id or "unknown",
            "plant_created": str(self.inverter_api.plant_created)
            if self.inverter_api.plant_created
            else "unknown",
            "plant_name": self.inverter_api.plant_name or "unknown",
            "plant_status": str(self.inverter_api.plant_status),
            # Solcast data
            "power_pv_estimated": self.solcast_api.get_current_hour_pv_estimate(
                current_hour
            ),
            "sun": self.solcast_api.get_current_hour_sun_estimate(current_hour),
            # Shading data
            "shading": str(self.shading),
        }

    def authenticate(self) -> None:
        """Start the TOU Scheduler."""
        # First save the entry data
        entry_data = self.data.data
        entry_options = self.data.options
        # Get username and password from configuration, if missing log an error and return
        inverter_username = entry_data.get("username")
        inverter_password = entry_data.get("password")
        if inverter_username is None or inverter_password is None:
            logger.error("Inverter username or password is missing")
            return
        # Set inverter key variables
        self.inverter_api.username = inverter_username
        self.inverter_api.password = inverter_password
        self.inverter_api.plant_id = entry_data.get("plant_id") or "unknown"
        self.inverter_api.timezone = self.timezone or "UTC"

        # Set ToU variables from the options in the configuration
        self.inverter_api.grid_boost_midnight_soc = entry_options.get(
            GRID_BOOST_MIDNIGHT_SOC, DEFAULT_GRID_BOOST_MIDNIGHT_SOC
        )
        self.inverter_api.grid_boost_starting_soc = entry_options.get(
            GRID_BOOST_STARTING_SOC, DEFAULT_GRID_BOOST_STARTING_SOC
        )
        self.grid_boost_on = entry_options.get(GRID_BOOST_ON, DEFAULT_GRID_BOOST_ON)

        # Get the Solcast API key and resource ID from configuration, if missing log an error and return
        api_key = entry_options.get(SOLCAST_API_KEY)
        resource_id = entry_options.get(SOLCAST_RESOURCE_ID)
        if api_key is None or resource_id is None:
            logger.error("Solcast API key or resource ID is missing")
            return

        # Set remaining Solcast variables from the options in the configuration
        self.solcast_api.api_key = api_key
        self.solcast_api.resource_id = resource_id
        self.solcast_api.timezone = self.timezone or "UTC"
        self.solcast_api.update_hours = entry_options.get(
            SOLCAST_UPDATE_HOURS, DEFAULT_SOLCAST_UPDATE_HOURS
        )

    async def async_start(self) -> None:
        """Start the TOU Scheduler, making sure the inverter api and solcast api authenticate."""
        if await self.inverter_api.authenticate() is False:
            logger.error("Inverter authentication failed")
            return
        await self.inverter_api.get_plant()
        await self.solcast_api.refresh_data()
        if self.solcast_api.status == SolcastStatus.NOT_CONFIGURED:
            logger.error("Solcast API key or resource ID is missing")
            return

    async def update_sensors(self) -> dict[str, int | float | str]:
        """Update the sensors with the latest data and return the updated sensor data as a dictionary."""
        # Update the inverter data
        await self.inverter_api.refresh_data()

        # Update the Solcast data
        await self.solcast_api.refresh_data()

        # Make sure we have the up-to-date forecast data from Solcast
        await self.solcast_api.refresh_data()

        # Make sure we have shading data for today
        await self._calculate_shading()

        # Make sure we have the hourly load averages for today
        await self._calculate_load_estimates()

        # Based on expected pv, shading, and load averages, compute remaining battery life and the grid boost SOC, logging any changes and updating the inverter
        await self.calculate_tou_parameters()

        return self.to_dict()

    async def _calculate_shading(self) -> None:
        """Calculate the shading for the past day.

        We do this once a day after midnight.
        """
        # Skip if not at startup or already done today
        if (
            self.shading_updated is not None
            and self.inverter_api is not None
            and self.shading_updated
            == datetime.now(ZoneInfo(self.inverter_api.timezone)).date()
        ):
            return

        # Get the past 1 day of pv estimate, actual pv, sun, and battery state of charge data
        load_entity_ids = {
            "sensor.solcast_estimated_pv_power",
            "sensor.solcast_sun",
            "sensor.solark_pv_power",
            "sensor.solark_battery_state_of_charge",
        }
        history_data = await self._request_ha_statistics(load_entity_ids, 1)

        # For each hour of the past 24 hours, calculate the shading and update the shading dict
        for hour in range(24):
            try:
                # Get values with defaults if missing
                sun_status = history_data.get("sensor.solcast_sun", {}).get(
                    hour, "unknown"
                )
                battery_soc = history_data.get(
                    "sensor.solark_battery_state_of_charge", {}
                ).get(hour, 100)
                pv_power = history_data.get("sensor.solark_pv_power", {}).get(hour, 0)
                estimated_pv = history_data.get(
                    "sensor.solcast_estimated_pv_power", {}
                ).get(hour, 0)

                # If the sun was full and the battery was charging we can adjust the shading, otherwise leave it alone
                if sun_status == "full" and battery_soc < 96:
                    # Avoid division by zero, should never happen
                    if estimated_pv > 0:
                        shading = 1.0 - min(pv_power / estimated_pv, 1.0)
                        log_message = (
                            "remained at"
                            if self.shading.get(hour) == shading
                            else "changed to"
                        )
                        logger.info(
                            "Shading for %s %s %s",
                            printable_hour(hour),
                            log_message,
                            shading,
                        )
                        self.shading[hour] = shading
                    else:
                        shading = 1.0
                        logger.warning(
                            "Hour %s: Estimated PV power is zero or missing",
                            printable_hour(hour),
                        )

            except KeyError as e:
                logger.error(
                    "KeyError processing hour %s: %s", printable_hour(hour), str(e)
                )
            except TypeError as e:
                logger.error(
                    "TypeError processing hour %s: %s", printable_hour(hour), str(e)
                )
            except ValueError as e:
                logger.error(
                    "ValueError processing hour %s: %s", printable_hour(hour), str(e)
                )

    async def _calculate_load_estimates(self) -> None:
        """Calculate the daily load averages."""

        if self.inverter_api is None:
            logger.error("Cannot calculate load estimates. Inverter API is not set")
            return

        # Skip if not at startup or already done today
        if (
            self.load_estimates_updated is not None
            and self.load_estimates_updated
            == datetime.now(ZoneInfo(self.inverter_api.timezone)).date()
        ):
            return

        # Get the past GRID_BOOST_HISTORY number of days of load data
        days_of_load_history = self.data.data.get(
            GRID_BOOST_HISTORY, DEFAULT_GRID_BOOST_HISTORY
        )
        load_entity_ids = {
            "sensor.solark_load_power",
        }
        history_data = await self._request_ha_statistics(
            load_entity_ids, days_of_load_history
        )

        # For each hour of the past 24 hours, calculate the average load and update the daily load averages dict
        for hour in range(24):
            try:
                # Get the load power with a default of 0
                load_power = history_data.get("sensor.solark_load_power", {}).get(
                    hour, 0
                )

                # Update the daily load averages dict
                self.daily_load_averages[hour] = load_power

            except KeyError as e:
                logger.error(
                    "KeyError processing hour %s: %s", printable_hour(hour), str(e)
                )
                # Set default load power value
                self.daily_load_averages[hour] = 0
            except TypeError as e:
                logger.error(
                    "TypeError processing hour %s: %s", printable_hour(hour), str(e)
                )
                # Set default load power value
                self.daily_load_averages[hour] = 0
            except ValueError as e:
                logger.error(
                    "ValueError processing hour %s: %s", printable_hour(hour), str(e)
                )
                # Set default load power value
                self.daily_load_averages[hour] = 0

    async def calculate_tou_parameters(self) -> None:
        """Calculate remaining battery life and grid boost SOC.

        Save and log any changes
        Update the inverter if the SoC changes.
        """

        if self.inverter_api is None:
            logger.error(
                "Cannot calculate battery life and grid boost. Inverter API is not set"
            )
            return

        logger.debug("Calculating remaining battery time")

        # Get the current hour
        now = datetime.now(ZoneInfo(self.inverter_api.timezone))
        current_day = now.date()
        current_hour = now.hour

        # Get the current usable battery power
        batt_wh_usable = self.inverter_api.batt_wh_usable or 0
        # Get the minimum amount of battery power we want to keep in reserve
        midnight_soc = self.data.data.get(
            GRID_BOOST_MIDNIGHT_SOC, DEFAULT_GRID_BOOST_MIDNIGHT_SOC
        )

        # For each hour going forward, we need to calculate how long the battery will last.
        minutes = 0
        while batt_wh_usable and batt_wh_usable > 0:
            # Calculate battery life remaining
            hour_impact = int(
                self.daily_load_averages.get(current_hour, 0)
                * (1 / (self.inverter_api.efficiency or 1))
            )
            key = f"{current_day}-{current_hour}"
            hour_impact += int(
                self.pv_estimate.get(key, 0.0)
                * (1 - self.shading.get(current_hour, 0.0))
            )

            # Check if grid boost is needed
            if (
                current_hour
                in range(
                    int(self.grid_boost_start.split(":", maxsplit=1)[0]),
                    int(self.inverter_api.grid_boost_end.split(":", maxsplit=1)[0]),
                )
                and self.grid_boost_on == ON
            ):
                if (batt_wh_usable - hour_impact) < (
                    self.inverter_api.grid_boost_wh_min or 0
                ):
                    hour_impact += (self.inverter_api.grid_boost_wh_min or 0) - (
                        batt_wh_usable - hour_impact
                    )

            # Update battery life calculations
            minutes += int(
                (max(1, (batt_wh_usable / (hour_impact or 1))) * 60)
                if hour_impact > 0
                else 60
            )
            batt_wh_usable -= hour_impact

            logger.debug(
                "Battery life remaining at %s is %s",
                printable_hour(datetime.now(ZoneInfo(self.timezone)).hour),
                batt_wh_usable,
            )

            # Move to next hour
            current_hour = (current_hour + 1) % 24
            if current_hour == 0:
                current_day = current_day + timedelta(days=1)

            self.batt_minutes_remaining = minutes

            # Calculate SOC required for grid boost
            if minutes > (24 - now.hour) * 60:
                self.grid_boost_starting_soc = int(midnight_soc)
                return

            # Calculate additional SOC needed to reach midnight
            additional_soc = 0
            if current_hour > 0:
                for hour in range(current_hour - 1, 23):
                    additional_soc += ceil(
                        self.daily_load_averages[hour]
                        * 1
                        / (self.inverter_api.efficiency or 1)
                        / (self.inverter_api.batt_wh_per_percent or 1)
                    )
                    current_hour = (current_hour + 1) % 24

            # Add SOC for last hour of day
            additional_soc += ceil(
                self.daily_load_averages[23]
                * 1
                / (self.inverter_api.efficiency or 1)
                / (self.inverter_api.batt_wh_per_percent or 1)
            )

    async def _request_ha_statistics(
        self, entity_ids: set[str], days: int
    ) -> defaultdict:
        """Request the mean hourly statistics for the given entity_id using units unit for the number of days specified.

        This uses a background task to prevent thread blocking.
        """
        # Initialize the start and end date range for yesterday
        if self.inverter_api is None:
            logger.error("Cannot request HA statistics. Inverter API is not set")
            return defaultdict()

        now = datetime.now(ZoneInfo(self.inverter_api.timezone))
        end_time = datetime.combine(now.date(), datetime.min.time()).replace(
            tzinfo=ZoneInfo(self.inverter_api.timezone)
        )
        start_time = end_time - timedelta(days=days)

        # Convert start_time and end_time to UTC
        start_time_utc = start_time.astimezone(ZoneInfo("UTC"))
        end_time_utc = end_time.astimezone(ZoneInfo("UTC"))

        # Log the request
        logger.debug(
            "Yesterday started at:%s, and ended at:%s.",
            start_time_utc.strftime("%A, %H:%M"),
            end_time_utc.strftime("%A, %H:%M"),
        )

        return await get_instance(self.hass).async_add_executor_job(
            self._get_statistics_during_period,
            start_time_utc,
            end_time_utc,
            entity_ids,
        )

    def _get_statistics_during_period(
        self,
        start_time: datetime,
        end_time: datetime,
        entity_ids: set[str],
    ) -> defaultdict:
        """Get statistics during the specified period."""
        stats = statistics.statistics_during_period(
            self.hass,
            start_time,
            end_time,
            entity_ids,
            "hour",
            None,
            {"mean"},
        )
        return defaultdict(list, stats)


def printable_hour(hour: int) -> str:
    """Return a printable hour string in 12-hour format with 'am' or 'pm' suffix.

    Args:
        hour: Hour in 24-hour format (0-23).

    Returns:
        Formatted string in 12-hour format with am/pm.

    """
    return (
        f"{'\u00a0' if (hour%12 < 10 and hour > 0) else ''}"
        f"{(hour % 12) or 12}"
        f"{'am' if hour < 12 else 'pm'}"
    )
