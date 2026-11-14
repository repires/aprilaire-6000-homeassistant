# AprilAire 6003 (6000-Series Zone Control) — Complete Protocol & Hardware Reference

Last updated: 2026-11-13  
Target Device: `192.0.2.45:7000` (`MAC: B4:82:55:XX:XX:XX`, Home Assistant Config Entry: `<APRILAIRE_CONFIG_ENTRY_ID>`)

---

## 1. Hardware & Wiring Architecture (AprilAire 6000 Series)

Per `Aprilaire-6000-Zone-Control-Manual.pdf` (Pages 4–14, 16–26) and live probe data from `192.0.2.45:7000`:

```
                               ┌─────────────────────────────────────────────────┐
                               │          AprilAire 6000 Series Hub              │
                               │         (Mounted near Furnace / HVAC)           │
                               ├─────────────────────────────────────────────────┤
  Zone 1 ("Whole Home")        │  ZONE 1 CONTROL (4-wire 1-2-3-4 RS-485 bus)     │
  Upstairs Hallway             │    ◄───► Model 6003 Wi-Fi Touchscreen Control   │
  IP: 192.0.2.45:7000           │          MAC: B4:82:55:XX:XX:XX                 │
  HW Rev B, FW 2.2, GS 4.14    │          Opens Local TCP :7000 + Cloud Client   │
                               │                                                 │
  Zone 2 ("Basement")          │  ZONE 2 CONTROL (4-wire 1-2-3-4 RS-485 bus)     │
  No Wi-Fi / No IP             │    ◄───► Model 6006/6007 6000-Series Sensor     │
  Configured as Zone #2        │          LCD + Up/Down buttons (Room Temp/Hold) │
                               │                                                 │
  Zone Dampers                 │  DAMPER 1 (Whole Home) / DAMPER 2 (Basement)    │
  HVAC Equipment               │  HVAC Terminals (R, C, W, W2, Y, Y2, O/B, G)    │
  IAQ Equipment                │  HUM/AUX: AprilAire 500 Whole-House Humidifier  │
                               │  VENT:    AprilAire HRV Fresh Air Ventilation   │
  Wired Duct / Outdoor Sensors │  DAT/LAT: Model 8057 Discharge Air Temp Sensor  │
                               │  ODT:     Model 8052 Outdoor Temp Sensor        │
                               └─────────────────────────────────────────────────┘
```

---

## 2. Binary Frame Format (TCP Port 7000)

| Byte Offset | Field | Size | Description |
| :--- | :--- | :--- | :--- |
| `0` | `revision` | 1 byte | Protocol revision (`0x01` or `0x02`). Echoed by thermostat in `READ_RESPONSE`. |
| `1` | `sequence` | 1 byte | `0x01..0x7F` (`1..127`) for client requests/responses; `0x80..0xFF` (`128..255`) for unsolicited COS events. |
| `2..3` | `length` | 2 bytes | Big-endian (`uint16`) length of `body` (excludes 4-byte header and 1-byte CRC). |
| `4..4+length-1` | `body` | `length` bytes | Normal frame: `[action, domain, attribute, ...data]`. NACK frame: `[0x06, nack_status_code]`. |
| `4+length` | `crc8` | 1 byte | CRC-8 (`poly=0x31`, `init=0x00`, `xorout=0x00`, `refin=False`, `refout=False`) over `header + body`. |

### Action Codes (`body[0]`)
- `1` (`0x01`): `WRITE`
- `2` (`0x02`): `READ_REQUEST`
- `3` (`0x03`): `READ_RESPONSE`
- `5` (`0x05`): `COS` (Change of State unsolicited push)
- `6` (`0x06`): `NACK` (`body[1]` = NACK status code)

### NACK Status Codes Observed on `192.0.2.45:7000`
| Code | Hex | Name | Meaning & Where Observed on 6003 |
| :--- | :--- | :--- | :--- |
| `6` | `0x06` | `UNKNOWN_DOMAIN` | Functional domain does not exist (`Domains 11, 12, 14, 15`). |
| `7` | `0x07` | `UNKNOWN_ATTRIBUTE` | Attribute not implemented in domain (e.g. `(8, 3)`, `(8, 5)`, `(8, 6)`). |
| `10` | `0x0A` | `UNSUPPORTED_MODEL` | Attribute exists in firmware table but rejected for Model `28` (`6003`): `(8, 10)`, `(9, 6)`, `(9, 7)`. |
| `32` | `0x20` | `ATTRIBUTE_NOT_READABLE` | Write-only attribute: `(1, 8)` Reset, `(2, 2)` Setpoints write-only, `(7, 2)` Sync. |
| `33` | `0x21` | `ATTRIBUTE_NOT_AVAILABLE` | Feature not installed/enabled in installer settings: `(2, 3)` Dehumidification, `(2, 6)` Air Cleaning, `(5, 4)` OTA Outdoor Temp. |
| `34` | `0x22` | `INCORRECT_READ_DATA_LENGTH` | `READ_REQUEST` payload length mismatch: `(3, 3)` Schedule Day when read with 0 bytes (requires 1 byte `day=1..7`), or `(2, 1)`, `(5, 1)`, `(5, 2)`, `(7, 6)`, `(8, 4)`, `(3, 4)` when read with extra parameter bytes. |

---

## 3. Complete Live Attribute Dump (`192.0.2.45:7000`)

Captured in `aprilaire_probe.json` and `aprilaire_probe2.json`:

### Domain 8 — `IDENTIFICATION`
| `(Dom, Attr)` | Name | Raw Data Bytes (`body[3:]`) | Decoded Meaning on User's 6003 |
| :--- | :--- | :--- | :--- |
| `(8, 1)` | Revision & Model | `[66, 2, 2, 2, 28, 4, 14]` | `hw_rev = 66 ('B')`, `fw = 2.2`, `proto_rev = 2`, **`model_number = 28 ('6003')`**, `gainspan_fw = 4.14` |
| `(8, 2)` | MAC & Extended ID (v2) | `[180, 130, 85, 0, 0, 1, 1, 66, 2, 2, 2, 28, 4, 14]` | `MAC = B4:82:55:XX:XX:XX`, `force_connection = 1`, followed by the 7 bytes of `(8, 1)`! (`pyaprilaire` previously truncated bytes `7..13` and misparsed byte `7` (`66`) as `connection_type`!) |
| `(8, 3)` | — | `NACK 0x07` | Unknown attribute |
| `(8, 4)` | Location & Name | `84 51 77 51 66 53 00 00 87 104 111 108 101 32 72 111 109 101 00...` | `location = "T3M3B5"` (bytes `0..7`), **`name = "Whole Home"`** (bytes `8..23`). |
| `(8, 5)` | Name (8800-only) | `NACK 0x07` | Unknown attribute on 6003 (`pyaprilaire` calls `(8, 5)` instead of `(8, 4)`, causing missing name and `ERROR: Received NACK for attribute 7` in HA!). |
| `(8, 10)` | — | `NACK 0x0A` | Unsupported model |

### Domain 1 — `SETUP` (Installer & Zone System Settings)
| `(Dom, Attr)` | Name | Raw Data Bytes (`body[3:]`) | Decoded Meaning on User's 6003 |
| :--- | :--- | :--- | :--- |
| `(1, 1)` | Thermostat Installer Settings | `[1, 0, 1, 0, 0, 0, 0, 0, 0, 1, 4, 5, 1, 1, 0, 0, 0, 0, 5, 2, 2, 4, 0, 0, 0, 0, 1, 1, 0, 2, 1, 61, 81, 1, 12, 0, 1, 0, 0, 0, 0, 13, 13, 0]` (44 bytes) | `temp_scale = 1` (Celsius), `control_setup = 0` (Heat & Cool), `auto_changeover = 1`, `deadband = 1`, `outdoor_sensor_installed = 0` (wired to Hub), `away_available = 1`, `heat_blast_available = 1`, `progressive_recovery = 1`, `program_format = 1` |
| `(1, 2)` | Contractor Info | `67 97 110 ...` (212 bytes) | `"Canyon plumbing"`, Phone `"4032581505"` |
| `(1, 3)` | Air Cleaning Setup | `[1]` | Not installed |
| `(1, 4)` | Humidity Control Setup | `[1, 41, 20, 13, 5, 11, 26]` | Manual Humidifier installed (`500 Whole-House Humidifier`) |
| `(1, 5)` | Fresh Air Setup (Basic) | `[0, 0, 13]` | Fresh Air Ventilation installed |
| `(1, 6)` | Fresh Air Setup (Extended) | `[1, 1, 0, 1, 1, 13, 10, 1, 0, 1, 1, 13, 2, 0, 0]` | Timed `30 Min/Hour` Fresh Air setup with high/low outdoor temp limits |
| `(1, 7)` | Setup Sync / Ack | `[]` (0 bytes) | Returns `[3, 1, 7]` |
| `(1, 8)` | Factory / Setup Reset | `NACK 0x20` | Write-only |
| **`(1, 10)`** | **Zone System Settings (Table 5)** | **`[1, 0, 2, 1, 1, 1, 1, 10, 10, 1, 47]`** (11 bytes) | **6000-Series Specific**: Byte 2 = **`2` (`Number of Zones = 2`)**, `Staging Based On = 0 (Zone)`, `Zone 1/2/3 Weighting = 1, 1, 1`, `DAT Sensor Enabled = 1`, `DAT Low Limit = 10°C`, `DAT High Limit = 47°C`, `Downstage on DAT = 1` |

### Domain 2 — `CONTROL`
| `(Dom, Attr)` | Name | Raw Data Bytes (`body[3:]`) | Decoded Meaning on User's 6003 |
| :--- | :--- | :--- | :--- |
| `(2, 1)` | Setpoint & Mode Settings | `[2, 2, 85, 22]` | `mode = 2` (`Heat`), `fan_mode = 2` (`Auto`), `heat_setpoint = 21.5°C` (`85` = `0x40 \| 21`), `cool_setpoint = 22.0°C` (`22`) |
| `(2, 2)` | Setpoint Write-Only | `NACK 0x20` | Write-only attribute |
| `(2, 3)` | Dehumidification Setpoint | `NACK 0x21` | Not available (no dehumidifier installed) |
| `(2, 4)` | Humidification Setpoint | `[50]` | `50%` RH target |
| `(2, 5)` | Fresh Air Control (HRV) | `[1, 0]` | `fresh_air_mode = 1` (`Automatic`), `fresh_air_event = 0` (`Off`, options: `0=Off`, `2=3hr`, `3=24hr`) |
| `(2, 6)` | Air Cleaning Control | `NACK 0x21` | Not available |
| `(2, 7)` | Thermostat & IAQ Available | `[5, 0, 1, 0, 2]` | `thermostat_modes = 5` (`Off, Heat, Cool, Auto`), `air_cleaning = 0`, `ventilation = 1`, `dehumidification = 0`, `humidification = 2` (`Manual`) |
| `(2, 8)` | — | `NACK 0x07` | Unknown attribute (`Heat Blast` is located at `(3, 5)` in Domain 3 `SCHEDULING`) |

### Domain 3 — `SCHEDULING`
| `(Dom, Attr)` | Name | Raw Data Bytes (`body[3:]`) | Decoded Meaning on User's 6003 |
| :--- | :--- | :--- | :--- |
| `(3, 1)` | Schedule Settings | `[1]` | Schedule configuration |
| `(3, 2)` | Away Settings | `[2, 2, 4]` | Away mode setpoints |
| `(3, 3)` | Schedule Day | `[1, 0, 6, 2, 21, 89, 0, 8, 2, 80, 93, 0, 17, 2, 21, 89, 0, 22, 2, 80, 91]` | Requires 1-byte parameter `day = 1..7` in `READ_REQUEST`. Returns 4 events (`Wake 06:00`, `Leave 08:00`, `Return 17:00`, `Sleep 22:00`). |
| `(3, 4)` | Schedule Hold | `[0, 0, 0, 0, 0, 0, 0, 0, 0, 0]` | `hold = 0` (`Disabled` / `None`; `1 = Temporary`, `2 = Permanent`, `3 = Away`, `4 = Vacation`) |
| **`(3, 5)`** | **Heat Blast (`COS_HEAT_BLAST`)** | **`[0]`** | `0 = Off`, `1 = Active` (Raises room setpoint by 3°F–5°F; exposed in iOS app right below `Fan on Auto`, maps to `COS_HEAT_BLAST` byte 15 of `(7, 1)`) |

### Domain 4 — `ALERTS`
| `(Dom, Attr)` | Name | Raw Data Bytes (`body[3:]`) | Decoded Meaning on User's 6003 |
| :--- | :--- | :--- | :--- |
| `(4, 1)` | Service Reminders Status | `[0, 0, 0, 0, 0, 66, 0, 0, 0, 0]` | Water panel / air filter reminder progress (`66%`) |
| `(4, 2)` | Alerts Status | `[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]` | No active alerts |
| `(4, 3)` | Alerts Settings | `[1, 4, 1, 13, 1, 65, 1, 30, ...]` | Low/high temperature & humidity alert thresholds |

### Domain 5 — `SENSORS`
| `(Dom, Attr)` | Name | Raw Data Bytes (`body[3:]`) | Decoded Meaning on User's 6003 |
| :--- | :--- | :--- | :--- |
| **`(5, 1)`** | **Full Sensor Values Array (8 pairs)** | **`[0, 85, 3, 0, 4, 146, 0, 47, 3, 146, 0, 43, 3, 0, 3, 0]`** | Pair 0 (Built-in Temp): `status=0 (OK), val=21.5°C`<br>Pair 1 (Wired Remote Temp): `status=3 (Not Installed), val=0`<br>Pair 2 (Wired Outdoor Temp `ODT`): `status=4, val=4.0°C` (`-18.0°C` when `146`)<br>Pair 3 (Built-in Humidity): `status=0 (OK), val=47%`<br>Pair 4 (Return Air Temp `RAT`): `status=3 (Not Installed)`<br>**Pair 5 (Leaving Air Temp `LAT` / `DAT`): `status=0 (OK), val=43.0°C` during heating (`26.0°C` idle)**<br>Pair 6 (Wireless Outdoor Temp): `status=3 (Not Installed)`<br>Pair 7 (Wireless Outdoor Humidity): `status=3 (Not Installed)` |
| `(5, 2)` | Controlling Sensors (4 pairs) | `[0, 85, 3, 0, 0, 47, 3, 0]` | Indoor Temp: `status=0, val=21.5°C`<br>Outdoor Temp: `status=3, val=0`<br>Indoor Humidity: `status=0, val=47%`<br>Outdoor Humidity: `status=3, val=0` |

### Domain 6 — `LOCKOUT`
| `(Dom, Attr)` | Name | Raw Data Bytes (`body[3:]`) | Decoded Meaning on User's 6003 |
| :--- | :--- | :--- | :--- |
| `(6, 1)` | Lockouts | `[1, 0, 0, 0, 0, 0, 0, 0]` | Keypad / lockout state |

### Domain 7 — `STATUS`
| `(Dom, Attr)` | Name | Raw Data Bytes (`body[3:]`) | Decoded Meaning on User's 6003 |
| :--- | :--- | :--- | :--- |
| `(7, 1)` | COS Subscriptions | `[1, 1, ..., 0, 1, ...]` (29 bytes) | All 28 COS channels enabled (`1`), byte 21 reserved (`0`) |
| `(7, 2)` | Sync | `NACK 0x20` | Write-only (`[1]` triggers full COS dump) |
| `(7, 6)` | Thermostat Equipment Status | `[0, 0, 0, 0]` or `[0, 0, 0, 1]` | Byte 0: `heating_equipment_status` (`0=Idle, 1=Wait, 2=Stage1...`)<br>Byte 1: `cooling_equipment_status`<br>Byte 2: `progressive_recovery`<br>Byte 3: **`fan_status`** (`0=Not Active, 1=Active`) |
| `(7, 7)` | IAQ Equipment Status | `[0, 2, 2, 0]` | Byte 0: `dehumidification_status = 0`<br>Byte 1: **`humidification_status = 2` (`Active`)**<br>Byte 2: **`ventilation_status = 2` (`Active`)**<br>Byte 3: `air_cleaning_status = 0` |
| `(7, 8)` | Error Status | `[0]` | `0 = No Error` |

### Domain 10 — `DISPLAY`
| `(Dom, Attr)` | Name | Raw Data Bytes (`body[3:]`) | Decoded Meaning on User's 6003 |
| :--- | :--- | :--- | :--- |
| `(10, 1)` | Backlight Settings | `[3, 8]` | Continuous backlight mode & brightness |

---

## 4. Deep Dive: Dual Zoning (`Whole Home` vs. `Basement`)

### Why Local TCP Port 7000 Only Sees Zone 1 (`Whole Home`)
1. **Empirical Parameter Verification**:
   - In the 6003 firmware's `READ_REQUEST` (`Action = 2`) dispatcher, each attribute has a fixed expected request length. When an attribute requires a 1-byte selector (such as `(3, 3)` `Schedule Day`), reading it with `0` payload bytes returns NACK `0x22` (`INCORRECT_READ_DATA_LENGTH`).
   - Across our complete scan of `Domains 1..15, Attributes 1..21`, **`(3, 3)` is the ONLY attribute that returns `0x22` on a 0-byte read**. Conversely, sending a 1-byte zone selector (`0x01` or `0x02`) to `(2, 1)`, `(5, 1)`, `(5, 2)`, `(7, 6)`, `(8, 4)`, or `(3, 4)` returns NACK `0x22` (`INCORRECT_READ_DATA_LENGTH`).
2. **Empirical Header Byte 0 (`revision`) Verification**:
   - Querying `(2, 1)`, `(5, 1)`, `(5, 2)`, `(7, 6)`, `(8, 4)`, and `(3, 4)` with `revision = 1` and `revision = 2` at the exact same timestamp returns identical Zone 1 (`"Whole Home"`, `22.0°C`, `46%`) payloads (with `revision` echoed in byte 0).
3. **Conclusion on Port 7000**:
   - The local port 7000 Home Automation server on the 6003 firmware is bound to Zone 1 (`Whole Home`), except for `(1, 10)` which reports global `Zone System Settings` (`number_of_zones = 2`).

### How AprilAire Healthy Air Cloud (`aprilaire.io`) Exposes Both Zones (`PZ1` & `SZ2`)
- The 6003's built-in cloud client pushes per-zone telemetry and settings to `aprilaire.io`:
  - **`PZ1` (`thermostatPZ1`)**: Primary Zone 1 — **`"Whole Home"`** (`Upstairs Hallway`)
  - **`SZ2` (`thermostatSZ2`)**: Secondary Zone 2 — **`"Basement"`**
- Each zone has independent `ThermostatStatus` (`zone: "PZ1"` / `"SZ2"`, `tempSensors`, `humSensors`, `heatingStatus`, `coolingStatus`, `isFanOn`) and `DeviceSettings` (`thermostatPZ1` / `thermostatSZ2`: `mode`, `heat`, `cool`, `fan`, `holdType`).
- In `custom_components/aprilaire_cloud/profiles/thermostat.py`, we enabled full `6003` + multi-zone (`PZ1`, `SZ2`, `SZ3`) + Celsius (`0.5°C` precision) write support so both zones can be monitored and controlled in Home Assistant:
  1. **Single-Setpoint Deadband Fix (`_encode_setpoint_pair`)**: On the 6003, when a zone is in `heat` mode (or `cool` mode), its inactive opposite setpoint (`cool` or `heat`) in `device_settings` may be below `heat` (e.g., `thermostatSZ2` had `heat = 22.0°C`, `cool = 21.0°C`). Upstream `aprilaire_cloud` unconditionally validated `_fahrenheit_grid(cool) - _fahrenheit_grid(heat) >= 3°F` even when only `command.heat` was set (`command.cool is None`), causing local `CommandValidationError` (`"The requested AprilAire change could not be applied"`). Fixed so the 3°F deadband check only applies when both `command.heat` and `command.cool` are explicitly commanded together (`heat_cool` mode), and disabled premature `mismatch_is_rejection` while the 6003 processes RS-485 updates.
  2. **Zone 2 (`SZ2`) Temperature Range Lock (`18.0°C – 23.0°C`)**: Added a persistent `RestoreEntity` switch (`switch.basement_home_basement_6003_basement_temp_lock_18_23degc`) and enforcement in `climate.py` + ` coordinator.py` that caps `min_temp = 18.0°C` and `max_temp = 23.0°C` in the Home Assistant UI and automatically clamps any external (physical wall thermostat or iOS app) setpoint outside `18.0°C–23.0°C` back into range when WebSocket updates arrive.
- **Sensor Inventory (`DeviceSetup.thermostat`)**:
  - **2 Indoor Temperature & Humidity Sensors (`type: "internal"`)**:
    1. `zone: "PZ1"` (**Whole Home** / Upstairs Hallway wall thermostat)
    2. `zone: "SZ2"` (**Basement** wall sensor / thermostat)
  - **1 Shared Leaving Air / Discharge Air Temperature Sensor (`type: "leaving-air"`, `DAT`)**:
    - Hardware: The 6003 Zone Control Board has a single `DAT` (Discharge Air Temperature) terminal pair (Manual p. 5 & p. 10, Model 8057/8052 sensor mounted in the main furnace supply plenum upstream of the zone dampers, configured with `lowLimit: 4°C`, `highLimit: 74°C`, `downstageOnDat: true`).
    - Cloud API: `DeviceSetup.thermostat.tempSensors` lists **3 temperature sensors total**: `internal (PZ1)`, `internal (SZ2)`, and **one** `leaving-air (PZ1)`. Both `thermostat/PZ1` and `thermostat/SZ2` status endpoints echo that same shared plenum `leaving-air` reading (`sensor.upstairs_hallway_aprilaire_leaving_air_temperature` in HA).

---

## 5. Deep Dive: Furnace / AC Blower Fan Operation on the 6003

Per `Aprilaire-6000-Zone-Control-Manual.pdf`:
- **Page 24 (`TABLE 9: HEAT COOL INSTALLER SETTING — IAQ Equipment Outputs`)**:
  - Step 6 (`Humidifier ON`): **`HUM/AUX = ON, G (Fan) = ON`**
  - Step 8 (`Ventilation ON`): **`VENT = ON, G (Fan) = ON`**
- **Page 25 (`FAN OPERATION`)**:
  - *"A call for Fan from any zone will initiate the G equipment output terminal. The dampers for all zones not calling for a continuous fan will be closed during the fan call."*
- **Why `Fan status` in Home Assistant Showed `On` While Thermostat Was `Off`**:
  - At `8:16:52 PM` (in the user's screenshot), `Ventilation status` (`Fresh Air 30 Min/Hour` Auto mode) and `Humidification status` (`50%` target vs `46%` actual) both turned `On` (`(7, 7) -> [0, 2, 2, 0]`).
  - Because the 6000 Series Hub energizes the furnace `G` terminal whenever Humidification or Ventilation is active, `(7, 6)` `fan_status` transitions to `On` (`1`) even if the Thermostat's HVAC mode is `Off` and `fan_mode` is `Auto`!
- **Improvements Implemented in Our Custom `aprilaire` Integration**:
  1. Added a dedicated **Furnace Fan Mode (`select` entity: `Auto`, `On`, `Circulate`)** and **Furnace Blower Fan (`fan` entity)** directly under **Controls** on the Device page so the furnace/AC blower fan can be controlled without opening the climate dialog.
  2. Updated `async_set_fan_mode`, `async_set_hvac_mode`, and `async_set_temperature` to immediately query both `read_control()` `(2, 1)` **and** `read_thermostat_status()` `(7, 6)`.
  3. Added a **Heat Blast (`switch` entity)** backed by `(3, 5)` (`0 = Off, 1 = On`).
