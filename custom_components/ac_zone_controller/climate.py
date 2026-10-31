"""Per-room thermostat entities."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import HVACMode
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ROOM_KEY, CONF_ROOM_NAME, CONF_ROOM_TEMPERATURE, CONF_ROOMS
from .coordinator import ACZoneCoordinator


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up a thermostat climate entity for every configured room."""
    coordinator: ACZoneCoordinator = hass.data["ac_zone_controller"][entry.entry_id]
    async_add_entities(
        RoomThermostat(coordinator, room)
        for room in coordinator.rooms
    )


class RoomThermostat(CoordinatorEntity[ACZoneCoordinator], ClimateEntity):
    """A room target thermostat that follows the shared Daikin mode."""

    _attr_has_entity_name = True
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 16.0
    _attr_max_temp = 30.0
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: ACZoneCoordinator, room: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self.room = room
        self._attr_name = room[CONF_ROOM_NAME]
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{room[CONF_ROOM_KEY]}_thermostat"
        self._attr_device_info = {
            "identifiers": {
                ("ac_zone_controller", coordinator.entry.entry_id, room[CONF_ROOM_KEY])
            },
            "name": f"{room[CONF_ROOM_NAME]} AC zone",
            "manufacturer": "AC Zone Controller",
            "model": "Virtual room thermostat",
        }

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Report the physical Daikin mode without changing it."""
        mode = self.coordinator.physical_mode()
        if mode in (HVACMode.HEAT, HVACMode.COOL, HVACMode.FAN_ONLY, HVACMode.OFF):
            return HVACMode(mode)
        return None

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Expose the shared unit mode as read-only state."""
        mode = self.hvac_mode
        return [mode] if mode else []

    @property
    def current_temperature(self) -> float | None:
        """Return this room's sensor value."""
        state = self.coordinator.state(self.room[CONF_ROOM_TEMPERATURE])
        try:
            return float(state.state) if state is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def target_temperature(self) -> float | None:
        """Return this room's target for the selected global mode."""
        mode = self.coordinator.selected_mode()
        if mode not in (HVACMode.HEAT, HVACMode.COOL):
            return None
        return self.coordinator.room_target(self.room[CONF_ROOM_KEY], mode)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose room occupancy and control status."""
        data = (self.coordinator.data or {}).get("rooms", {}).get(
            self.room[CONF_ROOM_KEY], {}
        )
        return {
            "occupied": data.get("occupied"),
            "zone_enabled": data.get("enabled"),
            "temperature_error": data.get("error"),
            "vent_position_target": data.get("desired_position"),
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target for the Daikin's currently selected mode."""
        mode = self.coordinator.selected_mode()
        if mode not in (HVACMode.HEAT, HVACMode.COOL):
            return
        value = kwargs.get("temperature")
        if value is None:
            return
        setting = "target_heat" if mode == HVACMode.HEAT else "target_cool"
        await self.coordinator.async_set_setting(
            setting,
            float(value),
            room=self.room[CONF_ROOM_KEY],
        )
