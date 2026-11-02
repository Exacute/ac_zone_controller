"""Constants for AC Zone Controller."""
from __future__ import annotations
from typing import Final

DOMAIN: Final = "ac_zone_controller"
PLATFORMS: Final = ("climate", "number", "sensor", "switch")

CONF_NAME: Final = "name"
CONF_CLIMATE: Final = "climate"
CONF_POWER_SWITCH: Final = "power_switch"
CONF_HOUSE_TEMPERATURE: Final = "house_temperature"
CONF_DOORS: Final = "doors"
CONF_SOLAR_GENERATION: Final = "solar_generation"
CONF_SOLAR_LOAD: Final = "solar_load"
CONF_GRID_POWER: Final = "grid_power"
CONF_BATTERY_SOC: Final = "battery_soc"
CONF_SOLAR_ACTIVE: Final = "solar_active"
CONF_GAIN_SNAPSHOT: Final = "gain_snapshot"
CONF_SMART_CONTROL: Final = "smart_control"
CONF_HEAT_ADJUST_UP: Final = "heat_adjust_up"
CONF_HEAT_ADJUST_DOWN: Final = "heat_adjust_down"
CONF_ROOMS: Final = "rooms"
CONF_ROOM_KEY: Final = "key"
CONF_ROOM_NAME: Final = "name"
CONF_ROOM_TEMPERATURE: Final = "temperature_sensor"
CONF_ROOM_COVER: Final = "cover"
CONF_ROOM_ENABLED: Final = "enabled_entity"
CONF_ROOM_PRESENCE: Final = "presence_entities"
CONF_ROOM_GAIN: Final = "gain_entity"
CONF_SETTINGS: Final = "settings"
CONF_GLOBAL: Final = "global"
CONF_NOTIFICATION_INTERVAL: Final = "notification_interval"
CONF_NOTIFICATION_TARGETS: Final = "notification_targets"

DEFAULT_NOTIFICATION_INTERVAL: Final = 60

DEFAULTS: Final = {
    "temperature_tolerance": 0.6,
    "reached_delay": 5.0,
    "vent_step": 10.0,
    "hot_differential": 1.0,
    "cold_differential": 1.0,
    "heating_adjust_step": 0.5,
    "solar_fan_temperature": 24.3,
    "solar_cool_temperature": 26.0,
    "solar_low_generation": 100.0,
    "solar_resume_generation": 500.0,
    "solar_grid_limit": 50.0,
    "solar_headroom_reference": 500.0,
}

ROOM_DEFAULTS: Final = {
    "main_living": (23.5, 22.0, 0.62),
    "formal_lounge": (23.5, 22.0, 0.84),
    "home_theatre": (23.5, 22.0, 0.96),
    "master_bedroom": (23.5, 22.0, 0.90),
    "zoey_bedroom": (23.5, 22.0, 1.51),
    "harrison_bedroom": (23.5, 22.0, 1.35),
}
