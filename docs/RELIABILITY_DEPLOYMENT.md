# Reliability fixes: implementation and deployment receipt

The findings in [the review](IMPLEMENTATION_REVIEW_2026-11-15.md) were investigated at commit `2860c279c2400dcc6f83f9c383e9e58be5552312`. The user subsequently authorized implementation, testing, deployment, commits, pushes and upstream contributions.

## Shipped behavior

- Local component **1.2.0**: component-owned streaming parser and connection lifecycle; no global library monkey-patches or subnet scanning. Per-connection initialization, paced sends, correlated reads/NACKs, timeout recovery, awaited task cleanup, current availability and validated raw-sensor fallback. Heat Blast is exposed only after readable state is observed.
- Cloud fork **0.4.1**: explicit 6003 and 8920W contracts, separate temperature grids, model/mode-aware deadband and mismatch handling, independent restored secondary-zone range policies, framework shutdown cleanup and supervised WebSocket ping failures.
- Range switches preserve existing unique IDs and saved state; new switches default off. Bounds are configurable on a half-degree Celsius grid. Policy writes are coalesced, throttled and canceled with their owner.
- Climate properties use HA's native-temperature API. Documentation and synthetic protocol samples no longer promise a nonexistent fan entity or claim all secondary-zone local access is impossible.

## Verification

The worktree's **43 offline tests pass** on Python 3.14.9 with HA 2026.11.1. Internet/LAN sockets are disabled during tests. Ruff check, Ruff format check, AST/JSON validation and git whitespace checks pass. One warning originates in HA's aiohttp application class. An independent reviewer identified corrupted-length recovery, unrepresentable range bounds and malformed unit evidence; all have fixes and regression tests.

The local library contribution passes **301 packet/client/constants/socket tests**. A baseline full-library attempt reached 546 passing tests before hanging and being interrupted; its remaining interactive/session tests are not certified.

The cloud contract contribution passes **216 tests**, with **95.04%** statement coverage. The independent shutdown/ping contribution passes **203 tests**, with **95.02%** coverage. Both exceed upstream's 95.01% gate. These runs used the available Python 3.14 environment. Full-package mypy encounters six existing config-flow schema annotation incompatibilities against newer HA typing. A local attempt to provision the upstream Python 3.13 environment could not build its pinned lru-dict dependency because no C compiler is installed; upstream CI remains the check for that exact environment.

## Live acceptance

Both old component directories were backed up privately before replacement. The backup matched the reviewed repository source, so no preexisting deployment changes were overwritten. Backup directory on Hermes:

`~/.hermes/backups/home-assistant/aprilaire-reliability-20261116T035427Z`

All **43 deployed Python/JSON files were read back and SHA-256 checked**. The final deployment manifest fingerprint is `b4e21c00fda872675134098f6411a25baaf6e13d9b6a702b3eddac255ae5a04e`.

After restarting HA core to remove the previous process-wide patches, and again after reloading each entry:

- HA **2026.11.1** reports both entries loaded.
- All **31 AprilAire entities** are available; none reports unknown/unavailable.
- The existing range switch restores on and reports no policy error.
- Compared HVAC modes, heat/cool targets, fan modes and presets are unchanged.
- The current system-log list contains no AprilAire errors/warnings.

Live verification used telemetry and entry reloads. It did not deliberately change thermostat targets, fan mode, Heat Blast, humidity or schedules. Hardware behavior for other firmware/models and SZ3 writes remains unverified.

Rollback: restore the backed-up component files through the existing authenticated File editor, remove the newly introduced `aprilaire/protocol.py` and `aprilaire_cloud/range_lock.py` if reverting completely, then restart HA core. No HA configuration or registry migration is required.

## Repository publication

Source commit [`b7840a4`](https://github.com/repires/aprilaire-6000-homeassistant/commit/b7840a470c2850d717fbeb93759707c80d81dfb8) was pushed to `repires/aprilaire-review` and its remote SHA verified. [Repository PR #1](https://github.com/repires/aprilaire-6000-homeassistant/pull/1) is open. The [Test workflow](https://github.com/repires/aprilaire-6000-homeassistant/actions/runs/43803691588) passed installation, all 43 offline tests, Ruff check and format check on GitHub Actions. The code/JSON deployment hashes match this source commit.

## Upstream contributions

- [pyaprilaire #126](https://github.com/chamberlain2007/pyaprilaire/pull/126): updated against current develop while retaining upstream's newer parser/client APIs; redundant model/length changes removed.
- [Cloud #13](https://github.com/billda/ha-aprilaire-cloud/pull/13): narrowed model contracts and preserved 8920W semantics; added synthetic tests and safe config-flow isolation. Household range policy excluded.
- [Cloud #16](https://github.com/billda/ha-aprilaire-cloud/pull/16): independent coordinator shutdown and WebSocket ping-failure fixes, with regression tests.

These contributions are submitted for upstream review, not merged. No HA core dependency bump was submitted because the required library release is still a candidate.

## Upstream review follow-up (local 1.3.0, 2026-11-16)

The maintainer's review of [pyaprilaire #126](https://github.com/chamberlain2007/pyaprilaire/pull/126#pullrequestreview-5924028348) asked for four changes: `_and_wait` variants, a note that SETUP 10 is undocumented, a comment explaining the pacing, and a Heat Blast COS subscription. All four were made upstream. The PR branch was also rebased onto develop after [#127](https://github.com/chamberlain2007/pyaprilaire/pull/127). The full library suite passes (589 tests), as do ruff check and ruff format.

[HA core #186563](https://github.com/home-assistant/core/pull/186563) is the maintainer's draft bump to pyaprilaire 0.10. It zero-pads MAC addresses and migrates config entries to the padded form. Its Copilot findings about MACs regrouped by `format_mac` are fixed in the current head. An exhaustive offline check over 262,144 legacy MAC shapes found no mismatches.

This component gets the same changes where they apply:

- **Heat Blast COS.** The component writes its own subscription mask. The mask matches 0.9.1's, except that Heat Blast is on. The switch now updates when the thermostat changes, not only on the five-minute poll.
- **Pacing.** The intervals are named constants with the 6003 evidence explained. An unidentified model is paced, as it is upstream.
- **Heat Blast writes.** Each write is confirmed by reading the state back. When the write is not applied or the thermostat is disconnected, the switch raises `HomeAssistantError` instead of returning silently.
- **MAC identity.** Setup compares MACs in zero-padded form. An entry already migrated by core's 0.10 bump therefore still sets up under this component. Stored IDs are not rewritten.

**Verification:** 57 offline tests pass, including 14 new regression tests. Ruff check and ruff format pass.

**Deployment:**

- A fresh backup is at `~/.hermes/backups/home-assistant/aprilaire-upstream-review-20261116T233933Z` (43 files).
- The live files matched the previous release manifest, so no drift was overwritten.
- Five files were installed and checked by read-back hash.
- After the HA core restart, both entries loaded on 2026.11.1. All 31 entities were available, with no changes to compared controls. The range lock restored to on without error, the Heat Blast switch was present, and the system log had no AprilAire entries.
- Heat Blast was not toggled on the live system.

**Rollback:** restore `aprilaire/{__init__,coordinator,protocol}.py` and `aprilaire/manifest.json` from that backup, then restart HA core.

## Hardware test of HA core #186563 and pyaprilaire 0.10.0rc4 (2026-11-16)

The maintainer asked for this on [pyaprilaire #126](https://github.com/chamberlain2007/pyaprilaire/pull/126). The test used a throwaway HA 2026.11.1 instance with the live local entry paused. The entry was created with the built-in integration and pyaprilaire 0.9.1, then the PR integration and rc4 were loaded on the same storage. The live entry was never migrated, and it reloaded with all 31 entities available afterwards.

- **Migration:** the entry went from 1.1 to 1.2. Entity IDs, entity unique IDs and device identifiers were unchanged. This MAC has no octet below 0x10, so only the no-op path ran.
- **Control:** the heat target was moved from 21.0 to 21.5 °C, confirmed, and restored to 21.0. Reconnect took 10 s. There were no unexpected disconnects over three connections, including a 60 s watch.
- **Sync rejected:** the 6003 accepts the 1-byte Sync write (`07 02 01`) and NACKs rc4's 2-byte form (`07 02 01 00`) with 0x13 on every connect. This was reported upstream.
- **Pacing:** unpaced bursts of 11–14 frames did not drop the connection. The disconnects that originally motivated pacing were seen with 0.9.1's parser, so pacing is a precaution rather than a proven requirement. The comment in `protocol.py` was corrected in the repository only. The deployed 1.3.0 still has the old comment, but its code is otherwise identical.

## Cloud 0.4.2: moving the other setpoint to keep the deadband (2026-11-18)

Deployed after merging PR #2. A backup is at `~/.hermes/backups/home-assistant/aprilaire-cloud-042-20261118T210155Z`. The only drift before deploying was the comment-only `aprilaire/protocol.py` change, which this deploy also installed. Live files now match `main`. After the restart on HA 2026.11.2, both entries loaded and all 31 entities were available, with no control changes and no AprilAire log entries.

A live test on the 6003 primary zone (PZ1) used the cloud climate entity. Baseline: heat mode, 21.5/22.0 °C, room 23.0 °C.

| Step | Request | Result |
|---|---|---|
| Prepare | heat mode, widen to 21.5/23.5 | applied |
| Enter auto | `heat_cool` | applied |
| Raise heat into the deadband | heat 22.5, cool unchanged | 22.5/24.5: cool pushed up by 2.0 °C |
| Lower cool into the deadband | cool 23.5, heat unchanged | 21.5/23.5: heat pushed down by 2.0 °C |
| Restore | heat mode, then 21.5/22.0 | exact baseline, confirmed again 30 s later |

Each write was confirmed in 2–7 s. The HVAC stayed idle throughout, and the basement zone (SZ2, range-locked) was not touched.
