"""Entity classes for TOU Scheduler entity."""

from datetime import UTC
import logging
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import SensorStateClass
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DEBUGGING, DOMAIN
from .inverter import Inverter, Plant

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

        # Set the icon
        self._attr_icon = "mdi:clock-time-four-outline"
        # Set the unique_id of the sensor
        plant_id = (
            f"{entry_id}_{coordinator.data.get('plant_id', 'Plant ID not available')}"
        )
        self._attr_unique_id = f"{plant_id}_Inverter_ToU_settings"
        self._attr_name = (
            f"{coordinator.data.get('inverter_sn', 'My Inverter')} ToU settings"
        )
        self._device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": self.name,
            "manufacturer": "Sol-Ark",
        }

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def state(self) -> str:
        """Return the state of the grid boost."""
        return (
            "Boost ON"
            if self.coordinator.data.get("grid_boost_on", "OFF") == "ON"
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

        # Set the icon
        self._attr_icon = "mdi:clock-time-four-outline"
        # Set the unique_id of the sensor
        plant_id = (
            f"{entry_id}_{coordinator.data.get('plant_id', 'Plant ID not available')}"
        )
        self._attr_unique_id = f"{plant_id}_Battery"
        self._attr_name = (
            f"{coordinator.data.get('plant_name', 'Sol-Ark Plant')} Battery "
        )
        self._device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": self.name,
            "manufacturer": "EG4",
        }

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def state(self) -> str:
        """Return the state of the battery in hours."""
        return f"{round(self.coordinator.data.get('battery_minutes', 0)/60, 1)} hours of battery remaining"

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

        self._attr_unique_id = f"{entry_id}_{self.coordinator.data.get('plant_id', "Plant ID not available")}"
        self._attr_name = self.coordinator.data.get("plant_name", "Sol-Ark Plant")
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

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        status = self.coordinator.data.get("plant_status", Plant.UNKNOWN)
        return status if isinstance(status, str) else Plant.UNKNOWN

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

        # Set the icon
        self._attr_icon = "mdi:application-cog"

        # Set the unique_id and name of the sensor
        self._attr_unique_id = f"{entry_id}_{self.coordinator.data.get('inverter_serial_number', 'Missing SN')}"
        self._attr_name = f"{self.coordinator.data.get('plant_name', None)} Inverter"
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

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        status = self.coordinator.data.get("inverter_status", Inverter.UNKNOWN)
        return status if isinstance(status, str) else Inverter.UNKNOWN

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
        self._name = "Shading"
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:cloud-sun"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._hours: dict[int, float] = {}

        # Set the unique_id and name of the sensor
        self._attr_unique_id = f"{entry_id}_Shading"
        self._attr_name = "Shading expected"
        self._device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": self._name,
            "manufacturer": "OhSnyt",
        }

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the hourly shade values as dict[str,str]."""
        return {
            f"{hour % 12 or 12} {'am' if hour < 12 else 'pm'}": f"{round(float(value) * 100)}%"
            for hour, value in self._hours.items()
        }

    @property
    def state(self) -> str:
        """Return the average shading for the day."""
        self._hours = self.coordinator.data.get("shading", {})
        if self._hours:
            average = sum(map(float, self._hours.values())) / len(self._hours)
            return f"Average shading: {round(average * 100)}%"
        return "No shading info available"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return self._device_info

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self._attr_unique_id


class CloudEntity(CoordinatorEntity):
    """Representation of a Cloud. Base the unique id on the user email (userId)."""

    def __init__(
        self, entry_id: str, coordinator: DataUpdateCoordinator[dict[str, Any]]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        # Set the icon
        self._attr_icon = "mdi:cloud"
        # Set the unique_id of the sensor
        plant_id = self.coordinator.data.get("plant_id", "Missing Plant ID")
        self._attr_unique_id = f"{plant_id}_Solark_Cloud"
        self._attr_name = self.coordinator.data.get("cloud_name", "Sol-Ark Cloud")
        self._device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": self.name,
            "manufacturer": "Sol-Ark",
        }

    @property
    def attributes(self) -> dict[str, Any]:
        """Return the created date and bearer_token expiry date for the cloud sensor."""
        return {
            "created": self.coordinator.data["plant_created"]
            .replace(tzinfo=UTC)
            .astimezone(ZoneInfo("America/Chicago"))
            .strftime("%I:%M %p"),
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
            return "Updated at " + data_updated.strftime("%I:%M %p")
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
