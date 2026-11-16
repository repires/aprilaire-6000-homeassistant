# Reliability fixes: implementation and deployment receipt

The findings in [the review](IMPLEMENTATION_REVIEW_2026-11-15.md) were investigated at commit `2860c279c2400dcc6f83f9c383e9e58be5552312`. The user subsequently authorized implementation, testing, deployment, commits, pushes and upstream contributions.

## Shipped behavior

- Local component **1.2.0**: component-owned streaming parser and connection lifecycle; no global library monkey-patches or subnet scanning. Per-connection initialization, paced sends, correlated reads/NACKs, timeout recovery, awaited task cleanup, current availability and validated raw-sensor fallback. Heat Blast is exposed only after readable state is observed.
- Cloud fork **0.4.1**: explicit 6003 and 8920W contracts, separate temperature grids, model/mode-aware deadband and mismatch handling, independent restored secondary-zone range policies, framework shutdown cleanup and supervised WebSocket ping failures.
- Range switches preserve existing unique IDs and saved state; new switches default off. Bounds are configurable on a half-degree Celsius grid. Policy writes are coalesced, throttled and canceled with their owner.
- Climate properties use HA's native-temperature API. Documentation and synthetic protocol samples no longer promise a nonexistent fan entity or claim all secondary-zone local access is impossible.

## Verification

The worktree's **43 offline tests pass** on Python 3.14.9 with HA 2026.11.1. Internet/LAN sockets are disabled during tests. Ruff check, Ruff format check, AST/JSON validation and git whitespace checks pass. One warning originates in HA's aiohttp application class. An independent reviewer identified corrupted-length recovery, unrepresentable range bounds and malformed unit evidence; all have fixes and regression tests.

The local library contribution passes **301 packet/client/constants/socket tests**. A full-library attempt reached 546 passing tests before hanging and being interrupted; its remaining interactive/session tests are not certified.

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

## Upstream contributions

- [pyaprilaire #126](https://github.com/chamberlain2007/pyaprilaire/pull/126): updated against current develop while retaining upstream's newer parser/client APIs; redundant model/length changes removed.
- [Cloud #13](https://github.com/billda/ha-aprilaire-cloud/pull/13): narrowed model contracts and preserved 8920W semantics; added synthetic tests and safe config-flow isolation. Household range policy excluded.
- [Cloud #16](https://github.com/billda/ha-aprilaire-cloud/pull/16): independent coordinator shutdown and WebSocket ping-failure fixes, with regression tests.

These contributions are submitted for upstream review, not merged. No HA core dependency bump was submitted because the required library release is still a candidate.
