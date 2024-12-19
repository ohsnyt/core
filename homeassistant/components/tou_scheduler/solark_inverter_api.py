"""Contains the classes for a Sol-Ark Cloud data integration."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
import json
import logging
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import ClientSession
from requests.exceptions import HTTPError, RequestException, Timeout

from homeassistant.config_entries import ConfigEntry

from .const import (
    API_URL,
    CLOUD_UPDATE_INTERVAL,
    CLOUD_URL,
    DEBUGGING,
    DEFAULT_BATTERY_SHUTDOWN,
    DEFAULT_GRID_BOOST_END,
    DEFAULT_GRID_BOOST_MIDNIGHT_SOC,
    DEFAULT_GRID_BOOST_ON,
    DEFAULT_GRID_BOOST_START,
    DEFAULT_GRID_BOOST_STARTING_SOC,
    DEFAULT_INVERTER_EFFICIENCY,
    OFF,
    TIMEOUT,
)

logger = logging.getLogger(__name__)
if DEBUGGING:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


class InverterAPI:
    """Sol-Ark API to interact with the Sol-Ark Data Cloud.

    This will allow us to get pv, load, grid, and battery data from the cloud.
    It will allow us to set the grid boost SOC and time of use settings in the inverter.

    It requires a username and password to authenticate to the cloud. This will return false if the authentication fails.
    """

    def __init__(self) -> None:
        """Sol-Ark data cloud object."""

        logger.debug("Instantiating a Sol-Ark data cloud object")
        # General cloud info
        self.cloud_name = "MySolark Data"
        self.cloud_status = Cloud_Status.UNKNOWN
        self.data_updated: str = ""
        self.urls = {
            "auth": CLOUD_URL + "/oauth/token",
            "plant_list": API_URL + "plants?page=1&limit=10&name=&status=",
            "inverter_list": CLOUD_URL
            + "/api/v1/inverters?page=1&limit=10&type=-1&status=1",
            # Other urls will be added later after the plant is selected
        }
        self.user_id: str | None = None
        self._username: str | None = None
        self._password: str | None = None

        # Home Assistant stuff needed to set up listener after configuration is done
        self.config_entry: ConfigEntry | None = None
        self.config_entry_id: str | None = None

        # Here is the session info we use to communicate with the cloud
        self._headers = {
            "Content-type": "application/json",
            "Accept": "application/json",
            "Authorization": "",
        }
        self._session: ClientSession | None = None
        self._refresh_token: str | None = None
        self._bearer_token: str | None = None
        self._bearer_token_expires_on: datetime | None = None

        # Here is the plant info
        self.plant_address: str | None = None
        self.plant_created: datetime | None = None
        self.plant_id: str | None = None
        self.efficiency: float | None = None
        self.plant_name: str | None = None
        self.plant_status: Plant = Plant.UNKNOWN
        self.timezone: str = "UTC"
        # Here is the inverter info
        self.inverter_model: str | None = None
        self.inverter_serial_number: str | None = None
        self.inverter_status: Inverter = Inverter.UNKNOWN
        # Here is the TOU boost info we will monitor and update
        self.grid_boost_starting_soc: int = DEFAULT_GRID_BOOST_STARTING_SOC
        self.grid_boost_midnight_soc: int = DEFAULT_GRID_BOOST_MIDNIGHT_SOC
        self.grid_boost_start: str = DEFAULT_GRID_BOOST_START
        self.grid_boost_end: str = DEFAULT_GRID_BOOST_END
        self.grid_boost_on: str = DEFAULT_GRID_BOOST_ON

        # Here is the battery info
        self.batt_wh_usable: int = 0  # Current battery charge in Wh
        self.grid_boost_wh_min: int = (
            0  # Minimum battery charge in Wh during grid boost time
        )
        self.batt_wh_per_percent: float = 0.0  # Battery capacity in Wh per percent
        self.batt_shutdown: int = DEFAULT_BATTERY_SHUTDOWN  # Battery shutdown SoC

        # Realtime power in and out. Shown in kW
        self.realtime_battery_soc = 0.0
        self.realtime_battery_power = 0.0
        self.realtime_grid_power = 0.0
        self.realtime_load_power = 0.0
        self.realtime_pv_power = 0.0

        # self.batt_soc: float = 0.0
        self._batt_wh_max_est: float = 0.0

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
        self.urls["flow"] = (
            CLOUD_URL + "/api/v1/plant/energy/" + f"{self.plant_id}/flow"
        )
        self.urls["read_settings"] = (
            CLOUD_URL + f"/api/v1/common/setting/{self.inverter_serial_number}/read"
        )
        self.urls["write_settings"] = (
            CLOUD_URL + f"/api/v1/common/setting/{self.inverter_serial_number}/set"
        )

    async def test_authenticate(self) -> str | None:
        """Authenticate to the Sol-Ark cloud for config_flow. Return list of plants or None."""
        await self.authenticate()
        result = await self.get_plant()
        if self._session:
            await self._session.close()
        if result:
            return self.plant_id
        return None

    async def authenticate(self) -> bool:
        """Authenticate to the Sol-Ark cloud. Creates and holds a session."""
        # If we don't have a username or password, we can't authenticate
        if not (self.username and self.password):
            logger.error("Cannot authenticate: No username or password")
            return False

        # If we don't have a refresh token, we need to prepare to create a session and log in
        logger.debug("Authenticating to the Sol-Ark cloud")
        if self._session is None:
            # Prepare the headers for the session
            headers = {
                "Content-type": "application/json",
                "Accept": "application/json",
                "Authorization": "",
            }
            # Create the session
            self._session = ClientSession(headers=headers)
            # Prepare the payload for the login
            payload = {
                "username": self.username,
                "password": self.password,
                "grant_type": "password",
                "client_id": "csp-web",
            }

        # Otherwise just prepare to renew the tokens
        else:
            # Prepare the payload for the token renewal
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token if self._refresh_token else "",
            }

        try:
            # Await the response from the cloud
            response = await self._session.post(
                self.urls["auth"], json=payload, timeout=TIMEOUT
            )
            # Get the data from the response
            response_data = await response.json()
            # If the response is not OK, log the error and invalidate the session
            if response_data.get("code") != 0:
                logger.error(response_data.get("msg"))
                self.cloud_status = Cloud_Status.UNKNOWN
                self._session = None
                return False
            # Decode the bearer token, the refresh token and expiration time
            data: dict[str, Any] | None = response_data.get("data", {})
            if data:
                token = data.get("access_token", "")
                self._session.headers["Authorization"] = f"Bearer {token}"
                self._refresh_token = data.get("refresh_token", None)
                expires = data.get("expires_in", None)
                self._bearer_token_expires_on = (
                    datetime.now(ZoneInfo(self.timezone)) + timedelta(seconds=expires)
                    if expires
                    else None
                )
                # If anything is missing, token renewal failed. Log the failure and invalidate the session.
            if not (token and expires and self._refresh_token):
                logger.error("Failed to authenticate to the Sol-Ark cloud")
                self.cloud_status = Cloud_Status.UNKNOWN
                self._session = None
                return False
        except HTTPError as err:
            logger.error("HTTP error: %s", err)
            self.cloud_status = Cloud_Status.UNKNOWN
            self._session = None
            return False

        # Authentication was successful
        self.cloud_status = Cloud_Status.ONLINE
        return True

    async def get_plant(self) -> bool:
        """Get the plant info, returning true if successful."""

        logger.debug("Getting plant info")
        try:
            data = await self._request("GET", self.urls["plant_list"], body={})
            if data is None:
                return False
        except (HTTPError, RequestException, Timeout) as e:
            logger.error("Failed to get plant list: %s", e)
            return False

        infos: list[dict[str, Any]] = data.get("infos", [])
        if infos:
            self.plant_name = infos[0].get("name", None)
            self.plant_id = infos[0].get("id", None)
            self.efficiency = infos[0].get("efficiency", DEFAULT_INVERTER_EFFICIENCY)
            self.plant_address = infos[0].get("address", None)
            self.plant_status = Plant(infos[0].get("status", Plant.UNKNOWN))

        # With the plant info, go get the plant inverter serial number
        return await self.get_inverter_sn()

    async def get_inverter_sn(self) -> bool:
        """Get the inverter SN and build API endpoints. Done once when first updating sensor data."""

        data = await self._request("GET", self.urls["inverter_list"], body={})
        # If we don't have any details, we can't continue. Log an error and force reauthentication.
        if data is None:
            logger.error("Unable to get inverter list")
            self.cloud_status = Cloud_Status.UNKNOWN
            self._session = None
            return False

        inverter_list = data.get("infos")
        # If we don't have an inverter list, we can't continue. Log an error and return false.
        if not inverter_list:
            logger.error("No inverters found")
            self.cloud_status = Cloud_Status.UNKNOWN
            self._session = None
            return False

        # NOTE: We assume the master is inverter 0, store that inverter as the master
        self.inverter_serial_number = inverter_list[0]["sn"]
        self.inverter_model = self.convert_inverter_model(inverter_list[0]["model"])
        self.inverter_status = Inverter(
            inverter_list[0].get("status", Inverter.UNKNOWN)
        )
        # Build the api endpoints needed to get sensor and settings data from the cloud
        self._build_api_endpoints()
        logger.debug("Successfully retrieved the inverter serial number")
        return True

    async def refresh_data(self) -> None:
        """Update statistics on this plant's various components and return them as a dict."""
        # Get the realtime stats for this plant, raising an exception if there is a problem
        await self._read_settings()
        await self._update_flow()

        # Report that the cloud status was good
        self.cloud_status = Cloud_Status.ONLINE
        # logger.info("Dictionary of sensor data returned")
        # return self.to_dict()

    async def _update_flow(self) -> None:
        """Get statistics on this plant's flow."""
        logger.debug("Updating realtime power flow data")
        # Double check the validity of the cloud session.
        data = await self._request("GET", self.urls["flow"], body={})
        if data is None:
            logger.error("Unable to update realtime power flow information")
            return

        self.realtime_battery_soc = self.safe_get(data, "soc")
        self.realtime_battery_power = self.safe_get(data, "battPower")
        self.realtime_load_power = self.safe_get(data, "loadOrEpsPower")
        self.realtime_grid_power = self.safe_get(data, "gridOrMeterPower")
        self.realtime_pv_power = self.safe_get(data, "pvPower")

        # Calculate the current usable battery charge in Wh
        self.batt_wh_usable = int(
            self.batt_wh_per_percent * (self.realtime_battery_soc - self.batt_shutdown)
        )
        logger.debug("Current battery charge: %s wH", self.batt_wh_usable)

        self.data_updated = datetime.now(ZoneInfo(self.timezone)).strftime(
            "%a %I:%M %p"
        )

    async def _read_settings(self) -> dict[str, Any]:
        """Read the inverter settings and set self values."""
        logger.debug("Reading inverter settings")

        # Create a settings dict to return (whether we get the settings or not)
        settings: dict[str, Any] = {}
        data = await self._request("GET", self.urls["read_settings"], body={})

        if data is None:
            logger.error("Unable to update load information")
            return settings

        if data is not None:
            self.grid_boost_starting_soc = int(self.safe_get(data, "cap1"))
            self.grid_boost_start = data.get("sellTime1", DEFAULT_GRID_BOOST_START)
            self.grid_boost_end = data.get("sellTime2", DEFAULT_GRID_BOOST_END)
            self.grid_boost_on = data.get("time1on", OFF)
            batt_capacity_ah = self.safe_get(data, "batteryCap")
            self.batt_shutdown = int(self.safe_get(data, "batteryShutdownCap"))
            batt_float_voltage = self.safe_get(data, "floatVolt")
            self.batt_wh_per_percent = batt_capacity_ah * batt_float_voltage / 100

            self.grid_boost_wh_min = int(
                self.batt_wh_per_percent * self.grid_boost_starting_soc
            )

        return settings

    def safe_get(self, data: dict[str, Any], key: str, default: float = 0.0) -> float:
        """Convert a value to float safely, returning the default value if the value is None or cannot be converted."""
        try:
            value = data.get(key, default)
            return float(value)
        except (TypeError, ValueError):
            return default

    async def write_grid_boost_soc(self) -> None:
        """Set the inverter setting for Time of Use block 1, State of Charge."""

        # Don't write the setting if grid boost is turned off.
        if self.grid_boost_on == OFF:
            logger.info("Grid boost is off. Not writing SoC setting")
            return

        logger.debug("Pretending to grid boost SoC setting")
        # logger.debug("Writing grid boost SoC setting")
        # Set the inverter settings for Time of Use block 1, State of Charge
        body = {}
        body["cap1"] = str(self.grid_boost_starting_soc)
        body["sellTime1"] = str(self.grid_boost_start)
        body["time1on"] = self.grid_boost_on
        # TESTING ONLY
        # if self.urls.get("write_settings"):
        # response = await self._request(
        # "POST", self.urls["write_settings"], body=body
        # )
        # if response and response.get("msg", None) == "Success":
        # logger.info(
        # "Grid boost written: %s%% boost is scheduled to start just past midnight",
        # self.grid_boost_starting_soc,
        # )
        # return
        # logger.error(
        # "Grid boost SoC setting NOT written. Response was: %s",
        # response,
        # )

    async def _request(
        self, method: str, endpoint: str, body: Any | None
    ) -> dict[str, Any] | None:
        """Send a request to the Sol-Ark cloud and return the data portion of the response."""
        # If we don't have a session, don't bother trying to send the request
        if self._session is None:
            logger.error("Session is not initialized")
            return None

        # If we don't have a valid bearer token authenticate or die trying
        if (
            not self._bearer_token_expires_on
            or self._bearer_token_expires_on <= datetime.now(ZoneInfo(self.timezone))
        ):
            # Fail if we don't have username and password
            if not self._username or not self._password:
                logger.error("Cannot authenticate: No username or password")
                return None
            if not await self.authenticate():
                # If we can't authenticate, we can't send the request
                return None

        # Go get the data from the cloud
        try:
            if body:
                response = await self._session.request(
                    method, endpoint, data=json.dumps(body), timeout=TIMEOUT
                )
            else:
                response = await self._session.request(
                    method, endpoint, timeout=TIMEOUT
                )

            # All api get requests return a data dict, so we return the data portion of the response
            # response = await thread if thread else None
            response_data = await response.json() if response else None
            if method == "GET":
                return response_data.get("data") if response_data else None

        except HTTPError as errh:
            logger.error("HTTP Error: %s", errh)
            return None
        except ConnectionError as errc:
            logger.error("Error Connecting:  %s", errc)
            return None
        except Timeout as errt:
            logger.error("Timeout Error:  %s", errt)
            return None
        except RequestException as err:
            logger.error("Something Else:  %s", err)
            return None

        # Must be a post request. All api post requests return a status dict, so we return the status portion of the response
        return response_data

    def convert_inverter_model(self, value: str) -> str:
        """Convert the inverter model to a more recognizable string."""
        return "Sol-Ark 12K-2P-N" if value == "STROG INV" else value

    def just_after_top_of_hour(self) -> bool:
        """Return True if the current time is just after the top of the hour."""
        return datetime.now(ZoneInfo(self.timezone)).minute < CLOUD_UPDATE_INTERVAL


class Inverter(Enum):
    """Sol-Ark Inverter Status."""

    OFFLINE = 0
    NORMAL = 1
    WARNING = 2
    FAULT = 3
    UPGRADING = 4
    UNKNOWN = 9


class Grid_Status(Enum):
    """Sol-Ark Grid Status."""

    GRID_SELL = -1
    GRID_SOMETHING = 0
    GRID_BUY = 1
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


class Fault(Enum):
    """Sol-Ark Fault Codes."""

    INFO = 1
    WARNING = 2
    FAULT = 3
    UNKNOWN = 9


class Inverter_Type(Enum):
    """Sol-Ark Inverter Type."""

    INVERTER = 1
    ESS_MODULE = 2
    MICRO_INVERTER = 3
    CONVERT = 4
    METER = 5
    BATTERY = 6
    UNKNOWN = 9


class batt_Type(Enum):
    """Sol-Ark Inverter Type."""

    LEAD_ACID = 0
    LITHIUM = 1
    UNKNOWN = 9


class Plant_Type(Enum):
    """Sol-Ark Plant Type."""

    ENERGY_STORAGE_SYSTEM_AC = 0
    GRID_TIED = 1
    ENERGY_STORAGE_SYSTEM_DC = 2
    UNKNOWN = 9


class Cloud_Status(Enum):
    """Sol-Ark Data Cloud Status."""

    ONLINE = 0
    UNKNOWN = 9
