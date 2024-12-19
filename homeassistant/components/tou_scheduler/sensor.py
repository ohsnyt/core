"""Sensor platform for the TOU Scheduler integration."""

import logging

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
from .entity import (
    BatteryEntity,
    CloudEntity,
    InverterEntity,
    LoadEntity,
    PlantEntity,
    ShadingEntity,
    TOUSchedulerEntity,
)

logger = logging.getLogger(__name__)
if DEBUGGING:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


class OhSnytSensorEntityDescription(SensorEntityDescription):
    """Describes a sensor."""


TOU_SENSOR_ENTITIES: dict[str, OhSnytSensorEntityDescription] = {
    # Solcast related sensors
    "power_pv_estimated": OhSnytSensorEntityDescription(
        key="power_pv_estimated",
        translation_key="power_pv_estimated",
        has_entity_name=True,
        name="Estimated PV power",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "sun_ratio": OhSnytSensorEntityDescription(
        key="sun_ratio",
        translation_key="sun_ratio",
        has_entity_name=True,
        name="Ratio of full sun",
        icon="mdi:percent-outline",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "power_pv": OhSnytSensorEntityDescription(
        key="power_pv",
        translation_key="power_pv",
        has_entity_name=True,
        name="Power from PV",
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "batt_soc": OhSnytSensorEntityDescription(
        key="batt_soc",
        translation_key="batt_soc",
        has_entity_name=True,
        name="Battery State of Charge",
        icon="mdi:percent-outline",
        native_unit_of_measurement="%",
        suggested_unit_of_measurement="%",
        suggested_display_precision=0,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "batt_wh_usable": OhSnytSensorEntityDescription(
        key="batt_wh_usable",
        translation_key="batt_wh_usable",
        has_entity_name=True,
        name="Usable battery energy",
        icon="mdi:battery",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.ENERGY,
    ),
    "power_battery": OhSnytSensorEntityDescription(
        key="power_battery",
        translation_key="power_battery",
        has_entity_name=True,
        name="Power from (to) battery",
        icon="mdi:battery",
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "power_grid": OhSnytSensorEntityDescription(
        key="power_grid",
        translation_key="power_grid",
        has_entity_name=True,
        name="Power from (to) grid",
        icon="mdi:transmission-tower-import",
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "power_load": OhSnytSensorEntityDescription(
        key="power_load",
        translation_key="power_load",
        has_entity_name=True,
        name="Power to load",
        icon="mdi:power-socket-us",
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "grid_boost_soc": OhSnytSensorEntityDescription(
        key="grid_boost_soc",
        translation_key="grid_boost_soc",
        has_entity_name=True,
        name="Grid Boost SoC",
        icon="mdi:battery",
        native_unit_of_measurement="%",
        suggested_unit_of_measurement="%",
        suggested_display_precision=0,
        device_class=SensorDeviceClass.BATTERY,
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
    if coordinator.entry.data == {}:
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
            LoadEntity("ToU_Load", coordinator=coordinator),
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
        # Set the icon
        self._attr_icon = (
            entity_description.icon if entity_description.icon else "mdi:flash"
        )
        # Set the name and description
        self._attr_name = f"{entity_description.name}"
        self.entity_description = entity_description
        # And then set the key and sensor unique_id
        self._key = entry_id
        self._attr_unique_id = (
            f"{coordinator.data.get('plant_id', '??????')}_{entry_id}"
        )
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
    def unique_id(self) -> str:
        """Return a unique ID."""
        # This should always return a value - but error checking won't pass without this or statement.
        return self._attr_unique_id or "bogus_sensor_id"

    # @property
    # def state(self) -> str | int | float | None:
    #     """Return the state of the sensor."""
    #     return self.coordinator.data[self._key]
    @property
    def native_value(self) -> StateType | None | str | int | float:
        """Return the state of the sensor."""
        value = self.coordinator.data.get(self._key)
        if value is None:
            logger.error("No data found for key: %s", self._key)
        return value
