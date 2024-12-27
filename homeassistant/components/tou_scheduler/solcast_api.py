"""Classes for Solcast API calls and calculations for Sol-Ark inverter integration.

This module contains:

Classes:
    SolcastEstimator: Handles the integration with the Solcast API to estimate PV generation for tomorrow.
                      It saves raw data to a file and processes it to estimate PV generation, avoiding API rate limits.
                      It also saves damping factors to a file for recall after reboots.
    SolcastStatus: Enum representing the status of the Sol-Ark Inverter, including API faults, normal operation,
                   configuration status, and read errors.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from enum import Enum
import json
import logging
import os
from zoneinfo import ZoneInfo

import aiofiles
import aiohttp
import pandas as pd

from .const import (
    DEBUGGING,
    DEFAULT_SOLCAST_PERCENTILE,
    DEFAULT_SOLCAST_UPDATE_HOURS,
    TIMEOUT,
)

logger = logging.getLogger(__name__)
if DEBUGGING:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


class SolcastAPI:
    """Class to handle Solcast API calls and data processing for the Time of Use integration."""

    def __init__(self, api_key: str, resource_id: str, timezone: str) -> None:
        """Initialize key variables for API calls and data calculations.

        Args:
            api_key (str): The API key for Solcast.
            resource_id (str): The resource ID for Solcast.
            timezone (str): The timezone for the location of the solar installation.

        This method sets up the necessary variables to estimate solar activity using Solcast.com.

        """
        # General info
        self._api_key: str = api_key
        self._resource_id: str = resource_id
        self.timezone: str = timezone

        self.status = SolcastStatus.UNKNOWN
        self.data_updated: datetime | None = None
        # forecast is a dictionary of kWh hourly estimates with the date/hour as the key and the value as a tuple of float and bool.
        self.forecast: dict[str, tuple[float, float]] = {}
        self.energy_production_tomorrow = 0.0
        self.percentile = DEFAULT_SOLCAST_PERCENTILE
        self.update_hours = DEFAULT_SOLCAST_UPDATE_HOURS

        # Initialize the path to the data files
        module_dir = os.path.dirname(os.path.abspath(__file__))
        self.raw_filepath = os.path.join(module_dir, "solcast_raw.data")

    # @property
    # def api_key(self) -> str | None:
    #     """Return the Solcast API key."""
    #     return self._api_key

    # @api_key.setter
    # def api_key(self, value: str) -> None:
    #     """Set the Solcast API key."""
    #     self._api_key = value

    # @property
    # def resource_id(self) -> str | None:
    #     """Return the Solcast resource ID."""
    #     return self._resource_id

    # @resource_id.setter
    # def resource_id(self, value: str) -> None:
    #     """Set the Solcast resource ID."""
    #     self._resource_id = value

    @property
    def update_hours(self) -> list[int]:
        """Return the hours to update Solcast data."""
        return self._update_hours

    @update_hours.setter
    def update_hours(self, value: list[int]) -> None:
        """Set the hours to update Solcast data."""
        self._update_hours = value

    def get_current_hour_pv_estimate(self) -> float:
        """Get the estimate for the current hour PV."""
        current_hour = datetime.now(ZoneInfo(self.timezone)).strftime("%Y-%m-%d-%H")
        # Return the current hour estimate
        logger.debug(
            "PV estimate for %s is %s",
            printable_hour(int(current_hour[-2:])),
            round(1000 * self.forecast.get(current_hour, (0.0, 0.0))[0], 0),
        )
        return round(1000 * self.forecast.get(current_hour, (0.0, 0.0))[0], 0)

    def get_current_hour_sun_estimate(self) -> float:
        """Get the sun status for the current hour."""
        current_hour = datetime.now(ZoneInfo(self.timezone)).strftime("%Y-%m-%d-%H")
        # Return the current hour estimate
        logger.debug(
            "Sun ratio for %s is %s",
            printable_hour(int(current_hour[-2:])),
            self.forecast.get(current_hour, (0.0, 0.0))[1],
        )
        return self.forecast.get(current_hour, (0.0, 0.0))[1]

    async def refresh_data(self) -> None:
        """Refresh Solcast data.

        This method fetches the latest solar forecast data from the Solcast API, processes it, and updates the internal state.
        It sets the SolcastStatus appropriately based on the success or failure of the API call and data processing.
        This method populates the forecast dictionary with hourly estimates, updates the energy production for tomorrow,
        and handles damping factors.
        """
        # If we don't have a Solcast API key, set the status to not_configured and return.
        if not (self._api_key and self._resource_id):
            logger.error(
                "Either the Solcast API key or resource id is missing in the configuration"
            )
            self.status = SolcastStatus.NOT_CONFIGURED
            return

        # If we have hourly_forecast data and the hour of self.data_updated is in the self._update_hours list AND self.data_updated is today, return.
        if self.data_updated and (
            self.data_updated.hour in self._update_hours
            and self.data_updated.date() == datetime.now(ZoneInfo(self.timezone)).date()
        ):
            return

        # If self.data_updated is None (startup) and we have hourly_forecast data, and the raw data file has a file date of today, update self.data_updated to the date of the hourly_forceast data.
        if self.data_updated is None and os.path.exists(self.raw_filepath):
            file_date = datetime.fromtimestamp(
                os.path.getmtime(self.raw_filepath), ZoneInfo(self.timezone)
            )
            if file_date.date() == datetime.now(ZoneInfo(self.timezone)).date():
                self.data_updated = file_date

        # Check when we last got data from the API, and refresh if necessary
        # First check if we have a raw data file and call the api if we don't have one.
        # Second, compare the date of the file to today. If it isn't today, call the api.
        # Third, compare the hour of the last update and the current hour to the list of hours to update.
        # Fourth, if the status is CANNOT_READ, call the api. That only gets set when we can't read the raw data file.
        if (
            not os.path.exists(self.raw_filepath)
            or self.data_updated
            and self.data_updated.date() < datetime.now(ZoneInfo(self.timezone)).date()
            or datetime.now(ZoneInfo(self.timezone)).hour in self._update_hours
            and self.data_updated
            and self.data_updated.hour != datetime.now(ZoneInfo(self.timezone)).hour
            or self.status == SolcastStatus.CANNOT_READ
            or self.data_updated is None
        ):
            await self._api_call()
            if self.status != SolcastStatus.API_NORMAL:
                return

        # We only get here if we have a raw data file and we need to update our data.
        # First, try to read the raw data file. If we can't, set the status to CANNOT_READ and return.
        async with aiofiles.open(self.raw_filepath, encoding="utf-8") as file:
            file_content = await file.read()
            forecasts = json.loads(file_content)
            if not forecasts:
                logger.error("Unable to read the Solcast raw forecast file")
                self.status = SolcastStatus.CANNOT_READ
                return

        # Convert input data to a DataFrame
        df = pd.DataFrame(forecasts)

        # If we have no data, note the fault and return
        if df.empty:
            logger.info("No data available for tomorrow")
            self.status = SolcastStatus.API_FAULT
            return

        # Parse the period_end column, assuming the format includes a 'Z' for UTC
        df["period_end"] = pd.to_datetime(df["period_end"], utc=True)

        # Convert to the local timezone
        df["period_end"] = await asyncio.to_thread(
            df["period_end"].dt.tz_convert, ZoneInfo(self.timezone)
        )

        # Calculate the target estimate based on linear interpolation
        if self.percentile <= 50:
            df["target_pv"] = df["pv_estimate10"] + (self.percentile - 10) / 40 * (
                df["pv_estimate"] - df["pv_estimate10"]
            )
        else:
            df["target_pv"] = df["pv_estimate"] + (self.percentile - 50) / 40 * (
                df["pv_estimate90"] - df["pv_estimate"]
            )

        # Drop the 'period' column if it exists in the resampled DataFrame
        if "period" in df.columns:
            # df.drop(columns=["period"], inplace=True)
            await asyncio.to_thread(df.drop, columns=["period"], inplace=True)

        # Resample to hourly intervals, summing 30-minute increments
        df = df.resample("h", on="period_end").mean().reset_index()

        # Round the pv_estimate and pv_estimate90 columns to one decimal place
        df["pv_estimate"] = df["pv_estimate"].round(1)
        df["pv_estimate90"] = df["pv_estimate90"].round(1)

        # Add a column that checks for full sun. This is the 50th percentile / the 90th percentile, both rounded to 1 decimal place.
        df["sun_ratio"] = (df["pv_estimate"] / df["pv_estimate90"]).round(1)

        # Create a dictionary with the local date and hour (yyyy-mm-dd-h) as the key and target_pv and is_full_sun as the value list
        self.forecast = {
            f"{row['period_end'].date()}-{row['period_end'].hour}": (
                0.0 if pd.isna(row["target_pv"]) else row["target_pv"],
                0.0 if pd.isna(row["sun_ratio"]) else row["sun_ratio"],
            )
            for _, row in df.iterrows()
        }  # All done
        self.status = SolcastStatus.API_NORMAL

    async def _api_call(self) -> bool:
        """Make the Solcast API call."""
        # Do this no questions asked. Return False if it fails.
        try:
            # Build the url
            url = f"https://api.solcast.com.au/rooftop_sites/{self._resource_id}/forecasts?format=json"
            headers = {"Authorization": f"Bearer {self._api_key}"}

            # Open a session and get the data and close the session
            async with aiohttp.ClientSession() as session:
                response = await session.get(url, headers=headers, timeout=TIMEOUT)
                response.raise_for_status()
                data = await response.json()
                forecasts = data.get("forecasts", None)

            # Save the raw forecast data for damping factor calculations
            async with aiofiles.open(
                self.raw_filepath, mode="w", encoding="utf-8"
            ) as file:
                data = json.dumps(forecasts, ensure_ascii=False, indent=4)
                await file.write(data)

            # Update the self.data_updated time and api status
            logger.info("Timezone is: %s", self.timezone)
            self.data_updated = datetime.now(ZoneInfo(self.timezone))
            self.status = SolcastStatus.API_NORMAL
        except aiohttp.ClientResponseError as errh:
            logger.error("HTTP Error: %s", errh)
            self.status = SolcastStatus.API_FAULT
            return False
        except aiohttp.ClientConnectionError as errc:
            logger.error("Error Connecting:  %s", errc)
            self.status = SolcastStatus.API_FAULT
            return False
        except TimeoutError as errt:
            logger.error("Timeout Error:  %s", errt)
            self.status = SolcastStatus.API_FAULT
            return False
        except aiohttp.ClientError as err:
            logger.error("Something Else:  %s", err)
            self.status = SolcastStatus.API_FAULT
            return False
        return True

    def set_api_key(self, api_key: str) -> None:
        """Set the Solcast API key."""
        self._api_key = api_key

    def set_resource_id(self, resource_id: str) -> None:
        """Set the Solcast resource ID."""
        self._resource_id = resource_id


class SolcastStatus(Enum):
    """Sol-Ark Inverter Status."""

    NOT_CONFIGURED = 0
    API_FAULT = 1
    API_NORMAL = 2
    CANNOT_READ = 3
    UNKNOWN = 9


class SunStatus(Enum):
    """Sun status for the current hour."""

    DARK = 0
    PARTIAL = 1
    FULL = 2
    UNKNOWN = 9


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
