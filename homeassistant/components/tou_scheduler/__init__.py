"""The Time of Use Scheduler integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

# from homeassistant.helpers import discovery
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .tou_scheduler import TOUScheduler

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the TOU Scheduler integration."""
    # Perform any global setup here if needed
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up TOU Scheduler from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    scheduler = TOUScheduler(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = scheduler

    # Forward the setup to the sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start the scheduler
    # await scheduler.async_start()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    scheduler = hass.data[DOMAIN].pop(entry.entry_id)
    await scheduler.async_stop()

    # Unload the sensor platform
    await hass.config_entries.async_forward_entry_unload(entry, Platform.SENSOR)

    return True
