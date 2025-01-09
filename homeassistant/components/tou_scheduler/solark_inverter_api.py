"""Contains the classes for a Sol-Ark Cloud data integration."""

from datetime import datetime, timedelta
from enum import Enum
import json
import logging
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import ClientSession
from dateutil.relativedelta import relativedelta
from requests.exceptions import HTTPError

from .const import (
    API_URL,
    CLOUD_URL,
    DEBUGGING,
    DEFAULT_BATTERY_SHUTDOWN,
    DEFAULT_GRID_BOOST,
    DEFAULT_GRID_BOOST_END,
    DEFAULT_GRID_BOOST_START,
    DEFAULT_GRID_BOOST_STARTING_SOC,
    DEFAULT_INVERTER_EFFICIENCY,
    DEFAULT_MANUAL_GRID_BOOST,
    TIMEOUT,
)

logger = logging.getLogger(__name__)
if DEBUGGING:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


class InverterAPI:
    """Sol-Ark API to interact with the inverter via the Sol-Ark Data Cloud.

    This will allow us to get pv, load, grid, and battery data from the cloud.
    It will allow us to read and set the grid boost SOC and time of use settings in the inverter.

    It requires a username and password to authenticate to the cloud. Authentication will return false if the authentication fails.

    The class contains:
        - 6 methods to provide constructor, getters and setters, and string representation.
        - 11 private helper methods.
        - 5 public methods to
            a) test authentication credentials
            b) authenticate,
            c) reauthenticate,
            d) get data from the inverter
            e) write grid boost state of charge settings to the inverter.
    """

    # Class initialization, getters and setters, and string representation
    def __init__(self, username: str, password: str, timezone: str) -> None:
        """Sol-Ark data cloud object."""

        logger.debug("Instantiating a Sol-Ark data cloud object")
        self._username: str = username
        self._password: str = password
        self.timezone: str = timezone
        self._refresh_token: str | None = None
        self._bearer_token: str | None = None
        self.bearer_token_expires_on: datetime = datetime.now(ZoneInfo(timezone))

        # Here is the session headers we use to communicate with the cloud
        self._headers = {
            "Content-type": "application/json",
            "Accept": "application/json",
            "Authorization": "",
        }

        # General cloud info
        self.cloud_status = Cloud_Status.UNKNOWN
        self.data_updated: str = ""
        self._urls = {
            "auth": CLOUD_URL + "/oauth/token",
            "plant_list": API_URL + "plants?page=1&limit=10&name=&status=",
            "inverter_list": CLOUD_URL
            + "/api/v1/inverters?page=1&limit=10&type=-1&status=1",
            # Other urls will be added later after the plant is selected
        }

        # Here is the plant info
        self.plant_address: str | None = None
        self.plant_created: datetime | None = None
        self.plant_id: str | None = None
        self.plant_status: Plant = Plant.UNKNOWN
        self.efficiency: float = DEFAULT_INVERTER_EFFICIENCY
        self._efficiency_update_month = (
            datetime.now(ZoneInfo(timezone)) - relativedelta(months=1)
        ).month
        self.plant_name: str | None = None
        # Here is the inverter info
        self.inverter_model: str | None = None
        self.inverter_serial_number: str | None = None
        self.inverter_status: Inverter = Inverter.UNKNOWN
        self.actual_grid_boost: int = 0
        # Here is the TOU boost info we will monitor and update
        self._grid_boost_starting_soc: int = DEFAULT_GRID_BOOST_STARTING_SOC
        self.grid_boost_start: str = DEFAULT_GRID_BOOST_START
        self.grid_boost_end: str = DEFAULT_GRID_BOOST_END
        self.boost: str = DEFAULT_GRID_BOOST
        self.manual_grid_boost: int = DEFAULT_MANUAL_GRID_BOOST
        self.calculated_grid_boost: int = DEFAULT_GRID_BOOST_STARTING_SOC

        # Here is the battery info
        self.batt_wh_usable: int = 0  # Current battery charge in Wh
        self.grid_boost_wh_min: int = (
            0  # Minimum battery charge in Wh during grid boost time
        )
        self.batt_wh_per_percent: float = 0.0  # Battery capacity in Wh per percent
        self.batt_shutdown: int = DEFAULT_BATTERY_SHUTDOWN  # Battery shutdown SoC
        self.batt_low_warning: int = DEFAULT_BATTERY_SHUTDOWN + 5

        # Realtime power in and out. Shown in kW
        self.realtime_battery_soc = 0.0
        self.realtime_battery_power = 0.0
        self.realtime_grid_power = 0.0
        self.realtime_load_power = 0.0
        self.realtime_pv_power = 0.0

        # self.batt_soc: float = 0.0
        self._batt_wh_max_est: float = 0.0

        # Temporary counter for reauthentication log
        self._reauth_counter = 0

    @property
    def username(self) -> str | None:
        """Return the username."""
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        """Set the username."""
        self._username = value

    @property
    def password(self) -> str | None:
        """Return the password."""
        return self._password

    @password.setter
    def password(self, value: str) -> None:
        """Set the password."""
        self._password = value

    def __str__(self) -> str:
        """Return a string representation of the cloud."""
        return f"Cloud(url={CLOUD_URL}, selected plant={self.plant_id}, updated={self.data_updated})"

    # Private helper methods
    def _build_api_endpoints(self) -> None:
        """Build endpoints needed to get sensor and settings data from the cloud.

        This method constructs the necessary API endpoints for various operations:
        - `flow`: Retrieves energy flow data for the plant.
        - `plant_details`: Fetches detailed information about the plant.
        - `inverter`: Gets real-time data for the specified inverter.
        - `battery`: Retrieves real-time battery statistics.
        - `pv`: Fetches real-time photovoltaic (PV) data.
        - `grid`: Retrieves real-time grid statistics.
        - `load`: Gets real-time load data.
        - `read_settings`: Reads the current settings of the inverter.
        - `write_settings`: Writes new settings to the inverter.
        """
        self._urls["flow"] = (
            CLOUD_URL + "/api/v1/plant/energy/" + f"{self.plant_id}/flow"
        )
        self._urls["read_settings"] = (
            CLOUD_URL + f"/api/v1/common/setting/{self.inverter_serial_number}/read"
        )
        self._urls["write_settings"] = (
            CLOUD_URL + f"/api/v1/common/setting/{self.inverter_serial_number}/set"
        )
        prefix = CLOUD_URL + "/api/v1/inverter/"
        self._urls["battery"] = (
            prefix
            # + f"battery/{self.inverter_serial_number}/realtime"
            + f"battery/{self.inverter_serial_number}/realtime?sn={self.inverter_serial_number}&lan=en"
        )
        self._urls["pv"] = prefix + f"{self.inverter_serial_number}/realtime/input"
        self._urls["grid"] = (
            prefix
            + f"grid/{self.inverter_serial_number}/realtime?sn={self.inverter_serial_number}&lan=en"
        )
        self._urls["load"] = prefix + f"load/{self.inverter_serial_number}/realtime"

    def _prepare_authorization_payload(self) -> dict[str, str]:
        """Prepare the payload for authentication or token renewal."""
        if self.username and self.password:
            if self._refresh_token:
                return {
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                }
            return {
                "username": self.username,
                "password": self.password,
                "grant_type": "password",
                "client_id": "csp-web",
            }
        logger.error("Cannot authenticate: No username or password")
        return {}

    def _process_response_data(self, response_data: dict[str, Any]) -> bool:
        """Process the response data from the authentication request."""
        data = response_data.get("data", {})
        if not data:
            return False

        token = data.get("access_token", "")
        self._refresh_token = data.get("refresh_token", None)
        expires = data.get("expires_in", None)

        if not (token and expires and self._refresh_token):
            return False

        self.bearer_token_expires_on = datetime.now(
            ZoneInfo(self.timezone)
        ) + timedelta(seconds=expires)
        return True

    def _convert_inverter_model(self, value: str) -> str:
        """Convert the inverter model to a more recognizable string."""
        return "Sol-Ark 12K-2P-N" if value == "STROG INV" else value

    async def _update_flow(self) -> None:
        """Get statistics on this plant's flow."""
        # Double check the validity of the cloud session.
        data = await self._request("GET", self._urls["flow"], body={})
        if data is None:
            logger.error("Unable to update realtime power flow information")
            return

        if self._safe_get(data, "soc") <= 0:
            logger.critical("ODD BATTERY SOC: %s ", data)
            return
        self.realtime_battery_soc = self._safe_get(data, "soc")
        self.realtime_battery_power = self._safe_get(data, "battPower")
        self.realtime_load_power = self._safe_get(data, "loadOrEpsPower")
        self.realtime_grid_power = self._safe_get(data, "gridOrMeterPower")
        self.realtime_pv_power = self._safe_get(data, "pvPower")

        # Calculate the current usable battery charge in Wh
        self.batt_wh_usable = int(
            self.batt_wh_per_percent * (self.realtime_battery_soc - self.batt_shutdown)
        )

        self.data_updated = datetime.now(ZoneInfo(self.timezone)).strftime(
            "%a %I:%M %p"
        )

    async def _calculate_total_efficiency(self) -> None:
        """Calculate the long term (total) power efficiency."""

        # Only calculate the total efficiency once a month
        if datetime.now(ZoneInfo(self.timezone)).month == self._efficiency_update_month:
            return

        # Get totals for battery, PV, Grid, and Load from MySolark data cloud
        logger.debug("Getting battery totals for monthly efficiency calculation")
        data = await self._request("GET", self._urls["battery"], body={})
        if data is None:
            logger.error("Unable to update battery information")
            return
        total_batt_charge = float(data.get("etotalChg", 0))
        total_batt_discharge = float(data.get("etotalDischg", 0))
        self._batt_wh_max_est = int(float(data.get("capacity", 0)) * 48)

        logger.debug("Getting PV totals")
        data = await self._request("GET", self._urls["pv"], body={})
        if data is None:
            logger.error("Unable to update PV information")
            return
        total_pv = float(data.get("etotal", 0.0))

        logger.debug("Getting grid totals")
        data = await self._request("GET", self._urls["grid"], body={})
        if data is None:
            logger.error("Unable to update grid information")
            return
        total_grid_import_buy = float(data.get("etotalFrom", 0))

        logger.debug("Getting load totals")
        data = await self._request("GET", self._urls["load"], body={})
        if data is None:
            logger.error("Unable to update load information")
            return
        total_load = float(data.get("totalUsed", 0.0))

        # Calculate the total power source and the total power efficiency
        total_source = (
            total_pv + total_grid_import_buy + total_batt_discharge - total_batt_charge
        )
        # Prevent divide by zero. Only set the total efficiency if we had any power from the sources
        if (total_source) > 0:
            efficiency = round((total_load / total_source), 2)
        else:
            efficiency = DEFAULT_INVERTER_EFFICIENCY
        logger.info("Total power efficiency is %.0f", efficiency * 100)
        self.efficiency = efficiency

        # Update the month we last calculated the total efficiency
        self._efficiency_update_month = datetime.now(ZoneInfo(self.timezone)).month

    async def _read_settings(self) -> dict[str, Any]:
        """Read the inverter settings and set self values."""

        # Create a settings dict to return (whether we get the settings or not)
        settings: dict[str, Any] = {}
        data = await self._request("GET", self._urls["read_settings"], body={})

        if data is None:
            logger.error("Unable to update load information")
            return settings

        if data is not None:
            self._grid_boost_starting_soc = int(self._safe_get(data, "cap1"))
            self.actual_grid_boost = int(self._safe_get(data, "cap1"))
            self.grid_boost_start = data.get("sellTime1", DEFAULT_GRID_BOOST_START)
            self.grid_boost_end = data.get("sellTime2", DEFAULT_GRID_BOOST_END)
            batt_capacity_ah = self._safe_get(data, "batteryCap")
            self.batt_shutdown = int(self._safe_get(data, "batteryShutdownCap"))
            self.batt_low_warning = int(self._safe_get(data, "batteryLowCap"))
            batt_float_voltage = self._safe_get(data, "floatVolt")
            self.batt_wh_per_percent = batt_capacity_ah * batt_float_voltage / 100

            self.grid_boost_wh_min = int(
                self.batt_wh_per_percent * self._grid_boost_starting_soc
            )

        return settings

    def _safe_get(self, data: dict[str, Any], key: str, default: float = 0.0) -> float:
        """Convert a value to float safely, returning the default value if the value is None or cannot be converted."""
        try:
            value = data.get(key, default)
            return float(value)
        except (TypeError, ValueError):
            return default

    async def _request(
        self, method: str, endpoint: str, body: Any | None = None
    ) -> dict[str, Any] | None:
        """Send a request to the Sol-Ark cloud and return the data portion of the response."""

        # Log the time until we need to reauthenticate if we are between the top of the hour and five minutes before the hour
        time_remaining = self.bearer_token_expires_on - datetime.now(
            ZoneInfo(self.timezone)
        )
        if self._reauth_counter % 12 == 0 or time_remaining.total_seconds() < 300:
            # TEMP Using logger.info instead of debug in semi-final version
            logger.info(
                "We need to reauthenticate in %s hours %s minutes",
                time_remaining.total_seconds() // 3600 % 24,
                time_remaining.total_seconds() // 60 % 60,
            )
        self._reauth_counter += 1

        # Check if we need to reauthenticate
        if self.bearer_token_expires_on and datetime.now(
            ZoneInfo(self.timezone)
        ) >= self.bearer_token_expires_on - timedelta(hours=1):
            # TEMP Using logger.info instead of debug in semi-final version
            logger.info("Reauthenticating to the Sol-Ark cloud")
            if not await self.reauthenticate():
                logger.error(
                    "Failed to reauthenticate to the Sol-Ark cloud. Doing backup authentication."
                )
                # Fallback if reauthentication fails.
                payload = self._prepare_authorization_payload()
                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.post(
                            self._urls["auth"], json=payload, timeout=TIMEOUT
                        ) as response:
                            if response.status == 200:
                                outer = await response.json()
                                if outer is None:
                                    logger.error(
                                        "Failed to get a valid response from the authentication request"
                                    )
                                    return None
                                data = outer.get("data", {})
                                logger.info("Authenticated with Solark Inverter API")
                                token = data.get("access_token", "")
                                session.headers["Authorization"] = f"Bearer {token}"
                                self._headers["Authorization"] = f"Bearer {token}"
                                self._refresh_token = data.get("refresh_token", None)
                                expires = data.get("expires_in", None)
                                self.bearer_token_expires_on = (
                                    datetime.now(ZoneInfo(self.timezone))
                                    + timedelta(seconds=expires)
                                    if expires
                                    else datetime.now(ZoneInfo(self.timezone))
                                )
                    except aiohttp.ClientError as err:
                        logger.error("Request error: %s", err)
                        return None

        if method == "GET":
            return await self._get_request(endpoint)
        if method == "POST":
            return await self._post_request(endpoint, body)
        logger.error("Unsupported HTTP method: %s", method)
        return None

    async def _get_request(self, endpoint: str) -> dict[str, Any] | None:
        """Send a GET request to the Sol-Ark cloud and return the data portion of the response."""
        async with aiohttp.ClientSession(headers=self._headers) as session:
            try:
                async with session.get(endpoint, timeout=TIMEOUT) as response:
                    response_data = await response.json() if response else None
                    return response_data.get("data") if response_data else None
            except aiohttp.ClientError as err:
                logger.error("Request error: %s", err)
                return None

    async def _post_request(self, endpoint: str, body: Any) -> dict[str, Any] | None:
        """Send a POST request to the Sol-Ark cloud and return the response."""
        async with aiohttp.ClientSession(headers=self._headers) as session:
            try:
                async with session.post(url=endpoint, json=body) as response:
                    return await response.json() if response else None
            except aiohttp.ClientError as err:
                logger.error("Request error: %s", err)
                return None

    # Public methods
    async def test_authenticate(self) -> bool:
        """Authenticate to the Sol-Ark cloud for config_flow. Return list of plants or None."""
        # If we don't have a username or password, we can't authenticate
        if not (self.username and self.password):
            logger.error("Cannot authenticate: No username or password")
            return False

        logger.debug("Authenticating to the Sol-Ark cloud")

        # Prepare the payload for the login
        payload = {
            "username": self.username,
            "password": self.password,
            "grant_type": "password",
            "client_id": "csp-web",
        }

        async with ClientSession() as session:
            try:
                # Await the response from the cloud
                response = await session.post(
                    self._urls["auth"], json=payload, timeout=TIMEOUT
                )
                # Get the data from the response
                response_data = await response.json() if response else None
                # If the response is not OK, log the error and invalidate the session
                if response_data is None or response_data.get("code") != 0:
                    logger.error("Test authentication failed to get a valid response")
                    self.cloud_status = Cloud_Status.UNKNOWN
                    return False
            except HTTPError as err:
                logger.error("HTTP error: %s", err)
                self.cloud_status = Cloud_Status.UNKNOWN
                return False

        return True

    async def authenticate(self) -> bool:
        """Authenticate to the Sol-Ark cloud. Creates and holds a session."""
        # Only called at startup. We call reauthenticate to renew the token.
        logger.debug("Authenticating to the Sol-Ark cloud")
        # Prepare the payload for the login
        payload = self._prepare_authorization_payload()
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    self._urls["auth"], json=payload, timeout=TIMEOUT
                ) as response:
                    if response.status == 200:
                        outer = await response.json()
                        if outer is None:
                            logger.error(
                                "Failed to get a valid response from the authentication request"
                            )
                            return False
                        data = outer.get("data", {})
                        logger.info("Authenticated with Solark Inverter API")
                        token = data.get("access_token", "")
                        session.headers["Authorization"] = f"Bearer {token}"
                        self._headers["Authorization"] = f"Bearer {token}"
                        self._refresh_token = data.get("refresh_token", None)
                        expires = data.get("expires_in", None)
                        self.bearer_token_expires_on = (
                            datetime.now(ZoneInfo(self.timezone))
                            + timedelta(seconds=expires)
                            if expires
                            else datetime.now(ZoneInfo(self.timezone))
                        )
                        logger.debug("Getting plant info")
                        async with session.get(
                            self._urls["plant_list"],
                            data=json.dumps({}),
                            timeout=TIMEOUT,
                        ) as response:
                            if response.status == 200:
                                outer = await response.json()
                                if outer is None:
                                    logger.error(
                                        "Failed to get a valid response from the authentication request"
                                    )
                                    return False
                                data = outer.get("data", {})
                                infos: list[dict[str, Any]] = data.get("infos", [])
                                if infos:
                                    self.plant_name = infos[0].get("name", None)
                                    self.plant_id = infos[0].get("id", None)
                                    self.plant_address = infos[0].get("address", None)
                                    self.plant_status = Plant(
                                        infos[0].get("status", Plant.UNKNOWN)
                                    )
                                    created_date = infos[0].get("createAt", None)
                                    if created_date:
                                        self.plant_created = datetime.fromisoformat(
                                            created_date
                                        )
                                    logger.debug(
                                        "Plant status is: %s", self.plant_status
                                    )

                                # With the plant info, go get the plant inverter serial number
                                async with session.get(
                                    self._urls["inverter_list"],
                                    data=json.dumps({}),
                                    timeout=TIMEOUT,
                                ) as response:
                                    if response.status == 200:
                                        outer = await response.json()
                                        if outer is None:
                                            logger.error(
                                                "Failed to get a valid response from the authentication request"
                                            )
                                            return False
                                        data = outer.get("data", {})
                                        inverter_list = data.get("infos")
                                        # If we don't have an inverter list, we can't continue. Log an error and return false.
                                        if not inverter_list:
                                            logger.error("No inverters found")
                                            self.cloud_status = Cloud_Status.UNKNOWN
                                            return False

                                        # NOTE: We assume the master is inverter 0, store that inverter as the master
                                        self.inverter_serial_number = inverter_list[0][
                                            "sn"
                                        ]
                                        self.inverter_model = (
                                            self._convert_inverter_model(
                                                inverter_list[0]["model"]
                                            )
                                        )
                                        self.inverter_status = Inverter(
                                            inverter_list[0].get(
                                                "status", Inverter.UNKNOWN
                                            )
                                        )
                                        # Build the api endpoints needed to get sensor and settings data from the cloud
                                        self._build_api_endpoints()
                                        logger.debug(
                                            "Successfully retrieved the inverter serial number"
                                        )
                                        # await self._calculate_total_efficiency()
                                        return True
            except aiohttp.ClientConnectorError as e:
                logger.error("DNS resolution error: %s", e)
                return False
        return True

    async def reauthenticate(self) -> bool:
        """Reauthenticate to the Sol-Ark cloud using the refresh token."""
        if not self._refresh_token:
            logger.error("Cannot reauthenticate: No refresh token available")
            return False

        logger.debug("Reauthenticating to the Sol-Ark cloud")
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    self._urls["auth"], json=payload, timeout=TIMEOUT
                ) as response,
            ):
                response_data = await response.json()
                if response_data.get("msg") != "Success":
                    logger.error(
                        "Reauthentication failed with message: %s, response data: %s",
                        response_data.get("msg"),
                        response_data,
                    )
                    self.cloud_status = Cloud_Status.UNKNOWN
                    return False
                data = response_data.get("data", {})
                if not data:
                    logger.error(
                        "Failed to get a valid response from the reauthentication request"
                    )
                    self.cloud_status = Cloud_Status.UNKNOWN
                    return False
                logger.debug("Reauthentication data is %s", response_data)
                token = data.get("access_token", "")
                session.headers["Authorization"] = f"Bearer {token}"
                self._headers["Authorization"] = f"Bearer {token}"
                self._refresh_token = data.get("refresh_token", None)
                expires = data.get("expires_in", None)
                self.bearer_token_expires_on = (
                    datetime.now(ZoneInfo(self.timezone)) + timedelta(seconds=expires)
                    if expires
                    else datetime.now(ZoneInfo(self.timezone))
                )
                self.cloud_status = Cloud_Status.ONLINE
                logger.debug("self._headers is now %s", self._headers)
                logger.debug(
                    "-------------------------------------------------------------------------------"
                )
                return True

        except aiohttp.ClientError as err:
            logger.error("Request error: %s", err)
            self.cloud_status = Cloud_Status.UNKNOWN
            return False

    async def refresh_data(self) -> None:
        """Update statistics on this plant's various components and return them as a dict."""
        # Update efficiency once a month
        await self._calculate_total_efficiency()

        # Get the realtime stats for this plant, raising an exception if there is a problem
        await self._read_settings()
        await self._update_flow()

        # Report that the cloud status was good
        self.cloud_status = Cloud_Status.ONLINE

    async def write_grid_boost_soc(self, boost: str) -> None:
        """Set the inverter setting for Time of Use block 1, State of Charge as per the supplied directive."""

        # Set the inverter settings for Time of Use block 1, State of Charge
        body: dict[str, str | bool] = {}
        body["sellTime1"] = str(self.grid_boost_start)
        # If we are doing a manual boost, set the SoC to the manual boost value
        if boost == "manual":
            body["cap1"] = str(self.manual_grid_boost)
            body["time1on"] = True
        # If we are doing an automatic boost, set the SoC to the calculated value
        elif boost == "automated":
            body["cap1"] = str(self.calculated_grid_boost)
            body["time1on"] = True
        # If we are turning off the boost, set the SoC to 0
        elif boost == "off":
            body["cap1"] = "0"
            body["time1on"] = False
        else:
            logger.error("Invalid grid boost setting: %s", boost)
            return

        if not self._urls.get("write_settings"):
            logger.error("write_settings URL is not set")
            return

        response = await self._request("POST", self._urls["write_settings"], body=body)
        if response and response.get("msg", None) == "Success":
            logger.info(
                "Grid boost written: %s%% boost is scheduled to start just past midnight",
                self._grid_boost_starting_soc,
            )
            return
        logger.error(
            "Grid boost SoC setting NOT written. Response was: %s",
            response,
        )


# Enum classes
class Inverter(Enum):
    """Sol-Ark Inverter Status."""

    OFFLINE = 0
    NORMAL = 1
    WARNING = 2
    FAULT = 3
    UPGRADING = 4
    UNKNOWN = 9


class Plant(Enum):
    """Sol-Ark Plant Status."""

    OFFLINE = 0
    NORMAL = 1
    WARNING = 2
    FAULT = 3
    UNKNOWN = 9


class Batt_Status(Enum):
    """Sol-Ark Battery Status."""

    DISCHARGING = 0
    CHARGING = 1
    IDLE = 2
    UNKNOWN = 9


class Cloud_Status(Enum):
    """Sol-Ark Data Cloud Status."""

    ONLINE = 0
    UNKNOWN = 9


class Plant_Status(Enum):
    """Sol-Ark Plant Status."""

    OFFLINE = 0
    NORMAL = 1
    WARNING = 2
    FAULT = 3
    UNKNOWN = 9
