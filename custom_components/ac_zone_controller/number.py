"""Tuning and per-room target number entities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature, UnitOfTime
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ROOM_GAIN, CONF_ROOM_KEY, CONF_ROOM_NAME
from .coordinator import ACZoneCoordinator


@dataclass(frozen=True, kw_only=True)
class SettingDescription:
    key: str
    name: str
    minimum: float
    maximum: float
    step: float
    unit: str | None = None
    room_key: str | None = None
    default: float = 0.0


GLOBAL_SETTINGS = (
    SettingDescription(key="temperature_tolerance", name="Temperature tolerance", minimum=0.1, maximum=3.0, step=0.1, unit=UnitOfTemperature.CELSIUS, default=0.6),
    SettingDescription(key="reached_delay", name="Target reached delay", minimum=0.0, maximum=3600.0, step=1.0, unit=UnitOfTime.SECONDS, default=5.0),
    SettingDescription(key="vent_step", name="Vent step size", minimum=1.0, maximum=50.0, step=1.0, unit=PERCENTAGE, default=10.0),
    SettingDescription(key="hot_differential", name="Heating differential", minimum=0.1, maximum=5.0, step=0.1, unit=UnitOfTemperature.CELSIUS, default=1.0),
    SettingDescription(key="cold_differential", name="Cooling differential", minimum=0.1, maximum=5.0, step=0.1, unit=UnitOfTemperature.CELSIUS, default=1.0),
    SettingDescription(key="heating_adjust_step", name="Heating target nudge", minimum=0.1, maximum=2.0, step=0.1, unit=UnitOfTemperature.CELSIUS, default=0.5),
    SettingDescription(key="solar_fan_temperature", name="Solar fan-first temperature", minimum=18.0, maximum=30.0, step=0.1, unit=UnitOfTemperature.CELSIUS, default=24.3),
    SettingDescription(key="solar_cool_temperature", name="Solar cooling threshold", minimum=18.0, maximum=35.0, step=0.1, unit=UnitOfTemperature.CELSIUS, default=26.0),
    SettingDescription(key="solar_low_generation", name="Low solar generation threshold", minimum=0.0, maximum=5000.0, step=10.0, unit=UnitOfPower.WATT, default=100.0),
    SettingDescription(key="solar_resume_generation", name="Solar resume threshold", minimum=0.0, maximum=10000.0, step=10.0, unit=UnitOfPower.WATT, default=500.0),
    SettingDescription(key="solar_grid_limit", name="Maximum grid import for cooling", minimum=0.0, maximum=3000.0, step=10.0, unit=UnitOfPower.WATT, default=50.0),
    SettingDescription(key="solar_headroom_reference", name="Solar headroom reference", minimum=50.0, maximum=10000.0, step=50.0, unit=UnitOfPower.WATT, default=500.0),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up setting entities."""
    coordinator: ACZoneCoordinator = hass.data["ac_zone_controller"][entry.entry_id]
    entities: list[NumberEntity] = [
        ACSettingNumber(coordinator, setting)
        for setting in GLOBAL_SETTINGS
    ]
    for room in coordinator.rooms:
        key = room[CONF_ROOM_KEY]
        name = room[CONF_ROOM_NAME]
        entities.extend(
            [
                ACSettingNumber(
                    coordinator,
                    SettingDescription(
                        key="target_heat",
                        name=f"{name} heating target",
                        minimum=16.0,
                        maximum=30.0,
                        step=0.5,
                        unit=UnitOfTemperature.CELSIUS,
                        room_key=key,
                        default=23.5,
                    ),
                ),
                ACSettingNumber(
                    coordinator,
                    SettingDescription(
                        key="target_cool",
                        name=f"{name} cooling target",
                        minimum=16.0,
                        maximum=30.0,
                        step=0.5,
                        unit=UnitOfTemperature.CELSIUS,
                        room_key=key,
                        default=22.0,
                    ),
                ),
            ]
        )
        if not room.get(CONF_ROOM_GAIN):
            entities.append(
                ACSettingNumber(
                    coordinator,
                    SettingDescription(
                        key="gain",
                        name=f"{name} gain",
                        minimum=0.5,
                        maximum=2.0,
                        step=0.01,
                        room_key=key,
                        default=1.0,
                    ),
                )
            )
    async_add_entities(entities)


class ACSettingNumber(CoordinatorEntity[ACZoneCoordinator], NumberEntity):
    """Persistent integration setting."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: ACZoneCoordinator,
        description: SettingDescription,
    ) -> None:
        super().__init__(coordinator)
        self.description = description
        self._attr_name = description.name
        room_part = description.room_key or "global"
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{room_part}_{description.key}"
        )
        self._attr_native_min_value = description.minimum
        self._attr_native_max_value = description.maximum
        self._attr_native_step = description.step
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_info = {
            "identifiers": {("ac_zone_controller", coordinator.entry.entry_id)},
            "name": "AC Zone Controller",
            "manufacturer": "AC Zone Controller",
            "model": "Room coordinator",
        }

    @property
    def native_value(self) -> float:
        """Return current setting."""
        return self.coordinator.setting(
            self.description.key,
            room=self.description.room_key,
            default=self.description.default,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Persist a setting and refresh control."""
        room_key = self.description.room_key
        if room_key and self.description.key == "gain":
            room = next(
                (item for item in self.coordinator.rooms if item[CONF_ROOM_KEY] == room_key),
                None,
            )
            gain_entity = room.get(CONF_ROOM_GAIN) if room else None
            if gain_entity:
                await self.hass.services.async_call(
                    "input_number",
                    "set_value",
                    {"entity_id": gain_entity, "value": value},
                    blocking=True,
                )
        await self.coordinator.async_set_setting(
            self.description.key,
            value,
            room=room_key,
        )
