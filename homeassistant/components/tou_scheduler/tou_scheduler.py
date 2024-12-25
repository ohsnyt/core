"""TOU Scheduler for Home Assistant."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import json
import logging
from zoneinfo import ZoneInfo

import aiofiles
import pandas as pd

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
    ON,
    SOLCAST_API_KEY,
    SOLCAST_RESOURCE_ID,
    SOLCAST_UPDATE_HOURS,
)
from .solark_inverter_api import InverterAPI
from .solcast_api import SolcastAPI

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
        self.timezone = hass.config.time_zone or "UTC"
        self.status = "Starting"

        # Here is the inverter info
        self.inverter_api: InverterAPI = InverterAPI()
        self.load_estimates: dict[str, dict[int, float]] = {}
        self.load_estimates_updated: date | None = None
        self.daily_load_averages: dict[int, float] = {}

        # Here is the solcast info
        self.solcast_api: SolcastAPI = SolcastAPI()
        self.solcast_api_key: str | None = None
        self.solcast_resource_id: str | None = None

        # Here is the shading info: default to 0.0 for each hour of the day and no last update date
        self.daily_shading: dict[int, float] = {hour: 0.0 for hour in range(24)}
        self._shading_startup: bool = True
        self._current_hour: int = 0  # This is the current hour of the day, used to update shading once per hour
        self._current_hour_pv: list[
            float
        ] = []  # This is the current hour's PV power, used to calculate average pv generation this hour
        self._shading_file: str = "shading_data.json"

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

        return {
            "status": self.status,
            "batt_time": self.batt_minutes_remaining / 60,
            "grid_boost_soc": self.grid_boost_starting_soc,
            "grid_boost_start": self.grid_boost_start,
            "grid_boost_on": self.grid_boost_on,
            "load_estimate": self.load_estimates.get(str(hour), {}).get(hour, 1000),
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
            "power_pv_estimated": self.solcast_api.get_current_hour_pv_estimate(),
            # Inverter info
            "inverter_model": self.inverter_api.inverter_model or "unknown",
            "inverter_status": str(self.inverter_api.inverter_status),
            "inverter_serial_number": self.inverter_api.inverter_serial_number
            or "unknown",
            # Plant info
            "plant_id": self.inverter_api.plant_id or "unknown",
            "plant_created": str(self.inverter_api.plant_created.date())
            if self.inverter_api.plant_created
            else "unknown",
            "plant_name": self.inverter_api.plant_name or "unknown",
            "plant_status": str(self.inverter_api.plant_status),
            "bearer_token_expires_on": str(
                self.inverter_api.bearer_token_expires_on.date()
                if self.inverter_api.bearer_token_expires_on
                else "unknown"
            ),
            # Shading data
            "shading": str(self.daily_shading),
            "load": str(self.daily_load_averages),
        }

    async def async_start(self) -> None:
        """Start the TOU Scheduler, making sure the inverter api and solcast api authenticate."""
        # First get the configuration entry data for authentication and setup
        entry_data = self.data.data
        # Set the timezone here, in the inverter_api, and solcast_api
        self.timezone = self.hass.config.time_zone or "UTC"
        self.inverter_api.timezone = self.timezone
        self.solcast_api.timezone = self.timezone

        # Setup the inverter api
        inverter_username = entry_data.get("username")
        inverter_password = entry_data.get("password")
        if inverter_username is None or inverter_password is None:
            logger.error("Inverter username or password is missing")
            return
        self.inverter_api.username = inverter_username
        self.inverter_api.password = inverter_password
        result = await self.inverter_api.authenticate()
        if result is False:
            logger.error("Inverter authentication failed")
            return
        result = await self.inverter_api.get_plant()
        if result is None:
            logger.error("Inverter plant data not found")
            return

        # Setup the solcast api
        api_key = entry_data.get(SOLCAST_API_KEY)
        resource_id = entry_data.get(SOLCAST_RESOURCE_ID)
        if api_key is None or resource_id is None:
            logger.error("Solcast API key or resource ID is missing")
            return
        self.solcast_api.api_key = api_key
        self.solcast_api.resource_id = resource_id
        self.inverter_api.grid_boost_midnight_soc = entry_data.get(
            GRID_BOOST_MIDNIGHT_SOC, DEFAULT_GRID_BOOST_MIDNIGHT_SOC
        )
        self.inverter_api.grid_boost_starting_soc = 25
        self.grid_boost_on = entry_data.get(GRID_BOOST_ON, DEFAULT_GRID_BOOST_ON)
        self.solcast_api.update_hours = entry_data.get(
            SOLCAST_UPDATE_HOURS, DEFAULT_SOLCAST_UPDATE_HOURS
        )
        # TEMP
        self.solcast_api.update_hours = [23]

        # Set status to indicate we are ready to work
        self.status = "Working"
        # Go get the data for the sensors
        await self.update_sensors()

    async def update_sensors(self) -> dict[str, int | float | str]:
        """Update the sensors with the latest data and return the updated sensor data as a dictionary."""
        # Update the inverter data for the sensors (done every 5 minutes)
        #   (This must be done first because the other updates depend on current inverter data, especially at startup)
        await self.inverter_api.refresh_data()

        # Check if we need to update the Solcast data (startup and as per user schedule)
        await self.solcast_api.refresh_data()
        # Update our daily shading values (various parts done at different schedules)
        await self._calculate_shading()
        # Update the hourly load estimates (once a day)
        await self._calculate_load_estimates()

        # Hourly based on the above daily information...
        #  ...compute remaining battery life and the grid boost SOC...
        #     ...and update the inverter if the grid boost SoC changes
        await self._calculate_tou_parameters()

        # Return the updated sensor data
        return self.to_dict()

    async def _calculate_shading(self) -> None:
        """Calculate the shading each hour.

        We will store the shading for each hour of the day in a dictionary. We write this
        to a file so we can load past shading if we restart Home Assistant.

        Each update we record changes to actual PV power generated. We use this to compute an average PV power for the hour.
        At the beginning of a new hour, we compute the past hour average PV power and compare it to the estimated PV power and
        the estimated amount of sun. If the sun was full and the battery was charging we can adjust the shading and write
        the adjusted shading info to a file, otherwise leave it alone.

        We then reset the average PV power to the first value for this hour. and repeat the process for the next hour.
        """

        # We can't do this without SolCast data
        if self.solcast_api is None:
            return

        # At startup, shading_update will be None. Go try to read the shading file.
        if self._shading_startup:
            try:
                async with aiofiles.open(self._shading_file, encoding="utf-8") as file:
                    file_content = await file.read()
                    shading = json.loads(file_content)
                    if not shading:
                        logger.info("No shading data available in the file at startup.")
                    else:
                        self.daily_shading = shading
                        logger.info("Shading file read at startup.")
            except FileNotFoundError:
                logger.warning("Shading file not found at startup.")
            except json.JSONDecodeError:
                logger.error("Error decoding shading file at startup.")
            # Set the current hour to the current hour of the day and show we have done the startup
            self._current_hour = datetime.now().hour
            self._shading_startup = False
        # If we are not at the start of a new hour, just record the current PV power generation
        if self._current_hour == datetime.now().hour:
            self._current_hour_pv.append(self.inverter_api.realtime_pv_power)
            return

        # We are at the start of a new hour. If we have data in the list, calculate the average PV power for the past hour, updating as needed
        if self._current_hour_pv:
            pv_average = sum(self._current_hour_pv) / len(self._current_hour_pv)
            # Reset the current hour PV power list
            self._current_hour_pv = [self.inverter_api.realtime_pv_power]
            # Update shading if we had a positive average PV power, battery soc is low enough to allow charging, and the sun was full
            if (
                pv_average > 0
                and self.solcast_api.get_current_hour_pv_estimate() > 0
                and self.inverter_api.realtime_battery_soc < 96
                and self.solcast_api.get_current_hour_sun_estimate() > 0.95
            ):
                shading = 1 - min(
                    pv_average / self.solcast_api.get_current_hour_pv_estimate(), 1
                )
                self.daily_shading[datetime.now().hour] = shading
                logger.info(
                    "Shading for %s changed to %s", datetime.now().hour, shading
                )
                # Write the shading to a file
                async with aiofiles.open(
                    self._shading_file, "w", encoding="utf-8"
                ) as file:
                    await file.write(json.dumps(self.daily_shading))

    async def _calculate_load_estimates(self) -> None:
        """Calculate the daily load averages once a day."""

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

        days_of_load_history = int(
            self.data.data.get(GRID_BOOST_HISTORY, DEFAULT_GRID_BOOST_HISTORY)
        )
        sensor = f"sensor.{self.inverter_api.plant_id}_tou_power_load"
        load_entity_ids = {sensor}
        history_data = await self._request_ha_statistics(
            load_entity_ids, days_of_load_history
        )

        data = []
        for data_list in history_data.values():
            for item in data_list:
                # Ensure that each item is valid
                if (
                    not isinstance(item, dict)
                    or "start" not in item
                    or "mean" not in item
                ):
                    logger.debug("Skipping invalid item: %s", item)
                    continue

                start_time = datetime.fromtimestamp(
                    item["start"], tz=ZoneInfo(self.inverter_api.timezone)
                )
                data.append({"hour": start_time.hour, "mean": item["mean"]})

        # Create DataFrame
        df = pd.DataFrame(data)
        logger.debug("Created DataFrame with columns: %s", df.columns.tolist())

        # Check if DataFrame is empty or missing columns
        if df.empty or "hour" not in df.columns or "mean" not in df.columns:
            logger.warning("No valid load data found. Skipping load estimates.")
            self.daily_load_averages = {hour: 1000.0 for hour in range(24)}
            return

        # Group by "hour" and get averages
        hourly_averages = df.groupby("hour")["mean"].mean().to_dict()
        self.daily_load_averages = {
            hour: hourly_averages.get(hour, 1000.0) for hour in range(24)
        }

        self.load_estimates_updated = datetime.now(
            ZoneInfo(self.inverter_api.timezone)
        ).date()

        # Log the results (optional)
        # logger.debug("Daily load averages: %s", self.daily_load_averages)

    async def _calculate_tou_parameters(self) -> None:
        """Calculate remaining battery life and grid boost SOC.

        Save and log any changes
        Update the inverter if the SoC changes.
        """

        if self.inverter_api is None:
            logger.error(
                "Cannot calculate battery life and grid boost. Inverter API is not set"
            )
            return

        # For each hour going forward, we need to calculate how long the battery will last until completely exhausted.
        # Set initial variables
        now = datetime.now(ZoneInfo(self.inverter_api.timezone))
        current_day = now.date()
        current_hour: int = now.hour
        starting_time = datetime.now(ZoneInfo(self.inverter_api.timezone)).strftime(
            "%a %-I %p"
        )
        batt_wh_usable = self.inverter_api.batt_wh_usable or 0
        minutes = 0
        efficiency = 100 / (self.inverter_api.efficiency or 95)
        boost_min_wh = self.inverter_api.grid_boost_wh_min or 0
        # During the grid boost range we can't go below the grid boost SoC amount.
        boost_range = range(
            int(self.grid_boost_start.split(":", maxsplit=1)[0]),
            int(self.inverter_api.grid_boost_end.split(":", maxsplit=1)[0]),
        )

        # Log for debugging
        logger.debug("------- Calculating remaining battery time -------")
        logger.debug(
            "Starting at %s with %s wH usable energy.",
            printable_hour(current_hour),
            batt_wh_usable,
        )

        while batt_wh_usable > 0:
            # Subtract load, add PV generation, subtract shading for the hour
            load = self.daily_load_averages.get(current_hour, 1000) / efficiency
            pv_forecast = self.solcast_api.forecast.get(
                f"{current_day}-{current_hour}", (0.0, 0.0)
            )
            pv = pv_forecast[0] if isinstance(pv_forecast, tuple) else pv_forecast
            shading = self.daily_shading.get(current_hour, 0.0)
            hour_impact = load + pv - pv * shading
            # Check if we are inside the grid boost hours. If so, we can't go below the grid boost amount
            if (
                current_hour in boost_range
                and self.grid_boost_on == ON
                and (batt_wh_usable - hour_impact) < boost_min_wh
            ):
                hour_impact += boost_min_wh - batt_wh_usable - hour_impact
            # Update battery life calculations.
            minutes += int(min(1, (batt_wh_usable / (hour_impact or 1))) * 60)
            batt_wh_usable = int(max(0, batt_wh_usable - hour_impact))
            # Monitor progress
            logger.debug(
                "%s battery energy was reduced by %.0f wH and now is %.0f wH.",
                printable_hour(current_hour),
                hour_impact,
                batt_wh_usable,
            )

            # Move to next hour
            current_hour = (current_hour + 1) % 24
            if current_hour == 0:
                current_day = current_day + timedelta(days=1)

        self.batt_minutes_remaining = minutes
        logger.info(
            "%s: %.1f remaining hours of battery life.",
            starting_time,
            round(minutes / 60, 1),
        )

        # DONE WITH CALCULATING BATTERY LIFE IN MINUTES
        # Calculate SOC required for grid boost for tomorrow
        # Initialize variables
        self.grid_boost_starting_soc = 25
        required_soc = self.grid_boost_starting_soc
        tomorrow = now.date() + timedelta(days=1)

        logger.debug(
            "--------- Calculating grid boost SoC for %s ---------",
            tomorrow.strftime("%A"),
        )

        # Calculate additional SOC needed to reach midnight
        logger.debug("Starting base SoC is %s%%", required_soc)
        logger.debug("Hour: PV - Shading - Load = Net Power | ± SoC = SoC")

        for hour in range(6, 23):
            # Calculate the load for the hour (multiplied by the efficiency factor)
            hour_load = self.daily_load_averages.get(int(hour), 1000) * efficiency
            hour_pv_forecast = self.solcast_api.forecast.get(
                f"{tomorrow}-{current_hour}", 0.0
            )
            hour_pv = (
                hour_pv_forecast[0] * 1000
                if isinstance(hour_pv_forecast, tuple)
                else hour_pv_forecast * 1000
            )
            hour_shading = self.daily_shading.get(hour, 0.0)
            hour_net_pv = hour_pv - hour_pv * (hour_shading)
            net_power = hour_net_pv - hour_load
            hour_soc = net_power / (self.inverter_api.batt_wh_per_percent or 1)
            required_soc -= int(hour_soc)
            logger.debug(
                "%s: %4.0f - %5.0f - %4.0f= %6.0f wH  | %2.1f%% = %2.1f%%",
                printable_hour(hour),
                hour_pv,
                hour_shading,
                hour_load,
                net_power,
                hour_soc,
                required_soc,
            )
            current_hour = (current_hour + 1) % 24
        # Add SOC reserved desired at midnight
        required_soc += self.data.data.get(
            GRID_BOOST_MIDNIGHT_SOC, DEFAULT_GRID_BOOST_MIDNIGHT_SOC
        )
        # Prevent required SoC from going above 100%
        required_soc = min(100, required_soc)

        # Make sure we start with the minimum morning SoC
        self.grid_boost_starting_soc = max(
            DEFAULT_GRID_BOOST_STARTING_SOC, required_soc
        )
        logger.debug(
            "Adjusting to have the minimum starting SoC, SoC changes to %.0f%%",
            self.grid_boost_starting_soc,
        )
        logger.debug("---------Done calculating grid boost SoC---------")

        # Log the grid boost SOC
        logger.info(
            "Grid boost SoC required to still have %s%% at midnight is %.0f%%.",
            self.inverter_api.grid_boost_midnight_soc,
            self.grid_boost_starting_soc,
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
            "Statistics for %s gathered from %s until %s.",
            entity_ids,
            start_time_utc.strftime("%a at %-I %p"),
            end_time_utc.strftime("%a at %-I %p"),
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
        f"{'\u00a0' if ((hour%12 < 10) and hour%12 > 0) else ''}"
        f"{(hour % 12) or 12}"
        f"{'am' if hour < 12 else 'pm'}"
    )
