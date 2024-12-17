"""The Solcast Solar integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CLOUD_UPDATE_INTERVAL, DEBUGGING, DOMAIN, VERSION
from .tou_scheduler import TOUScheduler

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
        self.entry = entry
        self.hass = hass

        # Create the scheduler object.
        self.scheduler = TOUScheduler(hass, entry)

        # Attempt to authenticate the inverter cloud api and the Solcast api.
        self.scheduler.authenticate()

    async def async_start(self):
        """Start the scheduler."""
        logger.info("Starting OhSnytUpdateCoordinator")
        await self.scheduler.async_start()

    async def _async_update_data(self):
        """Fetch all data for your sensors here."""
        logger.debug(msg="Fetching Sol-Ark cloud data")
        # NOTE: This function is called by _async_refresh. The flow is that we update whatever we need in our object, then return
        # a dict of the sensor data. The caller will then use that with the @data.setter to update the data served by home assistant.
        # Go update the sensors and return a dict of the sensor data.
        return await self.scheduler.update_sensors()

    @property
    def data(self):
        """Return the data."""
        return self._data

    @data.setter
    def data(self, value):
        """Set the data. This is used by the system call _async_refresh."""
        self._data = value
