"""The Time of Use Scheduler integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

# from homeassistant.helpers import discovery
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .coordinator import OhSnytUpdateCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the TOU Scheduler integration."""
    # Perform any global setup here if needed

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up TOU Scheduler coordinator from a config entry."""
    # Create the UpdateCoordinator.
    coordinator = OhSnytUpdateCoordinator(
        hass=hass,
        entry=entry,
    )
    await coordinator.async_start()
    await coordinator.async_config_entry_first_refresh()

    # Store the coordinator in hass.data[DOMAIN]
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Forward the setup to the sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update our options."""
    await hass.config_entries.async_reload(entry.entry_id)
