# AprilAire reliability implementation plan

> Execute inline with the executing-plans and test-driven-development skills.

**Goal:** Resolve the reviewed defects, deploy the tested components with rollback, and publish focused upstream contributions.

**Architecture:** Keep pyaprilaire 0.9.1 and own the extended protocol/client through subclasses and private mapping copies. Use explicit cloud model contracts and a coordinator-owned per-zone range policy. Preserve entity unique IDs and existing user configuration.

**Spec:** `docs/IMPLEMENTATION_REVIEW_2026-11-15.md`, authorized for implementation/deployment by the user's next message.

**Constraints:** No global protocol monkey-patches, no automatic subnet scans, no credentials in artifacts. New range locks default off; restore existing per-device switch state before enforcement. Local/cloud endpoints must not be contacted by offline tests. Live acceptance uses telemetry/reloads, preserving HVAC settings. Deploy only after regression tests; back up both deployed directories first. Push this branch, and contribute focused upstream PRs without merging third-party branches.

## Review focus

- Fragmented/corrupt TCP and terminal NACKs must never corrupt later frames.
- Reconnect/unload must not retain senders, polling tasks, or stale availability.
- Celsius and Fahrenheit display contracts must retain their own setpoint grids.
- Partial auto-mode writes and range clamping must preserve valid separation.
- Failed/disabled range policies must not flood writes or affect another device.

## Tasks

1. Add a reproducible Python/HA test environment and regression fixtures; observe current parser, reconnect, fallback and cloud contract failures.
2. Add `aprilaire/protocol.py`: bounded streaming decoder, owned sender/initialization tasks, paced 6003 initialization per connection, client shutdown. Simplify coordinator to use it; remove subnet discovery, keep raw sensor data, fix entity availability and setup cleanup. Gate unsupported Heat Blast.
3. Constrain cloud model contracts (6003 native C; existing 8920W whole-F grid), mode-aware final-pair validation and operating states. Add a coordinator-owned coalesced SZ2 range policy with independent restored switches and bounded retry. Call base shutdown and supervise WebSocket ping errors.
4. Correct documentation, sanitize captures consistently, distinguish fork versions/support, add CI. Run the complete local suite and lint; obtain an independent final code review and fix accepted findings.
5. Back up deployed components; install exact tested files, restart HA to load updated modules, inspect setup/entities/logs, exercise an entry reload and verify no unintended setpoint changes. Roll back if acceptance fails. Record concrete evidence without identifiers/secrets.
6. Commit/push; update focused upstream branches/PRs or open new narrowly scoped fixes with regression tests and honest validation. Verify remote SHAs and CI status; report deployment and contribution links.

## Progress

- Planning: report and current code re-read; existing isolated worktree retained. User has authorized all six tasks; no extra approval gate is needed.

- Tasks 1–4: complete. Offline regressions, implementation, independent review and fixture/packaging updates are verified; 43 tests pass.
- Task 5: complete. Both components backed up, 43 deployed files hash-verified, HA restarted, both entries reloaded; 31 entities available and compared controls unchanged.
- Task 6: complete. Source commit `b7840a470c2850d717fbeb93759707c80d81dfb8` pushed and remote SHA verified; repository PR #1 opened and its Test workflow passed. Upstream PR #126 and #13 updated; independent cloud PR #16 opened. See `docs/RELIABILITY_DEPLOYMENT.md` for exact evidence and limitations.
