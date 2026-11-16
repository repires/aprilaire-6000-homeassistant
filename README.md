# AprilAire 6003 local and cloud integrations for Home Assistant

This repository provides a local `aprilaire` override and an `aprilaire_cloud` fork for AprilAire 6003 zoned systems. It targets **Home Assistant 2026.11.1 or newer**. Cloud thermostat support is experimental and restricted to evidenced contracts.

## Choosing an integration

| Integration | Supported use |
|---|---|
| Local TCP (`aprilaire`, version 1.2.0) | The networked primary thermostat, IAQ/equipment telemetry, a fan-mode select, Heat Blast when its state is readable, leaving/return-air sensors when installed, and reported zone count. |
| Cloud (`aprilaire_cloud`, fork version 0.4.1) | Reported PZ1/SZ2/SZ3 zones. Setpoint writes on 6003/6003_GS use Celsius wire values and a 0.5°C grid; 8920W/8920W_GS retain their confirmed single-zone Fahrenheit-display contract and whole-Fahrenheit grid. Unknown contracts remain read-only. Existing supported dehumidifier behavior is retained. |

No inspected implementation demonstrates secondary-zone control through the tested 6003 local automation socket. Invalid selector requests do not prove that every firmware or other interface is incapable of local zoning. Cloud SZ2 writes were previously reported on one two-zone 6003 installation; other configurations require their own validation.

Use one automation connection per thermostat. The custom local component overrides HA's built-in `aprilaire` integration. Keep one automation owner for each controlled setting to avoid local/cloud automations competing. Fan mode is a request; ventilation, humidification and other zones can keep the blower running. There is a fan-mode **select**, not a standalone `fan` entity.

## Installation

Back up any existing custom component directories, then copy the desired folders from `custom_components/` into HA's `/config/custom_components/`. Restart Home Assistant to import the new Python modules. Add/reconfigure the local integration with its actual host and port (typically 7000 for the tested 6003); use a DHCP reservation or stable hostname. Automatic subnet scanning is not performed.

For cloud setup, use an AprilAire Healthy Air (`aprilaire.io`) account. A successful HTTP PATCH means accepted, not necessarily applied: delayed writes are reconciled through WebSocket and bounded REST checks. A write that remains unconfirmed is logged. Preserve HA configuration/backups as credentials are stored in config-entry data.

## Optional secondary-zone range policy

Each supported 6003 secondary zone has its own temperature range-lock switch. New switches default **off**; existing switch IDs and saved on/off states are preserved. The default range is **18–23°C**. Change the bounds in the cloud integration's options; the range must span at least 2°C and bounds must be on the 0.5°C grid.

This is a reactive HA policy, not a physical keypad lock or an authorization boundary. Enforcement requires HA, cloud connectivity, manage access and an available device. Corrections are coalesced, limited to one attempt per zone per minute, and canceled on unload/disable. Only active single-mode setpoints are clamped; auto pairs retain at least the conservative 3°F separation. A failed correction is exposed in the switch's `last_error` attribute and retried only on a later update after the cooldown. If the switch entity is disabled, its saved policy is not activated on startup.

The range currently shares configured bounds within one cloud config entry; enablement and correction tasks are independent per device and zone. SZ2 does not inherently mean Basement. Entity registry IDs are preserved when display names change.

## Development and validation

```sh
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/pytest -q
.venv/bin/ruff check custom_components tests
.venv/bin/ruff format --check custom_components tests
```

Offline tests disable Internet/LAN sockets and use fake transports or synthetic device payloads. They exercise frame reassembly/CRC/NACKs, reconnect initialization and cleanup, model gates, units/grids, deadband, range policies, availability/fallback and WebSocket failures. They do not establish support for every hardware/firmware combination.

`tools/probe_*.py` are historical active probing scripts: they disable a HA entry and open a thermostat connection. Do not import them as tests or run them alongside the integration. `tools/aprilaire_6003_probe_sample.json` contains synthetic payloads derived from observations; identifiers were replaced and the original CRC-validity claims removed. It is not an original wire capture.

## Research and upstream work

- [Implementation review and ranked findings](docs/IMPLEMENTATION_REVIEW_2026-11-15.md)
- [Observed protocol reference](docs/PROTOCOL_6000_ZONING.md)
- [Current upstream contribution guide](docs/UPSTREAM_CONTRIBUTION_GUIDE.md)

Stable pyaprilaire 0.9.1 already recognizes model 6003. Its 0.10 candidate has stronger protocol APIs but requires a coordinated migration; changing only the dependency pin is insufficient. Prefer upstream/core adoption as equivalent fixes reach stable releases.
