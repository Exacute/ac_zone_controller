"""Config and options flows for AC Zone Controller."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_SOC,
    CONF_CLIMATE,
    CONF_DOORS,
    CONF_GLOBAL,
    CONF_HOUSE_TEMPERATURE,
    CONF_NAME,
    CONF_POWER_SWITCH,
    CONF_ROOM_COVER,
    CONF_ROOM_ENABLED,
    CONF_ROOM_GAIN,
    CONF_ROOM_KEY,
    CONF_ROOM_NAME,
    CONF_ROOM_PRESENCE,
    CONF_ROOM_TEMPERATURE,
    CONF_ROOMS,
    CONF_SETTINGS,
    CONF_SOLAR_ACTIVE,
    CONF_SOLAR_GENERATION,
    CONF_SOLAR_LOAD,
    CONF_GRID_POWER,
    CONF_GAIN_SNAPSHOT,
    CONF_SMART_CONTROL,
    CONF_HEAT_ADJUST_UP,
    CONF_HEAT_ADJUST_DOWN,
    DEFAULTS,
    DOMAIN,
)


def _entity(domain: str | list[str], *, multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domain, multiple=multiple)
    )


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _room_schema(room: dict[str, Any] | None = None) -> vol.Schema:
    room = room or {}
    schema: dict[Any, Any] = {
        vol.Required(CONF_ROOM_NAME, default=room.get(CONF_ROOM_NAME, "")): str,
        vol.Required(
            CONF_ROOM_TEMPERATURE,
            default=room.get(CONF_ROOM_TEMPERATURE, ""),
        ): _entity("sensor"),
        vol.Required(CONF_ROOM_COVER, default=room.get(CONF_ROOM_COVER, "")): _entity(
            "cover"
        ),
        vol.Optional(
            CONF_ROOM_ENABLED,
            default=room.get(CONF_ROOM_ENABLED),
        ): _entity("input_boolean"),
        vol.Optional(
            CONF_ROOM_PRESENCE,
            default=room.get(CONF_ROOM_PRESENCE, []),
        ): _entity("media_player", multiple=True),
        vol.Optional(
            CONF_ROOM_GAIN,
            default=room.get(CONF_ROOM_GAIN),
        ): _entity("input_number"),
    }
    return vol.Schema(schema)


def _clean_room(data: dict[str, Any]) -> dict[str, Any]:
    name = data[CONF_ROOM_NAME].strip()
    room = {
        CONF_ROOM_KEY: _slug(name),
        CONF_ROOM_NAME: name,
        CONF_ROOM_TEMPERATURE: data[CONF_ROOM_TEMPERATURE],
        CONF_ROOM_COVER: data[CONF_ROOM_COVER],
        CONF_ROOM_PRESENCE: data.get(CONF_ROOM_PRESENCE, []),
    }
    for key in (CONF_ROOM_ENABLED, CONF_ROOM_GAIN):
        if data.get(key):
            room[key] = data[key]
    return room


class ACZoneConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up the integration."""

    VERSION = 1

    def __init__(self) -> None:
        self._global: dict[str, Any] = {}
        self._rooms: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Collect shared entities."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            self._global = {
                key: value
                for key, value in user_input.items()
                if value not in (None, "", [])
            }
            return await self.async_step_room()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="AC Zone Controller"): str,
                vol.Required(CONF_CLIMATE): _entity("climate"),
                vol.Optional(CONF_POWER_SWITCH): _entity("switch"),
                vol.Optional(CONF_HOUSE_TEMPERATURE): _entity("sensor"),
                vol.Optional(CONF_DOORS): _entity("binary_sensor", multiple=True),
                vol.Optional(CONF_SOLAR_GENERATION): _entity("sensor"),
                vol.Optional(CONF_SOLAR_LOAD): _entity("sensor"),
                vol.Optional(CONF_GRID_POWER): _entity("sensor"),
                vol.Optional(CONF_BATTERY_SOC): _entity("sensor"),
                vol.Optional(CONF_SOLAR_ACTIVE): _entity("input_boolean"),
                vol.Optional(CONF_GAIN_SNAPSHOT): _entity("input_text"),
                vol.Optional(CONF_SMART_CONTROL): _entity("input_boolean"),
                vol.Optional(CONF_HEAT_ADJUST_UP): _entity("input_boolean"),
                vol.Optional(CONF_HEAT_ADJUST_DOWN): _entity("input_boolean"),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Add a room."""
        errors: dict[str, str] = {}
        if user_input is not None:
            room = _clean_room(user_input)
            if not room[CONF_ROOM_KEY]:
                errors["base"] = "invalid_room_name"
            elif any(existing[CONF_ROOM_KEY] == room[CONF_ROOM_KEY] for existing in self._rooms):
                errors["base"] = "duplicate_room"
            else:
                self._rooms.append(room)
                return await self.async_step_more_rooms()

        return self.async_show_form(
            step_id="room",
            data_schema=_room_schema(),
            errors=errors,
        )

    async def async_step_more_rooms(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Choose whether to add another room."""
        return self.async_show_menu(
            step_id="more_rooms",
            menu_options=["room", "finish"],
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Create the config entry."""
        if not self._rooms:
            return await self.async_step_room()

        title = self._global.pop(CONF_NAME, "AC Zone Controller")
        return self.async_create_entry(
            title=title,
            data=self._global,
            options={
                CONF_ROOMS: self._rooms,
                CONF_SETTINGS: dict(DEFAULTS),
                CONF_GLOBAL: {},
            },
        )
    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "ACZoneOptionsFlow":
        """Get the options flow."""
        return ACZoneOptionsFlow()

class ACZoneOptionsFlow(config_entries.OptionsFlowWithReload):
    """Add, edit, or remove configured rooms."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Show options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_room", "edit_room", "remove_room"],
        )

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Add a room after initial setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            room = _clean_room(user_input)
            rooms = list(self.config_entry.options.get(CONF_ROOMS, []))
            if not room[CONF_ROOM_KEY]:
                errors["base"] = "invalid_room_name"
            elif any(existing[CONF_ROOM_KEY] == room[CONF_ROOM_KEY] for existing in rooms):
                errors["base"] = "duplicate_room"
            else:
                rooms.append(room)
                return self.async_create_entry(
                    title="",
                    data={**self.config_entry.options, CONF_ROOMS: rooms},
                )
        return self.async_show_form(
            step_id="add_room",
            data_schema=_room_schema(),
            errors=errors,
        )

    async def async_step_edit_room(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Select a room to edit."""
        rooms = list(self.config_entry.options.get(CONF_ROOMS, []))
        if not rooms:
            return self.async_abort(reason="no_rooms")
        if user_input is not None:
            self._edit_key = user_input[CONF_ROOM_KEY]
            return await self.async_step_edit_details()
        return self.async_show_form(
            step_id="edit_room",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ROOM_KEY): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "value": room[CONF_ROOM_KEY],
                                    "label": room[CONF_ROOM_NAME],
                                }
                                for room in rooms
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_edit_details(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Edit selected room details."""
        rooms = list(self.config_entry.options.get(CONF_ROOMS, []))
        current = next(room for room in rooms if room[CONF_ROOM_KEY] == self._edit_key)
        if user_input is not None:
            updated = _clean_room(user_input)
            if updated[CONF_ROOM_KEY] != self._edit_key and any(
                room[CONF_ROOM_KEY] == updated[CONF_ROOM_KEY] for room in rooms
            ):
                return self.async_show_form(
                    step_id="edit_details",
                    data_schema=_room_schema(current),
                    errors={"base": "duplicate_room"},
                )
            rooms[rooms.index(current)] = updated
            return self.async_create_entry(
                title="",
                data={**self.config_entry.options, CONF_ROOMS: rooms},
            )
        return self.async_show_form(
            step_id="edit_details",
            data_schema=_room_schema(current),
        )

    async def async_step_remove_room(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Remove a configured room."""
        rooms = list(self.config_entry.options.get(CONF_ROOMS, []))
        if not rooms:
            return self.async_abort(reason="no_rooms")
        if user_input is not None:
            remaining = [
                room
                for room in rooms
                if room[CONF_ROOM_KEY] != user_input[CONF_ROOM_KEY]
            ]
            return self.async_create_entry(
                title="",
                data={**self.config_entry.options, CONF_ROOMS: remaining},
            )
        return self.async_show_form(
            step_id="remove_room",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ROOM_KEY): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "value": room[CONF_ROOM_KEY],
                                    "label": room[CONF_ROOM_NAME],
                                }
                                for room in rooms
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )
