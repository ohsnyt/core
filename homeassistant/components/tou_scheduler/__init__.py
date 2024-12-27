"""The Time of Use Scheduler integration."""

from __future__ import annotations

import logging

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.typing import ConfigType

from .config_flow import TouSchedulerOptionFlow
from .const import DOMAIN, PLATFORMS
from .coordinator import TOUUpdateCoordinator
from .solark_inverter_api import InverterAPI
from .solcast_api import SolcastAPI
from .tou_scheduler import TOUScheduler

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the TOU Scheduler integration."""
    _LOGGER.info("Setting up TOU Scheduler integration")
    # Perform any global setup here if needed
    _LOGGER.debug("TOU Scheduler integration setup complete (NOTHING TO DO)")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up TOU Scheduler from a config entry."""
    _LOGGER.info("Setting up TOU Scheduler entry: %s", entry.entry_id)
    try:
        # Initialize the Inverter API
        inverter_api = InverterAPI(
            username=entry.data["username"],
            password=entry.data["password"],
            timezone=hass.config.time_zone,
        )
        await inverter_api.authenticate()

        # Initialize the Solcast API
        solcast_api = SolcastAPI(
            api_key=entry.data["api_key"],
            resource_id=entry.data["resource_id"],
            timezone=hass.config.time_zone,
        )
        # await solcast_api.refresh_data()

        # Initialize the TOU Scheduler
        tou_scheduler = TOUScheduler(
            hass=hass,
            timezone=hass.config.time_zone,
            inverter_api=inverter_api,
            solcast_api=solcast_api,
        )
        # await tou_scheduler.update_sensors()

        # Create the UpdateCoordinator
        coordinator = TOUUpdateCoordinator(
            hass=hass,
            entry=entry,
            tou_scheduler=tou_scheduler,
        )
        await coordinator.async_start()
        await coordinator.async_config_entry_first_refresh()

        # Store the coordinator in hass.data[DOMAIN]
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

        # Forward the setup to the sensor platform
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    except Exception as e:  # noqa: BLE001
        _LOGGER.error("Error setting up TOU Scheduler entry: %s", e)
        return False

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry."""
    _LOGGER.info("Unloading TOU Scheduler entry: %s", entry.entry_id)
    try:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if unload_ok:
            hass.data[DOMAIN].pop(entry.entry_id)
    except KeyError as e:
        _LOGGER.error("Error unloading TOU Scheduler entry: %s", e)
        return False

    return unload_ok


@callback
def async_get_options_flow(config_entry: ConfigEntry) -> config_entries.OptionsFlow:
    """Get the options flow."""
    return TouSchedulerOptionFlow(config_entry)
