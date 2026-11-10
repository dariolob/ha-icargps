# iCar GPS (icargps.net) for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41A4DF.svg)](https://github.com/dariolob/ha-icargps)

Custom Home Assistant integration for **ICAR GPS pet trackers** (tested with an
**ICAR IK122T Pro**, model 504) using the **icargps.net** web platform — the same
backend the "ICAR" mobile app talks to.

> ⚠️ **This is an unofficial integration.** The icargps.net API is undocumented
> and was reverse-engineered from the web interface and the app traffic. It may
> stop working at any time if the platform changes. Telemetry traffic goes over
> **plain HTTP** (the web platform does not offer HTTPS); commands are sent to
> the app API over HTTPS.

## What you get

| Entity | Type | Notes |
| --- | --- | --- |
| `<collar>` | `device_tracker` | GPS position on the map, with speed, course, stop status, offline flag |
| `<collar> Battery` | `sensor` | Battery % (from the device `dataContext` field) |
| `<collar> Speed` | `sensor` | km/h |
| `<collar> Status` | `sensor` | `Stop` / `Moving` + stop duration |
| `<collar> Last Alarm` | `sensor` | Most recent alarm (geofence exit/enter, vibration/bark) |
| `<collar> Alarms` | `event` | One event per new alarm: `geofence_exit`, `geofence_enter`, `alarm` |
| `<collar> Find` | `button` | Long "find" tune + light for ~1 minute (`SLXKDM`) |
| `<collar> Sound` | `button` | Short training rhythm — the "punitive" sound of the app (`SLXKLS`) |
| `<collar> Vibration` | `button` | One vibration to train the dog (`SLXKBSD`) |
| `<collar> Night Light` | `button` | Flashing light to find the dog in the dark (`SLXKZXZD`) |
| `<collar> Shock` | `button` | **Disabled by default.** Vibration + e-shock at the level set in the options (`SLXKZDXG`) |

All five buttons send the same `CommandType` the ICAR app sends for the same
button (mapped by pressing each app button while reading the platform command
history on 2026-11-10). Physical execution was verified live for the sound
command (`SLXKLS`) with the exact request body used by this integration.

There is also a generic service `icargps.send_command` for any other platform
command you discover.

The collar sleeps when the dog is not moving (G-sensor wake), so while it is
asleep commands are queued and executed when it wakes up and reconnects.

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/dariolob/ha-icargps` with category **Integration**
3. Search "iCar GPS" and install it
4. **Restart Home Assistant** (a full restart — reloading the integration is
   not enough to pick up new integration code)

### Manual

Copy the `custom_components/icargps` folder into `/config/custom_components/`
on your Home Assistant instance, then restart Home Assistant.

## Configuration

1. **Settings → Devices & Services → Add Integration** → **iCar GPS**
2. Enter:
   - **SN / ID No.** — the serial number you use in the ICAR app (not the
     device ID)
   - **Password** — your device password
   - **Timezone offset** — e.g. `1:00` for UTC+1, `2:00` for UTC+2
   - **Polling interval** — seconds (default 120)

Options (Configure on the integration card): polling interval, timezone, and
the **shock level** (1–9) used by the shock button.

## Automations

```yaml
# Notify when the dog leaves the "Casa" geofence
automation:
  - alias: "Cane uscito di casa"
    trigger:
      - platform: state
        entity_id: event.collar_alarms
        attribute: event_type
        to: "geofence_exit"
    action:
      - service: notify.mobile_app
        data:
          message: "Il cane è uscito dal geofence!"
```

```yaml
# Low battery warning
automation:
  - alias: "Collare batteria bassa"
    trigger:
      platform: numeric_state
      entity_id: sensor.collar_battery
      below: 20
    action:
      - service: notify.mobile_app
        data:
          message: "Batteria del collare sotto il 20%"
```

```yaml
# React to a command result (event fired after every button)
automation:
  - alias: "Comando collare eseguito"
    trigger:
      platform: event
      event_type: icargps_command_result
    action:
      - service: notify.mobile_app
        data:
          message: >
            Comando {{ trigger.event.data.command }}:
            {{ trigger.event.data.message }}
```

## Command map (IK122T Pro, model 504)

Mapped by pressing every button of the ICAR app while reading the platform
command history (2026-11-10):

| App button | CommandType | Parameter |
| --- | --- | --- |
| Sound to find dog | `SLXKDM` | — |
| Sound(rhythm) to train dog | `SLXKLS` | — |
| Vibration training | `SLXKBSD` | — |
| Night light to find dog | `SLXKZXZD` | — |
| E-Shock to train dog | `SLXKZDXG` | level 1–9 |

## Troubleshooting commands

- **A button "works" (no error) but the collar does nothing?** The platform
  queues commands and reports `Success!` ACKs even for commands it never
  delivers. The app channel (`openapiv3.asmx` → `SendCommandByAPP`) is the
  only one that actually reaches the IK122T Pro, and its request must carry
  **exactly** the six fields the app sends: `Key, SN, DeviceID, CommandType,
  Model, Paramter`. Any extra field makes the platform accept the command and
  ACK it while silently never delivering it. This integration sends exactly
  those six fields — but make sure you are on the version you think you are
  on (HACS → iCar GPS → check the installed version), and remember that a
  **full Home Assistant restart** is required after an update.
- The collar sleeps when the dog is stationary (G-sensor wake). While it is
  asleep, commands wait in the queue until it wakes up and reconnects.
- The `Success!` ACK shown in the `icargps_command_result` event is the
  platform's claim, not proof that the collar beeped/vibrated.

## Known limitations

- **Shock button is disabled by default.** The command and level encoding are
  now verified (the app slider sends the same `SLXKZDXG` command), but an
  e-shock on a pet should be enabled deliberately: start at level 1 and
  supervise your dog.
- Alarm type `3` (vibration / bark indicator) is mapped generically to
  `alarm`; other unmapped types become `unknown`.
- Telemetry (position/alarms) is read from the icargps.net web platform over
  HTTP; credentials travel in cleartext (same as the vendor's own web
  interface and app).
- Commands are dispatched through the app API (`openapiv3.asmx`, the same
  channel the mobile app uses). Verified live: a `SLXKLS` sound command sent
  with the exact app request body was executed by the collar 3/3 on
  2026-11-10. The web `SendCommand`/`SendCommandByPhone` endpoints accept
  commands for this model but never deliver them, so they are not used.
- Geofences are configured in the vendor app; this integration only reads
  the resulting enter/exit events.

## License

MIT
