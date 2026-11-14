# AprilAire 6000-Series Zoned Comfort Control for Home Assistant

Complete Home Assistant integration suite, protocol reverse-engineering documentation, and upstream patches for the **AprilAire 6000-Series Zoned Comfort Control System** (`Model 6003` / `6002` / `6000`) and **8800/8900-Series Wi-Fi Thermostats**.

---

## ✨ What This Repository Solves

AprilAire 6000-series zoned HVAC systems consist of a **6000 Series Zone Control Board (Hub)** at the furnace, a **Zone 1 Wi-Fi Touchscreen Thermostat (`Model 6003`)**, and wired RS-485 **Zone 2 / Zone 3 Sensors (`Model 6006`/`6007`/`88xx`)**.

Out of the box, Home Assistant users with an AprilAire 6003 face several limitations:
1. **Local TCP (`port 7000`) only exposes Zone 1** and drops packets during startup bursts due to unpaced RS-485 queuing in `pyaprilaire`.
2. **Furnace Blower Fan control (`Auto` / `On` / `Circulate`)**, **Heat Blast (`(3, 5)`)**, **Leaving Air / Discharge Air Temperature (`(5, 1)` `DAT`)**, and **Configured Zones (`(1, 10)`)** are missing from device controls/sensors.
3. **Model `6003` (`model_number = 28`)** is reported as `"Unknown"` with raw integer hardware revision `66` instead of `Rev. B`.
4. **Zone 2 (`SZ2`) and Zone 3 (`SZ3`)** are only accessible via the AprilAire Cloud (`aprilaire.io`), where upstream `ha-aprilaire-cloud` lacked `6003` model whitelisting, `0.5 °C` Celsius step precision, and failed with `"The requested AprilAire change could not be applied"` when changing setpoints in single-setpoint (`heat` or `cool`) mode if the inactive opposite setpoint was lower than `heat + 3°F`.
5. **No Min/Max Temperature Range Lock for Secondary Zones**: The AprilAire iOS app does not allow locking a secondary zone (e.g., a Basement suite) to a `18.0 °C – 23.0 °C` range.

This repository provides **both** drop-in custom components (`aprilaire` for local TCP port 7000 + `aprilaire_cloud` for multi-zone cloud control), along with complete protocol documentation and upstream patches.

---

## 📂 Repository Structure

| Path | Description |
| :--- | :--- |
| [`custom_components/aprilaire/`](custom_components/aprilaire/) | **Local TCP (`port 7000`) integration**: RS-485 frame pacing (`0.30s`), `6003` model & `Rev. B` hardware ID, standalone **Furnace Fan Mode `select`** (`auto`, `on`, `circulate`), **Furnace Blower `fan`**, **Heat Blast `switch` (`(3, 5)`)**, **Leaving Air Temperature `sensor` (`(5, 1)`)**, and **Configured Zones `sensor` (`(1, 10)`)**. |
| [`custom_components/aprilaire_cloud/`](custom_components/aprilaire_cloud/) | **Multi-Zone Cloud (`aprilaire.io`) integration**: Full `6003`/`6002`/`6000` support, Zone 1 (`PZ1`), Zone 2 (`SZ2`), and Zone 3 (`SZ3`) `climate` and `sensor` entities, `0.5 °C` Celsius precision, single-setpoint deadband fix, and **Zone 2 Temperature Range Lock (`18.0 °C – 23.0 °C`) `switch`** with automatic clamping. |
| [`patches/ha-aprilaire-cloud-6003-multizone.patch`](patches/ha-aprilaire-cloud-6003-multizone.patch) | Clean unified diff against upstream [`billda/ha-aprilaire-cloud`](https://github.com/billda/ha-aprilaire-cloud) for submitting an upstream PR. |
| [`docs/PROTOCOL_6000_ZONING.md`](docs/PROTOCOL_6000_ZONING.md) | Complete reverse-engineered protocol reference for the AprilAire 6003 (Domains 1–15, NACK codes, RS-485 bus behavior, `(1, 10)` Zone System Settings, `(3, 5)` Heat Blast, `(5, 1)` Leaving Air Temp, and `DeviceSetup` sensor inventory). |
| [`docs/UPSTREAM_CONTRIBUTION_GUIDE.md`](docs/UPSTREAM_CONTRIBUTION_GUIDE.md) | Evaluation of all upstream AprilAire repositories (`billda/ha-aprilaire-cloud`, `chamberlain2007/pyaprilaire`, `home-assistant/core`, `chamberlain2007/aprilaire-ha`, `rborkow/pyaprilaire-cloud`) and roadmap for upstream PRs. |
| [`tools/`](tools/) | Sanitized protocol probing scripts (`probe_zones_and_fan.py`, `probe_correlated.py`) and sample attribute capture (`aprilaire_6003_probe_sample.json`). |

---

## 🚀 Installation in Home Assistant

Copy one or both integrations into your Home Assistant `/config/custom_components/` directory and restart Home Assistant:

```bash
cp -R custom_components/aprilaire /config/custom_components/
cp -R custom_components/aprilaire_cloud /config/custom_components/
```

1. **Local TCP Integration (`aprilaire`)**:
   - Connects directly to the thermostat IP on TCP port `7000` (6000-series) or `8000` (8800-series).
   - Exposes Zone 1 (`Whole Home`) climate, standalone Furnace Fan Mode (`select`), Furnace Blower Fan (`fan`), Heat Blast (`switch`), Leaving Air Temperature (`sensor`), Configured Zones (`sensor`), and IAQ status sensors.
2. **Multi-Zone Cloud Integration (`aprilaire_cloud`)**:
   - Authenticates with your AprilAire Healthy Air Cloud account (`aprilaire.io`).
   - Exposes independent `climate` and `sensor` entities for **Zone 1 (`PZ1`)** and **Zone 2 (`SZ2`)** (plus `SZ3` on 3-zone systems), attached Humidifier & Fresh Air IAQ telemetry, and the **Basement Temp Lock (`18–23 °C`)** switch.

---

## 🤝 Contributing Upstream

See [`docs/UPSTREAM_CONTRIBUTION_GUIDE.md`](docs/UPSTREAM_CONTRIBUTION_GUIDE.md) for details on submitting PRs to:
1. **[`billda/ha-aprilaire-cloud`](https://github.com/billda/ha-aprilaire-cloud)** (Multi-zone 6003 cloud support, `0.5 °C` precision, single-setpoint deadband fix)
2. **[`chamberlain2007/pyaprilaire`](https://github.com/chamberlain2007/pyaprilaire)** & **[`home-assistant/core`](https://github.com/home-assistant/core)** (Local TCP RS-485 frame pacing, Model 6003 ID, `(1, 10)`, `(3, 5)` Heat Blast, `(5, 1)` Leaving Air Temp, standalone Fan Mode `select`).
