# AC Zone Controller

A Home Assistant custom integration that gives each room an independent thermostat target and coordinates the rooms through one Daikin heat-pump.

## Behavior

- Add rooms in the integration UI and assign a room temperature sensor, vent cover, optional room-enable helper, optional media-player presence sources, and optional gain helper.
- Each room gets a climate entity with an independent target for heating and cooling. The physical Daikin climate entity remains the authority for the user's selected heat or cool mode. The integration never changes directly from heat to cool or cool to heat.
- Doors and stable target conditions may temporarily put the Daikin in fan-only mode. The integration remembers the selected heat/cool mode and restores that same mode when the temporary condition ends.
- Media players count as presence signals. A room is occupied when any configured player is on, playing, paused, or buffering. This is not used as a direct TV-to-vent command.
- Enabled occupied rooms request airflow based on their own temperature error. Covers are moved in configured steps.
- Hourly gain tuning can call the existing `script.ac_auto_tune_gain` with the room sensor and configured `input_number` gain helper.
- If configured, `input_text.ac_gain_snapshot` restores gains on integration startup and is refreshed after the hourly tuning pass.
- The optional solar controller is off by default. It only operates while the physical Daikin is already in cool mode, and it reads (but never writes) `input_boolean.solar_cooling_active`. Disable the JARVIS solar jobs and clear their ownership flag before enabling the integration controller.
- The integration can send a recurring AC status report to selected Home Assistant notify entities. Set the interval and recipients under the integration's **Configure** options; no report is sent until at least one recipient is selected.

## Setup

This repository follows the HACS custom integration layout for [Exacute/ac_zone_controller](https://github.com/Exacute/ac_zone_controller). For local testing, copy `custom_components/ac_zone_controller` into the Home Assistant `custom_components` directory, restart Home Assistant, then add **AC Zone Controller** from Devices & services. The repository includes its HACS icon and manifest links.

## Controls

Global tuning values and per-room targets/gains are exposed as integration number entities. Use the integration options page to add, edit, or remove rooms.

The room climate entities expose target temperature for the Daikin's currently selected heat/cool mode. Change heat versus cool on the physical Daikin climate entity; the room climate entities do not select the global mode.

## Status notifications

Open **Settings → Devices & services → AC Zone Controller → Configure → AC status notifications** to choose a report interval from 5 minutes to 24 hours and one or more notification devices. The report includes the Daikin mode, house average when configured, and each room's temperature, current target, presence, enabled state, and vent position. The first report is sent after one full interval following startup. Leave the recipient list empty to disable reports.

Once the integration report is configured and verified, disable the separate JARVIS hourly report to avoid duplicate messages. The integration does not change JARVIS jobs.

## Solar settings

The integrated solar controller starts disabled to prevent competing commands while JARVIS is active. Its switch can be enabled after the JARVIS monitor and resumer are disabled. It uses the configured PV generation, house load, grid flow, and house-average temperature entities. Positive grid flow is treated as importing; the controller will not request cooling above the configured import limit. Solar headroom is conservatively capped by both grid export and PV generation minus house load. Battery SOC can be selected for setup context but is not yet part of the control rule.

## Current limitations

- Presence is inferred from configured media-player states; use binary occupancy sensors as additional future inputs if they are needed.
- Gain tuning delegates to the existing script so its current thresholds and gain bounds remain authoritative.
- Solar cooling retains the manual heat/cool choice and will not initiate cooling when the Daikin is in heat mode.
- Selected notify entities receive the recurring report through Home Assistant's notification action.

## Releases and updates

Each release increments the version in `custom_components/ac_zone_controller/manifest.json` and publishes a matching GitHub tag and release. HACS can then show the integration update and release notes. Install the update through HACS and restart Home Assistant when prompted; custom integration code is loaded at startup.
