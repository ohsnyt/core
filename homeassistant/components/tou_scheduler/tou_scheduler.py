"""TOU Scheduler for Home Assistant."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import logging
import os
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

import pandas as pd

from homeassistant.components.recorder import get_instance, statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DEBUGGING,
    DEFAULT_GRID_BOOST_HISTORY,
    DEFAULT_GRID_BOOST_MIDNIGHT_SOC,
    DEFAULT_GRID_BOOST_START,
    DEFAULT_GRID_BOOST_STARTING_SOC,
    FORECAST_KEY,
    SHADE_KEY,
)
from .solark_inverter_api import InverterAPI
from .solcast_api import SolcastAPI

logger = logging.getLogger(__name__)
if DEBUGGING:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


def string_to_int_list(string_list) -> list[int]:
    """Convert a string containing one or more integers into a list of ints."""
    return [int(i.strip()) for i in string_list.split(",") if i.strip().isdigit()]


class TOUScheduler:
    """Class to manage Time of Use (TOU) scheduling for Home Assistant."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        timezone: str,
        inverter_api: InverterAPI,
        solcast_api: SolcastAPI,
    ) -> None:
        """Initialize the TOU Scheduler."""
        self.hass = hass
        self.config_entry = config_entry
        self.timezone = timezone
        self.status = "Starting"
        self.store_shade: Store = Store(hass, version=1, key=SHADE_KEY)
        self.store_forecast: Store = Store(hass, version=1, key=FORECAST_KEY)

        # Here is the inverter info
        self.inverter_api: InverterAPI = inverter_api
        self.load_estimates: dict[str, dict[int, float]] = {}
        self.load_estimates_updated: date | None = None
        self.daily_load_averages: dict[int, float] = {}

        # Here is the solcast info
        self.solcast_api: SolcastAPI = solcast_api

        # Here is the shading info: default to 0.0 for each hour of the day and no last update date
        self.daily_shading: dict[int, float] = {hour: 0.0 for hour in range(24)}
        self._current_hour: int = (
            datetime.now(ZoneInfo(self.timezone)).hour - 1
        )  # This is used to update some data once per hour
        self._shading_file_path = Path(os.path.dirname(__file__)) / "shading.data"

        # Here is the TOU boost info we will monitor and update
        self.batt_minutes_remaining: int = 0
        self.grid_boost_starting_soc: int = DEFAULT_GRID_BOOST_STARTING_SOC
        self.min_battery_soc: int = DEFAULT_GRID_BOOST_MIDNIGHT_SOC
        self.grid_boost_start: str = DEFAULT_GRID_BOOST_START
        self._boost: str = "testing"
        self.days_of_load_history: int = DEFAULT_GRID_BOOST_HISTORY
        self._update_tou_boost: bool = False

    def to_dict(self) -> dict[str, float | str]:
        """Return this sensor data as a dictionary.

        This method provides expected battery life statistics and the grid boost value for the upcoming day.
        It also returns the inverter_api data and the solcast_api data.

        Returns:
            dict[str, Any]: A dictionary containing the sensor data.

        """
        # Get the current hour
        hour = datetime.now(ZoneInfo(self.inverter_api.timezone)).hour

        return {
            "status": self._boost,
            "batt_time": self.batt_minutes_remaining / 60,
            "grid_boost_soc": self.grid_boost_starting_soc,
            "grid_boost_start": self.grid_boost_start,
            "grid_boost_on": self._boost,
            "load_estimate": self.load_estimates.get(str(hour), {}).get(hour, 1000),
            # Inverter data
            "data_updated": self.inverter_api.data_updated
            if self.inverter_api.data_updated
            else "unknown",
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
            "bearer_token_expires_on": str(
                self.inverter_api.bearer_token_expires_on.date()
                if self.inverter_api.bearer_token_expires_on
                else "unknown"
            ),
            # Daily data
            "shading": str(self.daily_shading),
            "load": str(self.daily_load_averages),
        }

    async def async_load_shading(self):
        """Load shading data from storage."""
        data = await self.store_shade.async_load()
        if data is not None:
            self.daily_shading = data

    async def async_save_shading(self):
        """Save shading data to storage."""
        await self.store_shade.async_save(self.daily_shading)

    async def async_load_forecast(self):
        """Load forecast data from storage."""
        data = await self.store_forecast.async_load()
        if data is not None:
            self.solcast_api.forecast = data

    async def async_save_forecast(self):
        """Save forecast data to storage."""
        await self.store_forecast.async_save(self.solcast_api.forecast)

    async def _hourly_updates(self) -> None:
        """Update the hourly data for the sensors after 10 past the hour."""
        # Check if we are at least 10 minutes past the hour
        current_time = datetime.now(ZoneInfo(self.timezone))
        if current_time.minute < 10:
            return

        # If we have already calculated shading for this hour, return
        if self._current_hour == current_time.hour:
            return

        # Update our daily shading values (various parts done at different schedules)
        await self._calculate_shading()

        #  Compute remaining battery life...
        await self._calculate_tou_battery_remaining_time()

        # Save the forecast data if it was updated and compute off-peak grid boost
        if self._update_tou_boost:
            await self.async_save_forecast()
            await self._calculate_tou_boost_soc()
            self._update_tou_boost = False

        self._current_hour = current_time.hour

    async def update_sensors(self) -> dict[str, int | float | str]:
        """Update the sensors with the latest data and return the updated sensor data as a dictionary."""
        # Set status to indicate we are working - May not be needed
        self.status = "Working"

        # Update the hourly load estimates (once a day)
        await self._calculate_load_estimates()

        # Update the inverter data for the sensors (done every 5 minutes)
        #   (This must be done first because the other updates depend on current inverter data, especially at startup)

        await self.inverter_api.refresh_data()

        # Try to update the Solcast data (true if successful at startup and as per user schedule)
        #  (Save the update flag for use in the hourly update)
        self._update_tou_boost = await self.solcast_api.refresh_data()

        # Do hourly updates
        await self._hourly_updates()

        # Return the updated sensor data
        return self.to_dict()

    async def async_start(self) -> None:
        """Set up the config options callback when starting the TOU Scheduler."""
        # Ensure config_entry is set
        if not self.config_entry:
            logger.error("Config entry is not set.")
            return

        # Load the shading data from storage
        await self.async_load_shading()
        # Load the forecast data from storage
        await self.async_load_forecast()
        if self.solcast_api.forecast:
            # Get the key with the lowest value
            lowest_key = min(self.solcast_api.forecast.keys())
            logger.debug(
                "First (lowest) key in forecast: %s -> %s", lowest_key, lowest_key
            )
            # Get the first period_end from the forecast data and set the data_updated date to this date
            self.solcast_api.data_updated = datetime.strptime(
                lowest_key, "%Y-%m-%d-%H"
            ) - timedelta(hours=1)
        # Try to read the shading file.
        # try:
        #     async with aiofiles.open(self._shading_file_path, encoding="utf-8") as file:
        #         file_content = await file.read()
        #         shading = json.loads(file_content)
        #         if not shading:
        #             logger.info("No shading data available in the file at startup.")
        #         else:
        #             self.daily_shading = {
        #                 int(hour): value for hour, value in shading.items()
        #             }
        #             logger.info("Shading file read at startup.")
        # except FileNotFoundError:
        #     logger.warning("Shading file not found at startup.")
        # except json.JSONDecodeError:
        #     logger.error("Error decoding shading file at startup.")

        # TEMP: Writing the shading data to the store
        await self.async_save_shading()

        # Load the options from the config entry
        if self.config_entry.options:
            await self._handle_options_dialog(self.hass, self.config_entry)
        # Listen for changes to the options and update the cloud object
        self.config_entry.add_update_listener(self._options_callback)

    async def _handle_options_dialog(
        self, hass: HomeAssistant, config_entry: ConfigEntry
    ) -> None:
        """Handle the options dialog."""
        # Process the options from the config entry
        options = config_entry.options
        logger.debug("Handling options dialog with options: %s", options)
        # Update the TOU Scheduler with the new options
        await self._async_update_options(options)

    async def _async_update_options(
        self, user_input: MappingProxyType[str, str | int]
    ) -> None:
        """Update the options and process the changes."""
        self.min_battery_soc = int(user_input.get("min_battery_soc", 25))
        self.grid_boost_starting_soc = int(
            user_input.get("grid_boost_starting_soc", 25)
        )
        self._boost = str(user_input.get("boost_mode", "testing"))
        self.solcast_api.update_hours = string_to_int_list(
            user_input.get("forecast_hours", "23")
        )
        self.days_of_load_history = int(user_input.get("history_days", 3))
        self.grid_boost_starting_soc = int(user_input.get("min_battery_soc", 10))
        self.inverter_api.manual_boost_soc = int(user_input.get("manual_boost_soc", 0))

        # Force an update of the sensors
        await self.update_sensors()

    async def _options_callback(
        self, hass: HomeAssistant, config_entry: ConfigEntry
    ) -> None:
        """Handle option updates callback."""
        logger.debug("Options updated: %s", config_entry.options)
        await self._handle_options_dialog(hass, config_entry)

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

        # Get the pv data for the current hour, calculate the average PV power for the past hour, updating as needed
        pv_average = await self._get_pv_statistic_for_last_hour()

        logger.debug(
            "Average PV power for the past hour: %s, current sun estimate is: %.2f",
            pv_average,
            self.solcast_api.get_current_hour_sun_estimate(),
        )
        # Update shading if we had a positive average PV power, battery soc is low enough to allow charging, and the sun was full
        last_hour = (datetime.now(ZoneInfo(self.timezone)).hour - 1) % 24
        if (
            pv_average > 0
            and self.solcast_api.get_current_hour_pv_estimate() > 0
            and self.inverter_api.realtime_battery_soc < 96
            and self.solcast_api.get_current_hour_sun_estimate() > 0.95
        ):
            shading = 1 - min(
                pv_average / self.solcast_api.get_current_hour_pv_estimate(), 1
            )
            self.daily_shading[last_hour] = shading
            logger.info(
                "Shading for %s changed to %s",
                last_hour,
                shading,
            )

            # Write the shading to the hass storage
            await self.async_save_shading()

            # Write the shading to a file
            # async with aiofiles.open(
            #     self._shading_file_path, "w", encoding="utf-8"
            # ) as file:
            #     await file.write(json.dumps(self.daily_shading))
            #     logger.info("Shading file updated.")
        self._current_hour = datetime.now(ZoneInfo(self.timezone)).hour

    async def _calculate_load_estimates(self) -> None:
        """Calculate the daily load averages once a day."""

        # Skip already done today
        if (
            self.load_estimates_updated is not None
            and self.load_estimates_updated
            == datetime.now(ZoneInfo(self.inverter_api.timezone)).date()
        ):
            return

        sensor = f"sensor.{self.inverter_api.plant_id}_tou_power_load"
        load_entity_ids = {sensor}
        history_data = await self._request_ha_statistics(
            load_entity_ids, self.days_of_load_history
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

    async def _calculate_tou_battery_remaining_time(self) -> None:
        """Calculate remaining battery life.

        Update the inverter if the SoC changes.
        """

        # For each hour going forward, we need to calculate how long the battery will last until completely exhausted.
        # Set initial variables
        now = datetime.now(ZoneInfo(self.inverter_api.timezone))
        day = now.date()
        hour: int = now.hour
        starting_time = datetime.now(ZoneInfo(self.inverter_api.timezone)).strftime(
            "%a %-I %p"
        )
        batt_wh_usable = float(self.inverter_api.batt_wh_usable or 0.0)
        minutes = 0
        boost_min_wh = self.inverter_api.batt_wh_per_percent * float(
            DEFAULT_GRID_BOOST_STARTING_SOC
        )
        # During the grid boost range we can't go below the grid boost SoC amount.
        boost_range = range(
            int(self.grid_boost_start.split(":", maxsplit=1)[0]),
            int(self.inverter_api.grid_boost_end.split(":", maxsplit=1)[0]),
        )

        # Log for debugging
        logger.debug("------- Calculating remaining battery time -------")
        logger.debug(
            "Starting at %s with %s wH usable energy.",
            printable_hour(hour),
            batt_wh_usable,
        )
        while batt_wh_usable > 0:
            # For each hour, calculate the impact of the solar generation and load.
            load = (
                self.daily_load_averages.get(hour, 1000) / self.inverter_api.efficiency
            )
            pv = (
                1000
                * self.solcast_api.forecast.get(f"{day}-{hour}", (0.0, 0.0))[0]
                * (1 - self.daily_shading.get(hour, 0.0))
            )
            batt_wh_usable = batt_wh_usable - load + pv
            if hour in boost_range and batt_wh_usable < boost_min_wh:
                batt_wh_usable = boost_min_wh
            logger.debug(
                "At %s battery energy is %6s wH.",
                printable_hour((hour + 1) % 24),
                f"{batt_wh_usable:6,.0f}",
            )
            # Monitor progress
            if batt_wh_usable > 0:
                minutes += 60
            else:
                minutes = minutes + int(batt_wh_usable / (pv - load)) * 60
            # Move to next hour
            hour = (hour + 1) % 24
            if hour == 0:
                day = day + timedelta(days=1)

        self.batt_minutes_remaining = minutes
        logger.info(
            "At %s: Estimating %.1f hours of battery life.",
            starting_time,
            minutes / 60,
        )

    async def _calculate_tou_boost_soc(self) -> None:
        """Calculate tomorrow off-peak grid boost required SoC.

        Save and log any changes
        Update the inverter with the new SoC.
        Log the results showing the impact of the changes.
        """

        # Initialize variables
        required_soc = float(DEFAULT_GRID_BOOST_STARTING_SOC)
        tomorrow = datetime.now(ZoneInfo(self.timezone)).date() + timedelta(days=1)
        # First we assume the lowest point of the battery will be the warning level, but at the end we will also compare to the desired midnight SoC
        lowest_point = float(-self.inverter_api.batt_low_warning)
        running_soc = 0.0

        # Do the initial calculation for the grid boost SoC
        for hour in range(6, 24):
            # Calculate the load for the hour (multiplied by the efficiency factor)
            load = (
                self.daily_load_averages.get(int(hour), 1000)
                * self.inverter_api.efficiency
            )
            pv = (
                1000
                * self.solcast_api.forecast.get(f"{tomorrow}-{hour}", (0.0, 0.0))[0]
                * (1 - self.daily_shading.get(hour, 0.0))
            )
            net_power = pv - load
            net_soc = net_power / (self.inverter_api.batt_wh_per_percent or 1)
            running_soc += net_soc
            lowest_point = min(lowest_point, running_soc)
        # Compare the lowest point to the final SoC less desired midnight SoC
        lowest_point = min(lowest_point, running_soc - self.min_battery_soc)
        soc = round(-lowest_point, 0)
        # Prevent required SoC from going above 100%
        required_soc = min(100, soc)
        # Save the new off-peak grid boost level
        self.grid_boost_starting_soc = int(round(required_soc, 0))

        # Test this new grid boost SoC to make sure we end up with the minimum SoC at midnight
        # Prepare the final results nicely for the user logs
        hyphen_format = "{:-^53}"
        logger.info(
            msg=hyphen_format.format(
                f"Off-peak charging for {tomorrow.strftime("%A")} starting at {self.grid_boost_starting_soc}% SoC"
            )
        )
        # Calculate additional SOC needed to reach midnight
        logger.info("Hour:    PV  Shade    Load   Net Power   ± SoC    SoC")

        for hour in range(6, 24):
            # Calculate the load for the hour (multiplied by the efficiency factor)
            hour_load = (
                self.daily_load_averages.get(int(hour), 1000)
                * self.inverter_api.efficiency
            )
            hour_pv_forecast = self.solcast_api.forecast.get(f"{tomorrow}-{hour}", 0.0)
            hour_pv = (
                hour_pv_forecast[0] * 1000
                if isinstance(hour_pv_forecast, tuple)
                else hour_pv_forecast * 1000
            )
            hour_shading = self.daily_shading.get(hour, 0.0)
            hour_net_pv = hour_pv - hour_pv * (hour_shading)
            net_power = hour_net_pv - hour_load
            hour_soc = net_power / (self.inverter_api.batt_wh_per_percent or 1)
            required_soc += hour_soc
            shade = int(round(hour_shading * 100, 2))
            logger.info(
                f"{printable_hour(hour)}: {hour_pv:5,.0f}  {shade:4d}%  {hour_load:6,.0f}  {net_power:7,.0f} wH   {hour_soc:4,.1f}%  {required_soc:4,.0f}%"  # noqa: G004
            )
        logger.info(msg=hyphen_format.format("Done calculating grid boost SoC"))

        # Write the new grid boost SoC to the inverter
        await self.inverter_api.write_grid_boost_soc(
            self._boost, self.grid_boost_starting_soc
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
        start_time = end_time - timedelta(days=int(days))

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

    async def _get_pv_statistic_for_last_hour(self) -> float:
        """Get the mean PV power for the last hour."""
        # Set the sensor entity_id and the start and end time to get the last hour's statistics
        entity_id = f"sensor.{self.inverter_api.plant_id}_tou_power_pv"
        now = datetime.now(ZoneInfo(self.inverter_api.timezone))
        start_of_last_hour = now.replace(minute=0, second=0, microsecond=0) - timedelta(
            hours=1
        )
        end_of_last_hour = (
            start_of_last_hour + timedelta(hours=1) - timedelta(microseconds=1)
        )

        # Get the statistics for the last hour
        stats = await get_instance(self.hass).async_add_executor_job(
            self._get_statistics_during_period,
            start_of_last_hour,
            end_of_last_hour,
            {entity_id},
        )

        # Extract the mean value for the entity_id
        mean_value = stats.get(entity_id, [{}])[0].get("mean", 0.0)
        logger.debug(
            ">>>>PV power generation at %s was %s wH<<<<",
            printable_hour(start_of_last_hour.hour),
            mean_value,
        )
        return mean_value

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
