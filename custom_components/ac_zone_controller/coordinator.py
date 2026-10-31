"""Runtime room thermostat and central AC controller."""
from __future__ import annotations

from datetime import timedelta
import json
import logging
from typing import Any

from homeassistant.components.climate.const import HVACMode
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import *

_LOGGER = logging.getLogger(__name__)
CONDITIONING = {HVACMode.HEAT, HVACMode.COOL}
FAN = HVACMode.FAN_ONLY
ACTIVE_MEDIA_STATES = {"on", "playing", "paused", "buffering"}


def numeric(state: Any, default: float | None = None) -> float | None:
    """Read a finite numeric entity state."""
    try:
        value = float(state.state)
    except (AttributeError, TypeError, ValueError):
        return default
    return value if value == value and abs(value) != float("inf") else default


class ACZoneCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate room thermostats through one manually selected Daikin mode."""

    def __init__(self, hass: HomeAssistant, entry: Any) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN,
                         update_interval=timedelta(seconds=30))
        self.entry = entry
        self.entities = dict(entry.data)
        self.rooms = list(entry.options.get(CONF_ROOMS, []))
        self.settings = dict(DEFAULTS)
        self.settings.update(entry.options.get(CONF_SETTINGS, {}))
        self.settings.setdefault("rooms", {})
        for room in self.rooms:
            heat, cool, gain = ROOM_DEFAULTS.get(room[CONF_ROOM_KEY], (23.5, 22.0, 1.0))
            self.settings["rooms"].setdefault(room[CONF_ROOM_KEY], {
                "target_heat": heat, "target_cool": cool, "gain": gain,
            })
        self._store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}")
        self._unsubscribers: list[Any] = []
        self._loaded = False
        self._last_mode: str | None = None
        self._pending_mode: str | None = None
        self.previous_mode: str | None = None
        self.fan_owned = False
        self.target_stable_since: float | None = None
        self.last_tuned = 0.0
        self.last_solar_tick = 0.0
        self.low_generation_ticks = 0
        self.solar_paused = False
        self.solar_powered_off = False
        self.solar_offset = 0.0
        self.zone_status: dict[str, dict[str, Any]] = {}
        self._adjust_states: dict[str, bool] = {}

    async def async_start(self) -> None:
        """Restore state, watch inputs, and start periodic control."""
        data = await self._store.async_load() or {}
        self.settings.update(data.get("settings", {}))
        room_settings = self.settings.setdefault("rooms", {})
        for room in self.rooms:
            heat, cool, gain = ROOM_DEFAULTS.get(room[CONF_ROOM_KEY], (23.5, 22.0, 1.0))
            room_settings.setdefault(room[CONF_ROOM_KEY], {
                "target_heat": heat, "target_cool": cool, "gain": gain,
            })
        self.previous_mode = data.get("previous_mode")
        self.fan_owned = bool(data.get("fan_owned", False))
        self.last_tuned = float(data.get("last_tuned", 0.0))
        self.solar_paused = bool(data.get("solar_paused", False))
        self.solar_powered_off = bool(data.get("solar_powered_off", False))
        self.low_generation_ticks = int(data.get("low_generation_ticks", 0))
        self._adjust_states = {key: False for key in (CONF_HEAT_ADJUST_UP, CONF_HEAT_ADJUST_DOWN)}
        self._loaded = True
        await self._restore_gain_snapshot()

        watched: set[str] = set()
        for value in self.entities.values():
            if isinstance(value, str):
                watched.add(value)
            elif isinstance(value, list):
                watched.update(item for item in value if isinstance(item, str))
        for room in self.rooms:
            watched.update(room.get(key) for key in (
                CONF_ROOM_TEMPERATURE, CONF_ROOM_COVER, CONF_ROOM_ENABLED, CONF_ROOM_GAIN
            ) if room.get(key))
            watched.update(room.get(CONF_ROOM_PRESENCE, []))
        self._unsubscribers.append(async_track_state_change_event(
            self.hass, list(watched), self._handle_state_change
        ))
        await self.async_config_entry_first_refresh()

    async def async_stop(self) -> None:
        """Remove state and timer listeners."""
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()

    async def _handle_state_change(self, event: Event) -> None:
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        if not self._loaded:
            raise UpdateFailed("Controller state has not loaded")
        try:
            await self._control()
            return {
                "rooms": self.zone_status,
                "mode": self.selected_mode(),
                "solar_enabled": bool(self.settings.get("solar_enabled", False)),
                "solar_paused": self.solar_paused,
                "solar_offset": self.solar_offset,
                "external_solar_owner": self.external_solar_owner(),
            }
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("AC zone control cycle failed")
            raise UpdateFailed(f"AC zone control cycle failed: {err}") from err

    def state(self, entity_id: str | None) -> Any:
        return self.hass.states.get(entity_id) if entity_id else None

    def physical_mode(self) -> str | None:
        state = self.state(self.entities.get(CONF_CLIMATE))
        return str(state.state) if state else None

    def selected_mode(self) -> str | None:
        mode = self.physical_mode()
        if mode in CONDITIONING:
            return mode
        if mode == FAN:
            return self.previous_mode if self.previous_mode in CONDITIONING else None
        if mode == HVACMode.OFF and self.solar_powered_off:
            return self.previous_mode
        return None

    def setting(self, key: str, room: str | None = None, default: float = 0.0) -> float:
        if room:
            return float(self.settings.setdefault("rooms", {}).setdefault(room, {}).get(key, default))
        return float(self.settings.get(key, default))

    def room_target(self, key: str, mode: str) -> float:
        field = "target_heat" if mode == HVACMode.HEAT else "target_cool"
        default = 23.5 if mode == HVACMode.HEAT else 22.0
        return self.setting(field, key, default)

    def gain(self, room: dict[str, Any]) -> float:
        entity = room.get(CONF_ROOM_GAIN)
        if entity:
            value = numeric(self.state(entity))
            if value is not None:
                return max(0.1, min(value, 2.0))
        return self.setting("gain", room[CONF_ROOM_KEY], 1.0)

    def enabled(self, room: dict[str, Any]) -> bool:
        entity = room.get(CONF_ROOM_ENABLED)
        if not entity:
            return True
        state = self.state(entity)
        return bool(state and state.state == "on")

    def occupied(self, room: dict[str, Any]) -> bool:
        players = room.get(CONF_ROOM_PRESENCE, [])
        if not players:
            return True
        return any((state := self.state(entity)) is not None and state.state in ACTIVE_MEDIA_STATES
                   for entity in players)

    def door_open(self) -> bool:
        return any((state := self.state(entity)) is not None and state.state == "on"
                   for entity in self.entities.get(CONF_DOORS, []))

    def external_solar_owner(self) -> bool:
        entity = self.entities.get(CONF_SOLAR_ACTIVE)
        state = self.state(entity)
        return bool(state and state.state == "on")

    async def _control(self) -> None:
        await self._process_heating_adjustments()
        if not self.smart_control_enabled():
            self.zone_status = self._calculate_zones(self.selected_mode())
            return
        self._observe_mode(self.physical_mode())
        mode = self.selected_mode()
        external_owner = self.external_solar_owner()
        self.solar_offset = 0.0
        solar_owns_mode = False

        self.zone_status = self._calculate_zones(mode)
        await self._control_vents(self.zone_status)
        if external_owner:
            self.target_stable_since = None
        else:
            if self.physical_mode() in CONDITIONING and mode in CONDITIONING:
                await self._set_central_target(self.zone_status, mode)
            pause_required = self._conditioning_pause_required(self.zone_status, mode)
            if pause_required:
                if self.physical_mode() in CONDITIONING:
                    await self._set_mode(FAN, preserve=mode)
                solar_owns_mode = True
            elif mode == HVACMode.COOL:
                solar_owns_mode = await self._solar_control()
            if not solar_owns_mode:
                await self._control_hvac_mode(self.zone_status, mode)
        await self._hourly_gain_tune(mode)

    def smart_control_enabled(self) -> bool:
        """Check the optional master-enable helper."""
        entity = self.entities.get(CONF_SMART_CONTROL)
        if not entity:
            return True
        state = self.state(entity)
        return bool(state and state.state == "on")

    async def _process_heating_adjustments(self) -> None:
        """Apply momentary half-degree room heating target nudges."""
        for key, direction in ((CONF_HEAT_ADJUST_UP, 1), (CONF_HEAT_ADJUST_DOWN, -1)):
            entity = self.entities.get(key)
            if not entity:
                continue
            state = self.state(entity)
            is_on = bool(state and state.state == "on")
            if is_on and not self._adjust_states.get(key, False):
                step = self.setting("heating_adjust_step", default=0.5)
                for room in self.rooms:
                    room_key = room[CONF_ROOM_KEY]
                    old = self.room_target(room_key, HVACMode.HEAT)
                    self.settings["rooms"][room_key]["target_heat"] = max(16.0, min(30.0, old + direction * step))
                await self.hass.services.async_call(
                    "input_boolean", "turn_off", {"entity_id": entity}, blocking=False
                )
                await self._save()
            self._adjust_states[key] = is_on
    def _observe_mode(self, mode: str | None) -> None:
        """Treat physical heat/cool changes as explicit user choices."""
        if mode in CONDITIONING:
            if self._pending_mode == mode:
                self._pending_mode = None
                self.previous_mode = mode
                self.fan_owned = False
            elif mode != self._last_mode:
                self.previous_mode = mode
                self.fan_owned = False
                self.solar_powered_off = False
        elif mode == FAN and mode != self._last_mode:
            if self._pending_mode == FAN:
                self.fan_owned = True
                self._pending_mode = None
            else:
                self.fan_owned = False
        self._last_mode = mode

    def _calculate_zones(self, mode: str | None) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        tolerance = self.setting("temperature_tolerance", default=0.6)
        step = self.setting("vent_step", default=10.0)
        for room in self.rooms:
            key = room[CONF_ROOM_KEY]
            temp = numeric(self.state(room[CONF_ROOM_TEMPERATURE]))
            enabled, occupied = self.enabled(room), self.occupied(room)
            target = self.room_target(key, mode) if mode in CONDITIONING else None
            error = demand = desired = 0.0
            reached = False
            if temp is not None and target is not None and enabled and occupied:
                error = temp - target if mode == HVACMode.COOL else target - temp
                if error > tolerance:
                    differential = self.setting(
                        "cold_differential" if mode == HVACMode.COOL else "hot_differential",
                        default=1.0,
                    )
                    demand = error
                    desired = min(100.0, max(
                        step,
                        (error - tolerance) * self.gain(room) * 100.0
                        + (step if error > differential else 0.0),
                    ))
                else:
                    reached = abs(error) <= tolerance
            result[key] = {
                "name": room[CONF_ROOM_NAME], "temperature": temp, "target": target,
                "error": error if temp is not None and target is not None else None,
                "enabled": enabled, "occupied": occupied, "demand": demand,
                "desired_position": desired, "reached": reached,
                "cover": room[CONF_ROOM_COVER], "mode": mode,
            }
        return result

    async def _control_vents(self, zones: dict[str, dict[str, Any]]) -> None:
        step = self.setting("vent_step", default=10.0)
        for zone in zones.values():
            if zone["temperature"] is None:
                continue
            desired = zone["desired_position"] if zone["enabled"] and zone["occupied"] else 0.0
            state = self.state(zone["cover"])
            if state is None:
                continue
            current = state.attributes.get("current_position")
            if current is None:
                service = "open_cover" if desired > 0 else "close_cover"
                await self.hass.services.async_call("cover", service,
                                                    {"entity_id": zone["cover"]}, blocking=False)
                continue
            current = float(current)
            if abs(desired - current) < 1:
                continue
            position = max(0, min(100, round(current + max(-step, min(step, desired-current)))))
            await self.hass.services.async_call(
                "cover", "set_cover_position",
                {"entity_id": zone["cover"], "position": position}, blocking=False
            )

    async def _set_central_target(self, zones: dict[str, dict[str, Any]], mode: str) -> None:
        eligible = [z for z in zones.values() if z["enabled"] and z["occupied"]
                    and z["temperature"] is not None and z["target"] is not None]
        if not eligible:
            return
        requesting = [z for z in eligible if z["demand"] > 0]
        chosen = max(requesting or eligible,
                     key=lambda z: z["demand"] if requesting else abs(z["error"] or 0))
        target = float(chosen["target"])
        if mode == HVACMode.COOL and self.settings.get("solar_enabled"):
            target += self.solar_offset
        state = self.state(self.entities.get(CONF_CLIMATE))
        if state is None:
            return
        try:
            current = float(state.attributes.get("temperature"))
        except (TypeError, ValueError):
            current = None
        if current is None or abs(current - target) >= 0.1:
            await self.hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": self.entities[CONF_CLIMATE], "temperature": round(target, 1)},
                blocking=False,
            )

    async def _control_hvac_mode(self, zones: dict[str, dict[str, Any]], mode: str | None) -> None:
        """Use fan-only temporarily; never select or switch heat/cool."""
        if mode not in CONDITIONING or self.external_solar_owner():
            self.target_stable_since = None
            return
        if self._conditioning_pause_required(zones, mode):
            if self.physical_mode() in CONDITIONING:
                await self._set_mode(FAN, preserve=mode)
            return
        if self.physical_mode() == FAN and self.fan_owned and self.previous_mode in CONDITIONING:
            await self._set_mode(self.previous_mode)

    def _conditioning_pause_required(self, zones: dict[str, dict[str, Any]], mode: str | None) -> bool:
        """Prioritize open doors and a stable room target over solar cooling."""
        if mode not in CONDITIONING:
            self.target_stable_since = None
            return False
        now = dt_util.utcnow().timestamp()
        active = [z for z in zones.values() if z["enabled"] and z["occupied"]
                  and z["temperature"] is not None]
        all_reached = bool(active) and all(z["reached"] for z in active)
        if all_reached:
            self.target_stable_since = self.target_stable_since or now
        else:
            self.target_stable_since = None
        held = (all_reached and self.target_stable_since is not None
                and now - self.target_stable_since >= self.setting("reached_delay", default=5))
        return not active or self.door_open() or held

    async def _solar_control(self) -> bool:
        """Run solar protection only if the user has already selected cool."""
        if not self.settings.get("solar_enabled") or self.external_solar_owner():
            return False
        if not all(self.entities.get(key) for key in (
            CONF_SOLAR_GENERATION, CONF_SOLAR_LOAD, CONF_GRID_POWER
        )):
            return False
        now = dt_util.utcnow().timestamp()
        if now - self.last_solar_tick >= 300:
            self.last_solar_tick = now
            generation = numeric(self.state(self.entities.get(CONF_SOLAR_GENERATION)))
            load = numeric(self.state(self.entities.get(CONF_SOLAR_LOAD)))
            if generation is None or load is None:
                return False
            if generation < self.setting("solar_low_generation", default=100):
                self.low_generation_ticks += 1
                if self.low_generation_ticks >= 3 and not self.solar_paused:
                    self.solar_paused = True
                    power = self.entities.get(CONF_POWER_SWITCH)
                    if power:
                        await self.hass.services.async_call(
                            "switch", "turn_off", {"entity_id": power}, blocking=False
                        )
                    else:
                        await self.hass.services.async_call(
                            "climate", "set_hvac_mode",
                            {"entity_id": self.entities[CONF_CLIMATE], "hvac_mode": HVACMode.OFF},
                            blocking=False,
                        )
                        self.solar_powered_off = True
                    await self._save()
                return True

            self.low_generation_ticks = 0
            if self.solar_paused and generation >= self.setting("solar_resume_generation", default=500):
                self.solar_paused = False
                power = self.entities.get(CONF_POWER_SWITCH)
                if power:
                    await self.hass.services.async_call(
                        "switch", "turn_on", {"entity_id": power}, blocking=False
                    )
                elif self.solar_powered_off and self.previous_mode == HVACMode.COOL:
                    await self.hass.services.async_call(
                        "climate", "set_hvac_mode",
                        {"entity_id": self.entities[CONF_CLIMATE], "hvac_mode": HVACMode.COOL},
                        blocking=False,
                    )
                    self.solar_powered_off = False
                await self._save()

        if self.solar_paused:
            return True
        grid = numeric(self.state(self.entities.get(CONF_GRID_POWER)))
        if grid is None:
            return False
        if grid > self.setting("solar_grid_limit", default=50):
            if self.physical_mode() == HVACMode.COOL:
                await self._set_mode(FAN, preserve=HVACMode.COOL)
            self.solar_offset = 1.5
            return True

        average = numeric(self.state(self.entities.get(CONF_HOUSE_TEMPERATURE)))
        if average is not None:
            if average < self.setting("solar_fan_temperature", default=24.3):
                if self.physical_mode() == HVACMode.COOL:
                    await self._set_mode(FAN, preserve=HVACMode.COOL)
            elif (average >= self.setting("solar_cool_temperature", default=26.0)
                  and self.physical_mode() == FAN and self.fan_owned
                  and self.previous_mode == HVACMode.COOL):
                await self._set_mode(HVACMode.COOL)

        # Negative grid flow means export; export is available AC headroom.
        export = max(0.0, -grid)
        generation = numeric(self.state(self.entities.get(CONF_SOLAR_GENERATION)))
        load = numeric(self.state(self.entities.get(CONF_SOLAR_LOAD)))
        if generation is not None and load is not None:
            export = min(export, max(0.0, generation - load))
        reference = max(1.0, self.setting("solar_headroom_reference", default=500))
        self.solar_offset = max(-1.5, min(1.5, (reference - export) / reference * 1.5))
        return True

    async def _hourly_gain_tune(self, mode: str | None) -> None:
        """Use the existing script or reproduce its thresholds for internal gains."""
        if mode not in CONDITIONING:
            return
        now = dt_util.utcnow().timestamp()
        if now - self.last_tuned < 3600:
            return
        self.last_tuned = now
        climate = self.state(self.entities.get(CONF_CLIMATE))
        try:
            unit_target = float(climate.attributes.get("temperature"))
        except (AttributeError, TypeError, ValueError):
            unit_target = None
        for room in self.rooms:
            gain_entity = room.get(CONF_ROOM_GAIN)
            if gain_entity:
                try:
                    await self.hass.services.async_call(
                        "script", "ac_auto_tune_gain",
                        {"room_temp_sensor": room[CONF_ROOM_TEMPERATURE],
                         "gain_input_number": gain_entity},
                        blocking=True,
                    )
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Gain tuning failed for %s", room[CONF_ROOM_NAME])
                continue
            temp = numeric(self.state(room[CONF_ROOM_TEMPERATURE]))
            if temp is None or unit_target is None:
                continue
            diff = abs(temp - unit_target)
            key = room[CONF_ROOM_KEY]
            gain = self.gain(room)
            if diff > 1.5:
                gain = min(gain + 0.1, 2.0)
            elif diff < 0.3:
                gain = max(gain - 0.05, 0.5)
            self.settings["rooms"][key]["gain"] = gain
        await self._save()
        await self._write_gain_snapshot()

    async def _restore_gain_snapshot(self) -> None:
        """Restore configured gain helpers from the optional JSON snapshot."""
        entity = self.entities.get(CONF_GAIN_SNAPSHOT)
        state = self.state(entity)
        if not state or not state.state:
            return
        try:
            snapshot = json.loads(state.state)
        except (TypeError, ValueError):
            _LOGGER.warning("Ignoring invalid AC gain snapshot in %s", entity)
            return
        if not isinstance(snapshot, dict):
            _LOGGER.warning("Ignoring non-object AC gain snapshot in %s", entity)
            return
        for room in self.rooms:
            gain_entity = room.get(CONF_ROOM_GAIN)
            value = snapshot.get(room[CONF_ROOM_KEY])
            try:
                gain = max(0.5, min(2.0, float(value)))
            except (TypeError, ValueError):
                continue
            if gain_entity:
                try:
                    await self.hass.services.async_call(
                        "input_number", "set_value",
                        {"entity_id": gain_entity, "value": gain}, blocking=True,
                    )
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Could not restore gain for %s", room[CONF_ROOM_NAME])
                    continue
            self.settings["rooms"][room[CONF_ROOM_KEY]]["gain"] = gain
        await self._save()

    async def _write_gain_snapshot(self) -> None:
        """Keep the optional JSON snapshot synchronized with current gains."""
        entity = self.entities.get(CONF_GAIN_SNAPSHOT)
        if not entity:
            return
        snapshot: dict[str, float] = {}
        for room in self.rooms:
            key = room[CONF_ROOM_KEY]
            snapshot[key] = round(self.gain(room), 3)
        await self.hass.services.async_call(
            "input_text", "set_value",
            {"entity_id": entity, "value": json.dumps(snapshot, separators=(",", ":"))},
            blocking=False,
        )

    async def _set_mode(self, mode: str, *, preserve: str | None = None) -> None:
        """Set fan temporarily or restore the user's earlier mode."""
        physical = self.physical_mode()
        if mode == FAN:
            if physical in CONDITIONING:
                self.previous_mode = preserve or physical
                self._pending_mode = FAN
                self.fan_owned = True
            elif physical != FAN:
                return
        elif mode in CONDITIONING:
            if not (physical == FAN and self.fan_owned and self.previous_mode == mode):
                return
            self._pending_mode = mode
            self.fan_owned = False
        else:
            return
        await self._save()
        await self.hass.services.async_call(
            "climate", "set_hvac_mode",
            {"entity_id": self.entities[CONF_CLIMATE], "hvac_mode": mode},
            blocking=False,
        )

    async def async_set_setting(self, key: str, value: float, room: str | None = None) -> None:
        """Update and persist one setting."""
        if room:
            self.settings.setdefault("rooms", {}).setdefault(room, {})[key] = float(value)
        else:
            self.settings[key] = float(value)
        await self._save()
        await self.async_request_refresh()

    async def async_set_solar_enabled(self, enabled: bool) -> None:
        self.settings["solar_enabled"] = enabled
        if not enabled:
            self.solar_paused = False
            self.low_generation_ticks = 0
        await self._save()
        await self.async_request_refresh()

    async def _save(self) -> None:
        await self._store.async_save({
            "settings": self.settings,
            "previous_mode": self.previous_mode,
            "fan_owned": self.fan_owned,
            "last_tuned": self.last_tuned,
            "solar_paused": self.solar_paused,
            "solar_powered_off": self.solar_powered_off,
            "low_generation_ticks": self.low_generation_ticks,
        })
