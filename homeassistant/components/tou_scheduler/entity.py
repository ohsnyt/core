"""Entity classes for TOU Scheduler entity."""

import ast
import logging
from typing import Any

from homeassistant.components.sensor import SensorStateClass
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DEBUGGING, DOMAIN
from .solark_inverter_api import Inverter, Plant

logger = logging.getLogger(__name__)
if DEBUGGING:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


class TOUSchedulerEntity(CoordinatorEntity):
    """Class for TOU Scheduler entity."""

    def __init__(
        self, entry_id: str, coordinator: DataUpdateCoordinator[dict[str, Any]]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._name = "tou_scheduler"
        self._key = "tou_scheduler"

        # Set the icon
        self._attr_icon = "mdi:toggle-switch"
        # Set the unique_id of the sensor
        self._attr_unique_id = (
            f"{coordinator.data.get('plant_id', '??????')}_tou_scheduler"
        )
        self._attr_name = (
            f"{coordinator.data.get('plant_name', 'My plant')} ToU scheduler"
        )
        self._device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": self.name,
            "manufacturer": "Sol-Ark",
        }
        # Set the entity ID with the "tou" prefix
        plant_name = f"{self.coordinator.data.get("plant_name", "Sol-Ark")}"
        self.entity_id = generate_entity_id(
            "tou.{}", f"{plant_name}_scheduler", hass=coordinator.hass
        )

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def state(self) -> str:
        """Return the state of the grid boost."""
        return (
            "Boost ON"
            if self.coordinator.data.get("grid_boost_on", "off") == "on"
            else "Boost OFF"
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return self._device_info

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self._attr_unique_id


class BatteryEntity(CoordinatorEntity):
    """TOU battery entity."""

    def __init__(
        self, entry_id: str, coordinator: DataUpdateCoordinator[dict[str, Any]]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._name = "battery"
        self._key = "battery"

        # Set the icon
        self._attr_icon = "mdi:clock-time-eleven-outline"
        # Set the unique_id of the sensor
        self._attr_unique_id = f"{coordinator.data.get('plant_id', '??????')}_Battery"
        self._attr_name = (
            f"{coordinator.data.get('plant_name', 'Sol-Ark Plant')} battery "
        )
        self._device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": self.name,
            "manufacturer": "EG4",
        }
        # Set the entity ID with the "tou" prefix
        plant_name = f"{self.coordinator.data.get("plant_name", "Sol-Ark")}"
        self.entity_id = generate_entity_id(
            "tou.{}", f"{plant_name}_battery", hass=coordinator.hass
        )

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def state(self) -> str:
        """Return the state of the battery in hours."""
        return f"{round(self.coordinator.data.get('battery_minutes', 0)/60, 1)} hours remaining"

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
        self, entry_id: str, coordinator: DataUpdateCoordinator[dict[str, Any]]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        # Set the icon
        self._attr_icon = "mdi:solar-power"
        self._name = "plant"
        self._key = "plant"

        self._attr_unique_id = f"{coordinator.data.get('plant_id', '??????')}"
        self._attr_name = f"{self.coordinator.data.get("plant_name", "Sol-Ark")} plant"
        self._device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": self.name,
            "manufacturer": "Sol-Ark",
        }
        self._additional_device_info = {
            "plant_created": self.coordinator.data.get(
                "plant_created", "Plant created time not available"
            ),
        }
        # Set the entity ID with the "tou" prefix
        plant_name = f"{self.coordinator.data.get("plant_name", "Sol-Ark")}"
        self.entity_id = generate_entity_id(
            "tou.{}", f"{plant_name}_plant", hass=coordinator.hass
        )

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return Plant.UNKNOWN.name
        return self.coordinator.data.get("plant_status", Plant.UNKNOWN.name)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return self._device_info

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self._attr_unique_id


class InverterEntity(CoordinatorEntity):
    """Representation of a Plant."""

    def __init__(
        self, entry_id: str, coordinator: DataUpdateCoordinator[dict[str, Any]]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._name = "inverter"
        self._key = "inverter"

        # Set the icon
        self._attr_icon = "mdi:application-cog"

        # Set the unique_id and name of the sensor
        self._attr_unique_id = (
            f"{self.coordinator.data.get('inverter_serial_number', 'Missing SN')}"
        )
        self._attr_name = f"{self.coordinator.data.get('plant_name', None)} inverter"
        # Set the extra device info
        self._additional_device_info = {
            "model": self.coordinator.data.get("inverter_model", None),
            "serial_number": self.coordinator.data.get("inverter_serial_number", None),
        }
        # Set the device info
        self._device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Sol-Ark Inverter",
            "manufacturer": "Sol-Ark",
            "model": self.coordinator.data.get("inverter_model", "Unknown Model"),
        }
        # Set the entity ID with the "tou" prefix
        plant_name = f"{self.coordinator.data.get("plant_name", "Sol-Ark")}"
        self.entity_id = generate_entity_id(
            "tou.{}", f"{plant_name}_inverter", hass=coordinator.hass
        )

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return Plant.UNKNOWN.name
        return self.coordinator.data.get("inverter_status", Inverter.UNKNOWN.name)

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
        self, entry_id: str, coordinator: DataUpdateCoordinator[dict[str, Any]]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._name = "shading"
        self._key = "shading"
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:weather-sunny"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._hours: dict[int, float] = {}

        # Set the unique_id and name of the sensor
        self._attr_unique_id = f"{coordinator.data.get('plant_id', '??????')}_Shading"
        self._attr_name = "Daily average shading"
        self._device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": self._name,
            "manufacturer": "OhSnyt",
        }
        # Set the entity ID with the "tou" prefix
        plant_name = f"{self.coordinator.data.get("plant_name", "Sol-Ark")}"
        self.entity_id = generate_entity_id(
            "tou.{}", f"{plant_name}_avg_load", hass=coordinator.hass
        )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the hourly shade values as dict[str,str]."""
        hours = ast.literal_eval(self.coordinator.data.get("shading", "{}"))
        attributes = {
            f"{'  ' if (hour % 12 or 12) < 10 else ''}{hour % 12 or 12:2} {'am' if hour < 12 else 'pm'}": f"{value * 100:.1f}%"
            for hour, value in hours.items()
        }
        if not attributes:
            return {"No shading found": ""}
        return attributes

    @property
    def state(self) -> str:
        """Return the average shading for the day."""
        hours = ast.literal_eval(self.coordinator.data.get("shading", {}))
        return (
            f"{sum(map(float, hours.values())) / len(hours) * 100:.1f}%"
            if hours
            else "0%"
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return self._device_info

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self._attr_unique_id

    @property
    def icon(self) -> str:
        """Return the icon based on the current state of the sensor sun in this integration."""
        state = self.hass.states.get("sensor.tou_sun")
        state_value = state.state if state else "unknown"
        state_icon_map = {
            "full": "mdi:sun-thermometer",
            "partial": "mdi:weather-partly-cloudy",
            "dark": "mdi:weather-night",
        }
        return state_icon_map.get(state_value, "mdi:progress-question")


class CloudEntity(CoordinatorEntity):
    """Representation of a Cloud. Base the unique id on the user email (userId)."""

    def __init__(
        self, entry_id: str, coordinator: DataUpdateCoordinator[dict[str, Any]]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._name = "solark_cloud"
        self._key = "solark_cloud"

        self._attr_icon = "mdi:cloud"

        # Set the unique_id of the sensor
        self._attr_unique_id = (
            f"{coordinator.data.get('plant_id', '??????')}_solark_sloud"
        )
        self._attr_name = self.coordinator.data.get("cloud_name", "Sol-Ark Cloud")
        self._device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": self.name,
            "manufacturer": "Sol-Ark",
        }
        # Set the entity ID with the "tou" prefix
        plant_name = f"{self.coordinator.data.get("plant_name", "Sol-Ark")}"
        self.entity_id = generate_entity_id(
            "tou.{}", f"{plant_name}_solark_cloud", hass=coordinator.hass
        )

    @property
    def attributes(self) -> dict[str, Any]:
        """Return the created date and bearer_token expiry date for the cloud sensor."""
        return {
            "created": self.coordinator.data["plant_created"],
            "bearer_token_expires_on": self.coordinator.data.get(
                "bearer_token_expires_on", "Unknown"
            ),
        }

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        data_updated = self.coordinator.data.get("data_updated")
        if data_updated:
            return "Retrieved " + data_updated
        return "Update time not available"

    @property
    def status(self) -> str:
        """Return the status of the sensor."""
        status = self.coordinator.data.get("cloud_status", "Unknown")
        return status if isinstance(status, str) else "Unknown"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return self._device_info

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self._attr_unique_id


class LoadEntity(CoordinatorEntity):
    """Representation of the average daily load.

    This sensor is used to display the average daily load for each hour of the day if available.
    """

    def __init__(
        self, entry_id: str, coordinator: DataUpdateCoordinator[dict[str, Any]]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._name = "daily_average_load"
        self._key = "daily_average_load"
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:power-socket-us"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._hours: dict[int, float] = {}

        # Set the unique_id and name of the sensor
        self._attr_unique_id = (
            f"{coordinator.data.get('plant_id', '??????')}_daily_average_load"
        )
        self._attr_name = "Daily average load"
        self._device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": self._name,
            "manufacturer": "OhSnyt",
        }
        # Set the entity ID with the "tou" prefix
        plant_name = f"{self.coordinator.data.get("plant_name", "Sol-Ark")}"
        self.entity_id = generate_entity_id(
            "tou.{}", f"{plant_name}_avg_load", hass=coordinator.hass
        )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the hourly load values as dict[str,str]."""
        hours = ast.literal_eval(self.coordinator.data.get("load", "{}"))
        attributes = {
            f"{'  ' if (hour % 12 or 12) < 10 else ''}{hour % 12 or 12} {'am' if hour < 12 else 'pm'}": f"{value:.1f} kWh"
            for hour, value in hours.items()
        }
        if not attributes:
            return {"No load averages available": ""}
        return attributes

    @property
    def state(self) -> str:
        """Return the average load for the day."""
        hours = ast.literal_eval(self.coordinator.data.get("load", {}))
        return (
            f"{sum(map(float, hours.values())) / len(hours) / 1000:.1f} kWh"
            if hours
            else "unknown"
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return self._device_info

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self._attr_unique_id
