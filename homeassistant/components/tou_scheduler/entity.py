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
        self._key = f"tou_{im_a}"
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


class BatteryEntity(CoordinatorEntity):
    """TOU battery entity."""

    def __init__(
        self,
        entry_id: str,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        # parent: str,
    ) -> None:
        """Initialize the sensor."""
        im_a = "battery"
        plant_name = f"{coordinator.data.get('plant_name', 'My plant')}"

        super().__init__(coordinator)
        self._coordinator = coordinator
        self._key = f"tou_{im_a}"
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
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return self._device_info

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self._attr_unique_id


class PlantEntity(CoordinatorEntity):
    """Representation of a Plant."""

    def __init__(
        self,
        entry_id: str,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        # parent: str,
    ) -> None:
        """Initialize the sensor."""
        im_a = "plant"
        plant_name = f"{coordinator.data.get('plant_name', 'My plant')}"

        super().__init__(coordinator)
        self._coordinator = coordinator
        self._key = f"tou_{im_a}"
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_icon = "mdi:toggle-switch"
        self._attr_name = f"{plant_name} ToU {im_a}"
        self._device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=self._attr_name,
        )
        self._additional_device_info = {
            "plant_created": coordinator.data.get(
                "plant_created", "Plant created time n/a"
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

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return self._device_info


class InverterEntity(CoordinatorEntity):
    """Representation of a Plant."""

    def __init__(
        self,
        entry_id: str,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        # parent: str,
    ) -> None:
        """Initialize the sensor."""
        im_a = "inverter"
        plant_name = f"{coordinator.data.get('plant_name', 'My plant')}"

        super().__init__(coordinator)
        self._coordinator = coordinator
        self._key = f"tou_{im_a}"
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_icon = "mdi:toggle-switch"
        self._attr_name = f"{plant_name} ToU {im_a}"
        self._device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=self._attr_name,
        )
        self._additional_device_info = {
            "plant_created": coordinator.data.get(
                "plant_created", "Plant created time n/a"
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
        self._key = f"tou_{im_a}"
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


class CloudEntity(CoordinatorEntity):
    """Representation of a Cloud. Base the unique id on the user email (userId)."""

    def __init__(
        self,
        entry_id: str,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        # parent: str,
    ) -> None:
        """Initialize the sensor."""
        im_a = "cloud"
        plant_name = f"{coordinator.data.get('plant_name', 'My plant')}"

        super().__init__(coordinator)
        self._coordinator = coordinator
        self._key = f"tou_{im_a}"
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_icon = "mdi:toggle-switch"
        self._attr_name = f"{plant_name} ToU {im_a}"
        self._device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)}, name=self._attr_name
        )
        self.extra_state_attributes = {
            "created": coordinator.data.get("plant_created", "Plant created time n/a"),
            "bearer_token_expires_on": coordinator.data.get(
                "bearer_token_expires_on", "Unknown"
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

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return self._device_info


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
        self._key = f"tou_{im_a}"
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
