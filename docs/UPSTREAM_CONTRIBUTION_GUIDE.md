# AprilAire upstream contribution guide

Status checked during the November 2026 review; verify linked PRs before starting new work.

| Project | Contribution target |
|---|---|
| [chamberlain2007/pyaprilaire](https://github.com/chamberlain2007/pyaprilaire) | Local protocol/library fixes against `develop`. Stable is 0.9.1; 0.10.0rc3/release PR #64 are not a stable HA dependency upgrade. |
| [home-assistant/core](https://github.com/home-assistant/core/tree/dev/homeassistant/components/aprilaire) | HA entities and lifecycle, after needed library APIs reach an appropriate release. Introduced in HA **2024.3**. |
| [billda/ha-aprilaire-cloud](https://github.com/billda/ha-aprilaire-cloud) | Complete cloud HA integration. Keep generic model contracts and lifecycle fixes separate from local household policies. |
| [chamberlain2007/aprilaire-ha](https://github.com/chamberlain2007/aprilaire-ha) | Archived; do not submit new implementation work here. |
| [rborkow/pyaprilaire-cloud](https://github.com/rborkow/pyaprilaire-cloud) | Small REST library tested with E-series dehumidifiers; not a multizone thermostat HA replacement. |

## Existing proposals

- [pyaprilaire #126](https://github.com/chamberlain2007/pyaprilaire/pull/126): pacing, extended identification and 6000 attributes. Some parser/model changes already exist in stable/develop; do not reintroduce old parsing or private monkey-patches when rebasing. Include fake-transport/frame fixtures and regression tests.
- [Cloud #13](https://github.com/billda/ha-aprilaire-cloud/pull/13): 6003 multizone setpoints. Restrict contracts to evidenced models, preserve the 8920W grid and make final-pair validation mode-aware. A similar JSON shape does not establish units, constraints or write support.
- [Cloud #14](https://github.com/billda/ha-aprilaire-cloud/pull/14): operating-state variants. Cover split cooling/heating statuses with fixtures.
- [Cloud #12](https://github.com/billda/ha-aprilaire-cloud/pull/12): explicit thermostat settings `scale` as display-unit evidence; distinguish display preference from Celsius wire values.

## Contribution boundaries

Submit focused changes with synthetic fixtures, exact behavior and reproducible tests. Never attach tokens, raw account/device IDs, addresses, room names or unsanitized wire dumps. A model name added to an allowlist needs evidence for its wire unit, grid, mode/deadband and zone mapping. Observations from one 6003 two-zone installation do not establish all 6000/6002/8840 devices or SZ3 writes.

The local component owns a compatibility adapter over stable pyaprilaire 0.9.1; it must not mutate global packet tables/classes. Upstream's newer client API should eventually replace it through a tested migration. The cloud range policy belongs in this fork unless the upstream maintainer explicitly accepts it; it is opt-in, independent per device/zone and not a physical thermostat lock.

The patch under `patches/` is historical and has been superseded by the linked PRs. It includes old workstation paths and site-specific behavior and must not be applied blindly. Generate future patches with `git diff` against a named upstream commit.

See [the review](IMPLEMENTATION_REVIEW_2026-11-15.md) for evidence, limitations and the ranked roadmap.
