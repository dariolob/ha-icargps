# iCar GPS (icargps.net) for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41A4DF.svg)](https://github.com/dariolob/ha-icargps)

Custom Home Assistant integration for **ICAR GPS pet trackers** (tested with an
**ICAR IK122T Pro**, model 504) using the **icargps.net** web platform — the same
backend the "ICAR" mobile app talks to.

> ⚠️ **This is an unofficial integration.** The icargps.net API is undocumented
> and was reverse-engineered from the web interface and the app traffic. It may
> stop working at any time if the platform changes. All traffic goes over
> **plain HTTP** — the platform does not offer HTTPS for these endpoints.

## What you get

| Entity | Type | Notes |
| --- | --- | --- |
| `<collar>` | `device_tracker` | GPS position on the map, with speed, course, stop status, offline flag |
| `<collar> Battery` | `sensor` | Battery % (from the device `dataContext` field) |
| `<collar> Speed` | `sensor` | km/h |
| `<collar> Status` | `sensor` | `Stop` / `Moving` + stop duration |
| `<collar> Last Alarm` | `sensor` | Most recent alarm (geofence exit/enter, vibration/bark) |
| `<collar> Alarms` | `event` | One event per new alarm: `geofence_exit`, `geofence_enter`, `alarm` |
| `<collar> Find` | `button` | Buzzer + flashing light for ~1 minute (`SLXKDM`) |
| `<collar> Shock` | `button` | **Disabled by default, experimental.** Vibration + e-shock (`SLXKZDXG`) |

There is also a generic service `icargps.send_command` for any other platform
command you discover.

The collar sleeps when the dog is not moving (G-sensor wake), so while it is
asleep commands are queued ("saved") and executed when it wakes up and
reconnects.

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/dariolob/ha-icargps` with category **Integration**
3. Search "iCar GPS" and install it
4. Restart Home Assistant

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
# React to a command result (event fired after Find/Shock)
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

## Known limitations

- **Shock button is experimental.** The command (`SLXKZDXG`) and the numeric
  level were read from the platform command history, but the level encoding
  has not been verified end-to-end. The entity is disabled by default; enable
  it only if you need it, start at level 1, and supervise your dog.
- Alarm type `3` (vibration / bark indicator) is mapped generically to
  `alarm`; other unmapped types become `unknown`.
- The platform is HTTP-only; credentials travel in cleartext to icargps.net
  (same as the vendor's own web interface and app).
- Commands are dispatched through the platform's `SendCommandByPhone` queue.
  The plain `SendCommand` endpoint answers "saved" (code 4) for this model
  but never delivers anything.
- Geofences are configured in the vendor app; this integration only reads
  the resulting enter/exit events.

## License

MIT
