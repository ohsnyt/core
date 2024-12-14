"""The Solcast Solar integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CLOUD_UPDATE_INTERVAL,
    DEBUGGING,
    DOMAIN,
    GRID_BOOST_MIDNIGHT_SOC,
    GRID_BOOST_ON,
    SOLCAST_API_KEY,
    SOLCAST_PERCENTILE,
    SOLCAST_RESOURCE_ID,
    SOLCAST_UPDATE_HOURS,
    VERSION,
)
from .inverter import Cloud
from .solcast import SolcastEstimator

logger = logging.getLogger(__name__)
if DEBUGGING:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


class OhSnytUpdateCoordinator(DataUpdateCoordinator):
    """Get the current data to update the sensors."""

    def __init__(self, *, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the OhSnytUpdateCoordinator."""
        logger.info("Initializing OhSnytUpdateCoordinator")
        super().__init__(
            hass,
            logger,
            name=DOMAIN,
            update_interval=timedelta(minutes=CLOUD_UPDATE_INTERVAL),
            request_refresh_debouncer=Debouncer(
                hass, logger, cooldown=0.3, immediate=True
            ),
            update_method=self._async_update_data,
        )
        self._version = VERSION

        # Create the cloud object.
        self.cloud = Cloud(hass)
        # Set the plant_id, username and password for the cloud object.
        # Debugging, print the entry data.
        logger.debug(">>>OhSnytUpdateCoordinator: entry.data: %s", entry.data)
        self.cloud.plant_id = entry.data.get("plant_id", None)
        self.cloud.set_username(entry.data.get("username", None))
        self.cloud.set_password(entry.data.get("password", None))
        self.cloud.timezone = hass.config.time_zone
        logger.debug(
            ">>>OhSnytUpdateCoordinator: plant_id: %s, username: %s",
            self.cloud.plant_id,
            self.cloud.get_username(),
        )

        # If we have grid boost options, set them in the cloud object.
        logger.debug(">>>OhSnytUpdateCoordinator: entry.options: %s", entry.options)
        if entry.options:
            # Create the solcast object.
            api_key = entry.options.get(SOLCAST_API_KEY, None)
            resource_id = entry.options.get(SOLCAST_RESOURCE_ID, None)
            timezone = self.cloud.timezone
            self.cloud.solcast = SolcastEstimator(
                api_key=api_key, resource_id=resource_id, timezone=timezone
            )
            # Add the percentile and update hours to the solcast object.
            self.cloud.solcast.percentile = entry.options.get(SOLCAST_PERCENTILE, None)
            self.cloud.solcast.update_hours = entry.options.get(
                SOLCAST_UPDATE_HOURS, None
            )
            # Add the other grid boost options to the cloud object.
            self.cloud.grid_boost_on = entry.options.get(GRID_BOOST_ON, None)
            self.cloud.grid_boost_history = entry.options.get(
                "grid_boost_history", None
            )
            self.cloud.grid_boost_midnight_soc = entry.options.get(
                GRID_BOOST_MIDNIGHT_SOC, None
            )

        # Set the config_entry and config_entry_id so the cloud object can do a callback to the options flow.
        self.cloud.config_entry = entry
        self.cloud.config_entry_id = entry.entry_id

    async def _async_update_data(self):
        """Fetch all data for your sensors here."""
        logger.debug(msg="Fetching Sol-Ark cloud data")
        # NOTE: This function is called by _async_refresh. That will update the data attribute with whatever we return. Hence we
        # CANNOT simply set self._data and return nothing because that will cause the data attribute to be set to None.
        return await self.cloud.update_sensors()

    @property
    def data(self):
        """Return the data."""
        return self._data

    @data.setter
    def data(self, value):
        """Set the data. This is used by the system call _async_refresh."""
        self._data = value
