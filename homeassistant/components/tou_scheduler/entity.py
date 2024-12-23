"""Entity classes for TOU Scheduler entity.

This module defines various entity classes used in the TOU (Time of Use) Scheduler integration.
Each entity class represents a different aspect of the TOU Scheduler, such as battery, plant, inverter, shading, cloud, and load.
These entities are used to monitor and manage different components of a solar power system, providing information such as shading ratios, battery status, plant information, and average daily load.
"""

import ast
import logging
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DEBUGGING, DOMAIN

logger = logging.getLogger(__name__)
if DEBUGGING:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


class TOUSchedulerEntity(CoordinatorEntity):
    """Class for TOU Scheduler entity."""

    def __init__(
        self,
        entry_id: str,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        # parent: str,
    ) -> None:
        """Initialize the sensor."""
        im_a: str = "scheduler"
        plant_name = f"{coordinator.data.get('plant_name', 'My plant')}"

        super().__init__(coordinator)
        self._key = im_a
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_icon = "mdi:toggle-switch"
        self._attr_name = f"{plant_name} ToU {im_a}"
        self._device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=self._attr_name,
        )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the extra state attributes."""
        return {
            "created": self.coordinator.data.get(
                "plant_created", "Plant created time n/a"
            ),
            "cloud_name": self.coordinator.data.get("cloud_name", "Cloud name n/a"),
            "cloud_token_refresh": self.coordinator.data.get(
                "bearer_token_expires_on", "Unknown"
            ),
            "plant_name": self.coordinator.data.get("plant_name", "Plant name n/a"),
            "plant_status": self.coordinator.data.get(
                "plant_status", "Plant status n/a"
            ),
            "inverter_model": self.coordinator.data.get(
                "inverter_model", "Inverter model n/a"
            ),
            "inverter_status": self.coordinator.data.get(
                "inverter_status", "Inverter status n/a"
            ),
            "battery_status": self.coordinator.data.get(
                "battery_status", "Battery status n/a"
            ),
        }

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self._attr_unique_id


class ShadingEntity(CoordinatorEntity):
    """Representation of a Shading.

    This sensor is used to display the shading ratio for each hour of the day if available.
    If there is no sun expected at a certain hour, no ratio will be listed.
    If we are unable to get the shading ratio, the sensor will display "No shading percentages available".
    """

    def __init__(
        self,
        entry_id: str,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        # parent: str,
    ) -> None:
        """Initialize the sensor."""
        im_a = "shading"
        plant_name = f"{coordinator.data.get('plant_name', 'My plant')}"

        super().__init__(coordinator)
        self._coordinator = coordinator
        self._key = im_a
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_icon = "mdi:toggle-switch"
        self._attr_name = f"{plant_name} ToU {im_a}"
        self._device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=self._attr_name,
        )

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self._attr_unique_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return self._device_info

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the hourly shade values as dict[str,str]."""
        hours = ast.literal_eval(self._coordinator.data.get("shading", "{}"))
        attributes = {
            f"{'  ' if (hour % 12 or 12) < 10 else ''}{hour % 12 or 12:2} {'am' if hour < 12 else 'pm'}": f"{value * 100:.1f}%"
            for hour, value in hours.items()
        }
        if not attributes:
            return {"No shading found": ""}
        return attributes


class LoadEntity(CoordinatorEntity):
    """Representation of the average daily load.

    This sensor is used to display the average daily load for each hour of the day if available.
    """

    def __init__(
        self,
        entry_id: str,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        # parent: str,
    ) -> None:
        """Initialize the sensor."""
        im_a = "load"
        plant_name = f"{coordinator.data.get('plant_name', 'My plant')}"

        super().__init__(coordinator)
        self._coordinator = coordinator
        self._key = im_a
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_icon = "mdi:toggle-switch"
        self._attr_name = f"{plant_name} ToU {im_a}"
        self._device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=self._attr_name,
        )

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self._attr_unique_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return self._device_info

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the hourly load values as dict[str,str]."""
        hours = ast.literal_eval(self._coordinator.data.get("load", "{}"))
        attributes = {
            f"{'  ' if (hour % 12 or 12) < 10 else ''}{hour % 12 or 12} {'am' if hour < 12 else 'pm'}": f"{value:.1f} kWh"
            for hour, value in hours.items()
        }
        if not attributes:
            return {"No load averages available": ""}
        return attributes
