"""Sensor platform for the TOU Scheduler integration."""

import logging

from entities import TOUSensorEntityDescription

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEBUGGING, DOMAIN
from .coordinator import OhSnytUpdateCoordinator
from .entities import (
    BatteryEntity,
    CloudEntity,
    InverterEntity,
    PlantEntity,
    ShadingEntity,
)
from .entity import TOUSchedulerEntity

logger = logging.getLogger(__name__)
if DEBUGGING:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


class OhSnytSensorEntityDescription(SensorEntityDescription):
    """Describes a sensor."""


TOU_SENSOR_ENTITIES: dict[str, TOUSensorEntityDescription] = {
    # Solcast related sensors
    "estimated_pv_power": TOUSensorEntityDescription(
        key="estimated_pv_power",
        translation_key="estimated_pv_power",
        has_entity_name=True,
        name="estimated_pv_power",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "sun": TOUSensorEntityDescription(
        key="sun",
        translation_key="sun",
        has_entity_name=True,
        name="sun",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "pv_power": TOUSensorEntityDescription(
        key="pv_power",
        translation_key="pv_power",
        has_entity_name=True,
        name="pv_power",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "battery_state_of_charge": TOUSensorEntityDescription(
        key="battery_state_of_charge",
        translation_key="battery_state_of_charge",
        has_entity_name=True,
        name="battery_state_of_charge",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "batt_wh_usable": TOUSensorEntityDescription(
        key="batt_wh_usable",
        translation_key="batt_wh_usable",
        has_entity_name=True,
        name="batt_wh_usable",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "batt_soc": TOUSensorEntityDescription(
        key="batt_soc",
        translation_key="batt_soc",
        has_entity_name=True,
        name="batt_soc",
        native_unit_of_measurement="%",
        suggested_unit_of_measurement="%",
        suggested_display_precision=0,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "power_battery": TOUSensorEntityDescription(
        key="power_battery",
        translation_key="power_battery",
        has_entity_name=True,
        name="power_battery",
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "power_grid": TOUSensorEntityDescription(
        key="power_grid",
        translation_key="power_grid",
        has_entity_name=True,
        name="power_grid",
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "power_load": TOUSensorEntityDescription(
        key="power_load",
        translation_key="power_load",
        has_entity_name=True,
        name="power_load",
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "power_pv": TOUSensorEntityDescription(
        key="power_pv",
        translation_key="power_pv",
        has_entity_name=True,
        name="power_pv",
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up individual sensors."""

    # Get the coordinator from hass.data (It should already have data.)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    # Double check that we have data
    if coordinator.data == {}:
        await coordinator.async_request_refresh()

    # Add the entity device level sensors: Cloud, Plant, Inverter, Solcast, Shading.
    async_add_entities(
        [
            TOUSchedulerEntity("ToU_Scheduler", coordinator=coordinator),
            BatteryEntity("ToU_Battery", coordinator=coordinator),
            CloudEntity("ToU_Cloud", coordinator=coordinator),
            PlantEntity("ToU_Plant", coordinator=coordinator),
            InverterEntity("ToU_Inverter", coordinator=coordinator),
            ShadingEntity("ToU_Shading", coordinator=coordinator),
        ]
    )
    # Add the "normal" Sol-Ark sensors for the inverter
    async_add_entities(
        [
            OhSnytSensor(
                entry_id=entry.entry_id,
                coordinator=coordinator,
                entity_description=entity_description,
            )
            for entity_description in TOU_SENSOR_ENTITIES.values()
        ]
    )


class OhSnytSensor(CoordinatorEntity[OhSnytUpdateCoordinator], SensorEntity):
    """Representation of a Solark Cloud sensor."""

    entity_description: OhSnytSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        *,
        entry_id: str,
        coordinator: OhSnytUpdateCoordinator,
        entity_description: OhSnytSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = f"Solark {entity_description.name}"
        self.entity_description = entity_description

        # And then set the sensor unique_id and device_info
        self._key = entity_description.key
        self._attr_unique_id = f"{entry_id}_{self._key}"
        # self._device_info = entity_description
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
    def native_value(self) -> StateType | None | str | int | float:
        """Return the state of the sensor."""
        value = self.coordinator.data.get(self._key)
        if value is None:
            logger.error("No data found for key: %s", self._key)
        return value
