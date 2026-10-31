"""Optional integrated solar controller switch."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ACZoneCoordinator


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up the solar controller switch."""
    coordinator: ACZoneCoordinator = hass.data["ac_zone_controller"][entry.entry_id]
    async_add_entities([SolarControllerSwitch(coordinator)])


class SolarControllerSwitch(CoordinatorEntity[ACZoneCoordinator], SwitchEntity):
    """Enable the integrated solar monitor after JARVIS is retired."""

    _attr_has_entity_name = True
    _attr_name = "Integrated solar cooling"
    _attr_icon = "mdi:solar-power"

    def __init__(self, coordinator: ACZoneCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_solar_enabled"
        self._attr_device_info = {
            "identifiers": {("ac_zone_controller", coordinator.entry.entry_id)},
            "name": "AC Zone Controller",
            "manufacturer": "AC Zone Controller",
            "model": "Room coordinator",
        }

    @property
    def is_on(self) -> bool:
        """Return whether the integrated solar monitor is enabled."""
        return bool(self.coordinator.settings.get("solar_enabled", False))

    @property
    def extra_state_attributes(self) -> dict[str, bool]:
        """Show whether JARVIS still owns solar control."""
        return {"external_solar_owner": self.coordinator.external_solar_owner()}

    async def async_turn_on(self, **kwargs) -> None:
        """Enable solar controller."""
        await self.coordinator.async_set_solar_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable solar controller."""
        await self.coordinator.async_set_solar_enabled(False)
