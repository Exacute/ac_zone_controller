# Changelog

## 0.1.2

- Add an optional 15-minute fan-only cycle before selecting a solar heating or cooling mode.
- Use current indoor and outdoor temperatures to select the mode while enforcing the solar power and door checks.
- Add an outdoor temperature sensor and house heating target under Solar heating and cooling.

## 0.1.1

- Add configurable recurring AC status notifications with selectable notify-device recipients.
- Add a notification interval setting from 5 minutes to 24 hours; reports default to hourly and remain disabled until recipients are selected.
- Improve code comments around notification timing and failure handling.
- Publish matching `v0.1.1` HACS release metadata so Home Assistant can present the update and restart requirement.
