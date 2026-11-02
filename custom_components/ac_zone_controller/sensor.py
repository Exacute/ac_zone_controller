"""Diagnostic entities for room demand and solar state."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ROOM_KEY, CONF_ROOM_NAME
from .coordinator import ACZoneCoordinator


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up diagnostic sensors."""
    coordinator: ACZoneCoordinator = hass.data["ac_zone_controller"][entry.entry_id]
    entities: list[SensorEntity] = [
        SolarStatusSensor(coordinator),
    ]
    for room in coordinator.rooms:
        entities.append(RoomErrorSensor(coordinator, room))
    async_add_entities(entities)


class RoomErrorSensor(CoordinatorEntity[ACZoneCoordinator], SensorEntity):
    """Temperature error for a room relative to its active target."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ACZoneCoordinator, room: dict[str, Any]) -> None:
        """Bind the room error sensor to the current thermostat demand."""
        super().__init__(coordinator)
        self.room = room
        self._attr_name = f"{room[CONF_ROOM_NAME]} temperature error"
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{room[CONF_ROOM_KEY]}_error"
        )
        self._attr_device_info = {
            "identifiers": {
                ("ac_zone_controller", coordinator.entry.entry_id, room[CONF_ROOM_KEY])
            },
            "name": f"{room[CONF_ROOM_NAME]} AC zone",
            "manufacturer": "AC Zone Controller",
            "model": "Virtual room thermostat",
        }

    @property
    def native_value(self) -> float | None:
        """Return signed temperature error."""
        zone = (self.coordinator.data or {}).get("rooms", {}).get(
            self.room[CONF_ROOM_KEY], {}
        )
        error = zone.get("error")
        return round(float(error), 2) if error is not None else None


class SolarStatusSensor(CoordinatorEntity[ACZoneCoordinator], SensorEntity):
    """Report the integrated solar controller state."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Solar controller status"

    def __init__(self, coordinator: ACZoneCoordinator) -> None:
        """Bind the solar status sensor to the shared coordinator."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_solar_status"
        self._attr_device_info = {
            "identifiers": {("ac_zone_controller", coordinator.entry.entry_id)},
            "name": "AC Zone Controller",
            "manufacturer": "AC Zone Controller",
            "model": "Room coordinator",
        }

    @property
    def native_value(self) -> str:
        """Return current solar state."""
        data = self.coordinator.data or {}
        if self.coordinator.external_solar_owner():
            return "external"
        if not data.get("solar_enabled"):
            return "disabled"
        if data.get("solar_paused"):
            return "paused_low_generation"
        return "active"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose controller ownership and budget adjustment."""
        return {
            "external_solar_owner": self.coordinator.external_solar_owner(),
            "setpoint_offset": (self.coordinator.data or {}).get("solar_offset", 0.0),
        }
