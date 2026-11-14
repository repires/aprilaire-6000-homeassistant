# Upstream Contribution Guide — AprilAire Home Assistant Ecosystem

This document evaluates all upstream open-source repositories in the AprilAire + Home Assistant ecosystem and outlines which projects make the most sense for upstream contributions.

---

## 1. Upstream Repository Comparison

| Repository | Transport | Last Activity | Status | Recommendation |
| :--- | :--- | :--- | :--- | :--- |
| **[`billda/ha-aprilaire-cloud`](https://github.com/billda/ha-aprilaire-cloud)** | AprilAire Healthy Air Cloud (`aprilaire.io` REST + WebSocket) | **Aug 2026** (`v0.4.0b4`) | **Active HACS Integration** | **⭐ Top Priority (#1)**: Best upstream target for **6000-series (`6003`/`6002`/`6000`) multi-zone (`PZ1`/`SZ2`/`SZ3`)**, **Celsius `0.5 °C` step precision**, and **single-setpoint (`heat`/`cool`) deadband fixes**. |
| **[`chamberlain2007/pyaprilaire`](https://github.com/chamberlain2007/pyaprilaire)** | Local TCP Socket (`port 7000` / `8000` RS-485 automation bus) | **Oct 2026** (`CI/PyPI`) | **Active Python Library** (powers official HA Core integration) | **⭐ Priority (#2a)**: Best upstream target for **RS-485 `_queue_loop` frame pacing (`0.30s`)**, **Model `6003` (`id=28`)**, **Leaving Air Temp `(5, 1)`**, **Zone System Settings `(1, 10)`**, and **Heat Blast `(3, 5)`**. |
| **[`home-assistant/core`](https://github.com/home-assistant/core)** (`homeassistant/components/aprilaire`) | Local TCP Socket (`port 7000` / `8000` via `pyaprilaire`) | **Active** | **Official Home Assistant Core Integration** | **⭐ Priority (#2b)**: Once `pyaprilaire` releases a bump, submit a PR to `home-assistant/core` exposing the standalone **Furnace Fan Mode `select` entity**, **Heat Blast `switch` entity**, **Leaving Air Temp `sensor`**, and **Configured Zones `sensor`**. |
| **[`chamberlain2007/aprilaire-ha`](https://github.com/chamberlain2007/aprilaire-ha)** | Local TCP Socket (`port 7000` / `8000`) | Jul 2024 | **Deprecated** (merged into `home-assistant/core` in 2023.3) | **Do not target for PRs** (kept in `custom_components/aprilaire/` here as a drop-in HACS override of the built-in `aprilaire` component so users don't have to wait for HA Core release cycles). |
| **[`rborkow/pyaprilaire-cloud`](https://github.com/rborkow/pyaprilaire-cloud)** | Cloud API library | Aug 2026 | Initial library only (no HA component) | Lower priority than `billda/ha-aprilaire-cloud`, which is a complete, actively maintained HACS integration with WebSocket push + REST reconciliation. |

---

## 2. Why We Need Both `aprilaire_cloud` and Local `aprilaire` on 6000-Series Zoned Systems

On the **AprilAire 6000-Series Zoned Comfort Control (`Model 6003`)**:
1. **Local TCP Port 7000 (`custom_components/aprilaire`)**:
   - Provides **100% local, zero-cloud-dependency** control of **Zone 1 (`Whole Home`)**, plus hardware attributes that the Cloud API does not expose as writable controls:
     - **Heat Blast (`(3, 5)` switch)**
     - **Leaving Air / Discharge Air Temperature (`(5, 1)` sensor)**
     - **Configured Zones (`(1, 10)` sensor)**
     - **Instantaneous local COS (`(7, 6)`, `(7, 7)`) equipment status**
   - However, the 6003 firmware's local port 7000 automation server is strictly bound to Zone 1 (`Whole Home`) and rejects zone-selector parameters with NACK `0x22` (`INCORRECT_READ_DATA_LENGTH`).
2. **AprilAire Cloud (`custom_components/aprilaire_cloud`)**:
   - The 6003 pushes independent per-zone telemetry and settings for **Zone 1 (`PZ1` / `thermostatPZ1`)**, **Zone 2 (`SZ2` / `thermostatSZ2`)**, and **Zone 3 (`SZ3` / `thermostatSZ3`)** to `aprilaire.io` over WebSocket + REST.
   - Enables full Home Assistant climate control, indoor temperature/humidity sensing, and temperature range locking (`18.0 °C – 23.0 °C`) for **Zone 2 (`Basement`)** and **Zone 3**.

---

## 3. Ready-to-Submit Upstream PR Breakdown

### A. PR to `billda/ha-aprilaire-cloud` (Patch: `patches/ha-aprilaire-cloud-6003-multizone.patch`)
1. **Expand `_CONFIRMED_8920W_MODELS` (`profiles/thermostat.py`)**:
   - Add `"6003"`, `"6003_GS"`, `"6002"`, `"6000"`, `"8840"`, `"8840_GS"`, `"8840M"`, `"8830"`, `"8820"`, `"8810"`.
2. **Fix Single-Setpoint Deadband Validation (`profiles/thermostat.py` — `_encode_setpoint_pair`)**:
   - When a zone is in single-setpoint `heat` or `cool` mode, its inactive opposite setpoint (`cool` in `heat` mode, or `heat` in `cool` mode) can legitimately violate `cool - heat >= 3°F` (for example, `heat = 22.0 °C` while inactive `cool = 21.0 °C`).
   - Only enforce `_fahrenheit_grid(cool) - _fahrenheit_grid(heat) >= _CONFIRMED_8920W_DEADBAND_F` when **both** `command.heat is not None` and `command.cool is not None` (`heat_cool` / `auto` mode).
3. **Native Celsius `0.5 °C` Setpoint Grid (`profiles/thermostat.py` — `_requested_setpoint`)**:
   - Preserve `0.5 °C` step precision (`round(number * 2) / 2`) instead of snapping Celsius setpoints to whole-Fahrenheit increments (`5/9 °C`).
4. **Fix Premature In-Flight Rejection on Zoned Controllers (`profiles/thermostat.py` — `mismatch_is_rejection`)**:
   - On 6000-series zone control boards, the Zone 1 thermostat forwards `SZ2`/`SZ3` setpoint changes over the 19200-baud RS-485 bus before the updated `DeviceSettings` frame is pushed back to the cloud. Returning `False` for `mismatch_is_rejection` prevents intermediate pre-echo snapshots from aborting the write before WebSocket confirmation arrives (~3 seconds).
5. **Zone-Friendly Entity Naming & Optional Zone 2 Temperature Range Lock (`climate.py`, `sensor.py`, `switch.py`, `coordinator.py`)**:
   - Label multi-zone entities clearly (`Whole Home (Zone 1)`, `Basement (Zone 2)`, `Zone 3`) and provide an optional per-zone temperature range lock switch (`18.0 °C – 23.0 °C`) that clamps both UI changes and external wall-thermostat changes.

### B. PR to `chamberlain2007/pyaprilaire` & `home-assistant/core` (`custom_components/aprilaire/`)
1. **RS-485 Outgoing Frame Pacing (`client.py` / `coordinator.py`)**:
   - Pace outgoing frames in `_queue_loop` by `0.30s` per frame instead of draining the queue in a `0ms` burst, preventing RS-485 collisions on 6000-series systems.
2. **Extended `(8, 2)` & `(8, 4)` Identification**:
   - Support 14-byte `(8, 2)` payloads on GainSpan `4.14` firmware without truncating bytes `7..13`.
   - Map `model_number = 28` to `"6003 (6000-Series Zone Control)"` and ASCII hardware revision bytes (`66` -> `"Rev. B"`).
3. **New Attributes**:
   - `(1, 10)` `Zone System Settings` (`number_of_zones`)
   - `(3, 5)` `Heat Blast` (`0 = Off`, `1 = On`, synced with `COS_HEAT_BLAST` bit 15 of `(7, 1)`)
   - `(5, 1)` byte 2 `Leaving Air Temperature` (`LAT` / `DAT` plenum sensor)
4. **Standalone Furnace Fan Mode `select` & `fan` Entities**:
   - Expose `select.<device>_furnace_fan_mode` (`auto`, `on`, `circulate`) and `fan.<device>_furnace_blower_fan` directly under device controls, and refresh both `(2, 1)` and `(7, 6)` immediately after mode/fan/setpoint writes.
