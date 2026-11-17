# AprilAire 6000/6003 implementation review

Reviewed 2026-11-15 against worktree commit `2860c279c2400dcc6f83f9c383e9e58be5552312`. Investigation only; no integration implementation was changed, no HVAC/AprilAire account was contacted, and nothing was deployed or published.

> Follow-up: the user authorized implementation and deployment. See the [deployment receipt](RELIABILITY_DEPLOYMENT.md) for fixes, tests, live acceptance and upstream contributions. Findings below refer to the original reviewed commit.

## Recommendation

**Keep the local/cloud split, improve this fork now, and progressively replace its internals with upstream implementations.** There is no verified, maintained, drop-in alternative in the surveyed projects that provides fully local 6003 secondary-zone control. Stock HA is the preferred long-term local integration, but it does not yet replace the fork's complete 6000-specific feature set. The cloud fork is still needed for the reported SZ2 writes; its broad capability changes and automatic temperature lock need tightening before general distribution.

The most valuable work is reliability and narrowly evidenced device support, rather than adding more entities or more protocol scanning. Keep one control owner for each function: for example, cloud for zoned temperature commands and local for equipment telemetry/extra controls. Two independent automations commanding the same zone can overwrite one another even when each integration serializes its own writes.

## Scope, evidence, and historical context

- Read `/documents/dev/AGENTS.md`, the repository README, upstream contribution guide, protocol document, all local integration modules, and cloud lifecycle, state/entity discovery, climate, switch, profile, REST, authentication, WebSocket, and diagnostic code. The Orca worktree has no additional AGENTS.md. The registered clone and current worktree were distinguished; the report belongs to this worktree.
- Consulted the accessible Matrix Obsidian vault over read-only SSH: `SCHEMA.md`, `index.md`, and recent `log.md`. A bounded search of entities/concepts/session notes/queries found no AprilAire/6003 note. The vault was not mounted locally and its unauthenticated Forgejo mirror redirected to login. No deployed HA state or installed component version was inferred from old infrastructure notes. An ai-memory global search supplied no substantive prior protocol evidence.
- Current upstream metadata and source were read from GitHub, including release metadata, issue/PR state, release-tagged code and current branches. Public GitHub REST/raw reads supplemented the connector for release metadata and exact source comparisons.
- “Confirmed” below means demonstrated by source/control flow or included capture, not reproduced on a live thermostat. “Risk” means an outcome depends on device behavior, timing, or deployment and still needs validation. Priority P1 means fix before broader use; P2 means the next reliability/maintenance pass. These are engineering priorities, not vulnerability severity ratings.
- Safe checks: Python 3.12.3 parsed all **37 Python files** with `ast.parse`; all **7 JSON files** decoded successfully. The sample has **46 capture records**. No tests or cloud fixtures are included. No repository module or probing script was executed. OS network namespace isolation is unavailable (`unshare -Urn true` returns “Operation not permitted”), so target-code execution was deliberately omitted. Syntax checks do not establish HA compatibility or device correctness.

## What upstream actually offers now

| Project | Verified current state | Consequence |
|---|---|---|
| Home Assistant core | Latest release checked: **2026.11.1**, published November 9. Both that release and current `dev` pin **pyaprilaire 0.9.1**. | Best maintained HA lifecycle/platform integration; still not a complete replacement for these custom 6000 controls. |
| chamberlain2007/pyaprilaire | Stable **0.9.1**, May 28, 2025. Default `develop` at `301e035…`; latest candidate **0.10.0rc3**, October 15, 2026. Release PR **#64 remains open**; candidate requires Python 3.14. | Much stronger protocol implementation exists, but it is a candidate with API changes, not a safe manifest-only dependency bump. |
| billda/ha-aprilaire-cloud | Main `027c452…`; latest published release **v0.4.0b4**, August 12, 2026, marked prerelease. Current issues/PRs include **#8, #9, #11–#15**. | Best complete cloud HA foundation surveyed, but still beta. Issue/PR activity is not evidence that fixes are merged. |
| chamberlain2007/aprilaire-ha | Archived; latest release **0.8.1**, March 2024; last source activity July 2024. | Do not replace this fork with the old custom component. Use core as the integration target. |
| rborkow/pyaprilaire-cloud | **v0.1.0**, August 6, 2026; one initial main commit, E080W-tested REST client. No issues returned. | Useful small library/reference, not a ready thermostat/multizone HA replacement; no equivalent WebSocket/entity/coordinator layer. |

Direct primary sources: [HA release](https://github.com/home-assistant/core/releases/tag/2026.11.1), [released HA manifest](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/aprilaire/manifest.json), [current HA manifest](https://github.com/home-assistant/core/blob/dev/homeassistant/components/aprilaire/manifest.json), [pyaprilaire stable](https://github.com/chamberlain2007/pyaprilaire/releases/tag/0.9.1), [candidate](https://github.com/chamberlain2007/pyaprilaire/releases/tag/0.10.0rc3), [release PR #64](https://github.com/chamberlain2007/pyaprilaire/pull/64), [cloud release](https://github.com/billda/ha-aprilaire-cloud/releases/tag/v0.4.0b4), [archived integration](https://github.com/chamberlain2007/aprilaire-ha), [rborkow source/limitations](https://github.com/rborkow/pyaprilaire-cloud/blob/main/README.md).

### Superseded versus still outstanding

**Already superseded:** model IDs `14 → 8840M` and `28 → 6003` are already in the very **0.9.1** dependency this fork pins, following [merged PR #32](https://github.com/chamberlain2007/pyaprilaire/pull/32). The README's claim that upstream still calls 6003 unknown is stale. Stable core also already contains the hardware-revision formatting logic copied here. Local LAT decoding exists in 0.9.1; the fork adds polling and entity exposure, not discovery of a completely absent parser field.

**Better upstream implementation, pending stable adoption:** `develop` already provides correct 16-bit lengths, buffered TCP reassembly, bounded field decoding, CRC-aware NACK parsing, sequence-aware response handling and terminal NACK handling. It also reads full sensor values through a supported client method ([PR #94](https://github.com/chamberlain2007/pyaprilaire/pull/94)) and preserves COS subscription settings ([PR #88](https://github.com/chamberlain2007/pyaprilaire/pull/88)). These are preferable to maintaining the custom wholesale parser replacement.

**Still outstanding:** [pyaprilaire PR #126](https://github.com/chamberlain2007/pyaprilaire/pull/126) for pacing/extended identification/6000 attributes is open and unmerged. Its length-fix premise overlaps work already in `develop`; rebase and reduce it before resubmission. [Cloud PR #13](https://github.com/billda/ha-aprilaire-cloud/pull/13) is also open and unmerged. [Issue #9](https://github.com/billda/ha-aprilaire-cloud/issues/9) reports 6003 multizone experience; it is supporting user evidence, not a merged implementation or independent protocol specification.

The public cloud main tree was compared by Git blob hashes: **27 of its 30 component files are identical here**. Only `climate.py`, `profiles/thermostat.py`, and `switch.py` differ. In particular, this fork already includes main's auth/security handling; replacing it with main does not buy a newer auth implementation and loses its local additions. The supplied upstream patch includes the site-specific lock and absolute workstation paths; it is not a narrowly scoped, portable, ready-to-submit patch.

The other cloud forks surveyed do not establish a better maintained alternative: martiar-77 and repires default branches resolve to the same cloud main commit, while Paradox52525's default branch is older. Useful proposals are on feature branches/open PRs, including [#12](https://github.com/billda/ha-aprilaire-cloud/pull/12) for explicit unit evidence and [#14](https://github.com/billda/ha-aprilaire-cloud/pull/14) for operating-state variants. Neither is merged. This is a bounded ecosystem survey, not proof that no other project exists.

## Local versus cloud multizone feasibility

**Established in the included local capture:** model 28 identification; `(2,1)` control; `(3,5)` returning one Heat Blast state byte; `(5,1)` returning eight status/value sensor pairs; `(5,2)` controlling sensors. LAT is the sixth pair, bytes **10/11** of the sensor data, not “byte 2” as one contribution-guide summary suggests. The shown LAT status/value is consistent with 43°C. The sample does not include a `(1,10)` response; the detailed zone-settings decoding therefore lacks a checked-in capture fixture. Reading Heat Blast state is evidenced; successful Heat Blast writes and their HVAC effect are not proved by a read response alone.

**Good evidence, limited conclusion:** the documentation reports that extra selector bytes produce NACK 0x22, revisions 1/2 return the same primary-zone data, and an attribute sweep did not find secondary-zone telemetry. This supports “no demonstrated secondary-zone API on the tested 6003 firmware/automation endpoint.” A length rejection proves that a particular request format is invalid. It does not prove every firmware, undocumented attribute, other protocol, or RS-485 bus route is impossible. No inspected local client implements a zone address selector.

**Practical recommendation:** use local TCP for the networked primary zone and shared equipment data. Keep cloud for PZ1/SZ2/SZ3 where explicitly reported in settings/status. The cloud profile already discovers and routes these keys; this fork mainly relaxes write gating. PR #13 reports one 6003 two-zone Celsius installation successfully writing SZ2; it does not establish all the newly enabled model families, SZ3 writes, every mode, or Fahrenheit display behavior. Add sanitized fixtures and an explicit model/firmware capability matrix before claiming full 6000/6002/6003/8840-family support.

A passive RS-485 research project or another firmware interface might eventually provide fully local zoning, but there is no validated implementation here to recommend. Treat that as separate research. Do not schedule more active attribute scans as a routine integration feature. HA documents that these thermostats permit only one automation connection and can become unresponsive with concurrent clients: [official integration documentation](https://www.home-assistant.io/integrations/aprilaire/). The contribution guide also dates core introduction incorrectly: official documentation says **2024.3**, not 2023.3.

## Ranked findings

### 1. P1 — Reconnect initialization is disabled after first setup (confirmed)

**Evidence:** `custom_components/aprilaire/coordinator.py:211–219` replaces `_AprilaireClientProtocol._update_status` with a no-op. Its replacement initialization is only in `wait_for_ready`, lines 453–529. The pinned library calls `_update_status` on **each** `connection_made` ([0.9.1 client.py](https://github.com/chamberlain2007/pyaprilaire/blob/0.9.1/pyaprilaire/client.py#L84)). The fork requests an hourly reconnect (`coordinator.py:21`). Its minute poll (349–363) reads full sensors, Heat Blast and equipment status, but neither control settings nor COS subscriptions.

**Impact:** the first setup can work while a later reconnect fails to resubscribe/reconcile setpoints, modes, IAQ availability and scheduling. Whether the device retains subscriptions across connections needs hardware confirmation; the missing initialization path is definite.

**Fix:** make paced initialization a per-connection client lifecycle operation; refresh capabilities/settings and configure supported COS after every reconnect. Keep the minute poll only for values lacking reliable push.

**Verify:** offline fake transport: first connection, disconnect, second connection; assert the second receives the same essential initialization/subscription sequence and settings recover without an entry reload.

### 2. P1 — The replacement parser still mishandles stream boundaries and NACKs (confirmed)

**Evidence:** `aprilaire/coordinator.py:102–110` breaks on an incomplete frame without retaining it. The pinned `client.py:107–111` passes each TCP callback directly to `Packet.parse`; it has no receive buffer. At coordinator lines 112–127, the NACK status byte is converted to `FunctionalDomain` before testing NACK. Status 0x20/0x21/0x22 is not a valid domain and is silently discarded. Accepted NACKs bypass CRC verification. MAC/TEXT field reads at 183–201 have no per-field bounds check; a short declared payload can make them read beyond its boundary. A normal two-byte-body NACK is seven bytes long, so merely reading index 6 is not itself an out-of-bounds error—it reads the CRC byte as if it were an attribute.

**Impact:** valid split responses disappear, unsupported reads wait for timeouts instead of reporting a correlated NACK, malformed fields can raise out of the callback. This is a reliability finding; no remote code-execution or thermostat-safety exploit was demonstrated.

**Fix:** adopt the upstream buffered/parser implementation through a compatible library release or carefully tested backport. Preserve frame sequence and NACK status, validate CRC, enforce field boundaries, and cap receive buffers.

**Verify:** captured frames split at every byte boundary, multiple concatenated frames, incomplete trailing frames, NACK 0x22, bad CRC, short MAC/TEXT payloads and unknown attributes. No network/device required.

### 3. P1 — Cloud write gating now accepts unverified device contracts (confirmed broadening; device harm unverified)

**Evidence:** `aprilaire_cloud/profiles/thermostat.py:390–406` requires only numeric heat/cool on exposed zones. Lines 723–726 accept `bool(zones)` as an alternative to a known model. Lines 756–764 enable setpoints without checking a model-specific wire unit, grid, limits or supported mode. Lines 427–435 default unknown thermostats to Celsius. `_requested_setpoint` at 929–940 applies 0.5°C to every supported thermostat, including the previously whole-Fahrenheit 8920W contract.

**Impact:** the allowlist is not the actual write boundary. A new/unknown thermostat with familiar-shaped JSON can acquire controls with assumed units and constraints. Existing Fahrenheit-grid devices can receive values off their established grid: 70°F converts to about 21.11°C, then rounds to 21.0°C. Device rounding/rejection and confirmation failures need validation.

**Fix:** retain explicit per-model/firmware contracts with native wire unit, display preference, grid, limits and available zone commands; start with the captured 6003 contract. Keep unknown contracts read-only. Do not label a capability “live confirmed” solely because keys exist.

**Verify:** fixture matrix for 6003 C, 8920W with F display/C wire, missing units, unknown model, incomplete zone, read-only account and range boundaries. Confirm encoding/echo tolerances separately from HA display conversion.

### 4. P1 — Deadband bypass follows argument shape, not operating mode (confirmed)

**Evidence:** `profiles/thermostat.py:917–926` checks the 3°F separation only if the caller supplied both fields; the function never checks mode. It always sends both values, filling the omitted field from current settings (881–905).

**Impact:** an auto-mode request supplying just `target_temp_low` can construct an invalid heat/cool pair without the deadband check. A single-mode request supplying both fields can still be rejected unnecessarily. The reported single-mode problem is real evidence for a mode-specific fix, not for removing validation based on kwargs. Independently clamping both endpoints to 23°C can also collapse an auto pair into zero deadband.

**Fix:** validate the final pair against the effective mode and captured model deadband; preserve the unused endpoint only where the device contract permits it. Plan explicit behavior when a lock interval cannot accommodate the required separation. Do not invent a hardware deadband from rounded whole-Fahrenheit subtraction without device evidence.

**Verify:** heat-only/cool-only with crossed inactive setpoints; auto with one endpoint supplied; mode changes into auto; equal endpoints; pair clamping at both lock bounds; device-specific deadbands.

### 5. P1 — The range lock is account-wide, default-on and implemented in an entity callback (confirmed)

**Evidence:** `aprilaire_cloud/switch.py:33–34,75–87,102–129` stores one `coordinator.sz2_temp_lock_enabled` boolean for all devices and defaults it to true. Multiple switches restore into that same variable. `climate.py:206–210,403–430` automatically writes from every relevant entity update, without a pending-task key, availability/access guard, retry cooldown or exception wrapper. The switch's enable path clamps inactive endpoints too; the climate callback only clamps endpoints active in the current mode. There is no enforcement implementation in `coordinator.py`, despite the docs' claim.

**Impact:** turning off one device's switch affects all SZ2 zones on the account. Startup can enforce before a saved off state restores. Failed writes can clear optimistic state, publish another out-of-range snapshot and schedule another attempt; exact frequency depends on errors/events. Tasks can outlive entity removal and disabled climate entities do not run this policy. Read-only accounts can still get the switch and attempted writes. The lock cannot enforce during an HA/cloud/network outage and is not an access-control boundary on the physical thermostat.

**Fix:** make this an opt-in, configurable per-device/per-zone policy restored before enforcement starts. Own one coalesced task per zone in the coordinator, cancel it on unload/disable, respect availability/manage access, apply mode/deadband-aware clamping and back off after failures. Expose failure state. Avoid site-specific “Basement” names in shared code.

**Verify:** two devices with independent locks, startup with restored off, 429/401/network failure, rapidly repeated snapshots, disabled/removed climate entity, unload during write, and auto-mode bounds. Test policy behavior without sending a real command.

### 6. P2 — IP rediscovery is unreachable and its query is invalid (confirmed)

**Evidence:** `aprilaire/coordinator.py:411–413` treats any non-None `client.protocol` as connected. In pinned [socket_client.py](https://github.com/chamberlain2007/pyaprilaire/blob/0.9.1/pyaprilaire/socket_client.py#L86), the protocol is created before connecting and is retained after failure/disconnect. Even if reached, lines 382–386 send seven bytes with a zero body length and no CRC, rather than a serialized read request. The implementation assumes an IPv4 /24 and probes up to 64 hosts concurrently.

**Impact:** advertised DHCP recovery does not work and a repaired reachability check would enable unintended subnet probing with malformed requests.

**Fix:** prefer stable hostname/DHCP reservation and explicit reconfiguration. If rediscovery is retained, make it opt-in and network-aware, use actual connection state, valid serialized frames, full-frame reading, CRC and MAC verification, and conservative connection limits.

**Verify:** fake disconnected client with a retained protocol, synthetic subnet/hostname input and in-memory fragmented ID replies; assert outgoing bytes decode as a valid `(8,2)` request. Do not verify by scanning the real LAN.

### 7. P2 — Local availability is cached once and can remain true while disconnected (confirmed)

**Evidence:** `aprilaire/entity.py:31–46` calls `_update_available` only in the constructor. The inherited HA `BaseCoordinatorEntity._handle_coordinator_update` only writes HA state; it does not call this helper. `aprilaire/sensor.py:273–283` explicitly returns true for sensors without a status gate, including fan status.

**Impact:** stale telemetry and unusable controls can continue to look online. Reconnecting is also treated as connected in the helper.

**Fix:** derive availability from current connection state on every read/update, distinguish reconnecting from connected, and combine transport availability with each sensor's own status.

**Verify:** publish connected → disconnected → reconnecting → connected state without rebuilding entities; assert availability changes while last measured values remain distinguishable from fresh data.

### 8. P2 — Local sensor fallback can hide faults and never revert (confirmed)

**Evidence:** `aprilaire/coordinator.py:259–274` substitutes built-in readings whenever controlling status is nonzero/missing, without checking built-in status. `async_set_updated_data` merges into previously normalized `self.data` (303–309), which overwrote the original invalid controlling status with zero.

**Impact:** a faulty/not-installed built-in reading can be presented as valid; after substitution, later built-in-only updates may stop updating the controlling value because the synthetic status is now zero. Missing versus stale versus faulty information is lost.

**Fix:** keep raw readings/status separately, derive fallback each time using valid/fresh source status, scope it to observed 6003 behavior and expose the source used. Do not rewrite device-reported validity globally for all models.

**Verify:** invalid controlling + valid built-in; invalid built-in; repeated built-in updates; restored controlling sensor; other thermostat models.

### 9. P2 — Task shutdown and failure cleanup need lifecycle fixes (confirmed gaps; leakage timing needs validation)

**Evidence:** local setup starts listeners/tasks before registering cleanup; a MAC mismatch at `aprilaire/__init__.py:34–35` raises before the unload hook at 38. `coordinator.stop_listen` cancels its own tasks without awaiting them. Pinned 0.9.1 creates protocol queue/reconnect tasks without lifecycle ownership. Cloud `coordinator.py:262–291` overrides `DataUpdateCoordinator.async_shutdown` but never calls `await super().async_shutdown()`, omitting HA's refresh/debouncer/shutdown-flag cleanup. HA registers this overridden method as the config-entry unload callback, so it is incorrect to claim there is no automatic cloud cleanup at all.

**Impact:** failed local setup or reload can leave reconnect work running; cloud teardown omits base-class protections against scheduled refreshes. The new lock tasks are also not in the coordinator's tracked reconciliation task set.

**Fix:** register cleanup immediately after creating resources, use try/finally for local setup failure, await owned task cancellation, call the cloud base shutdown, and avoid copying lifecycle logic already corrected upstream.

**Verify:** wrong-MAC setup, connection failure, setup cancellation, repeated reload, pending refresh/debounce at unload and a queued lock command; assert no residual tasks or connections using fake transports.

### 10. P2 — Operating-state variants and feature descriptions are incomplete (confirmed)

**Evidence:** cloud `profiles/thermostat.py:97–98,463–495` recognizes stage1 but not stage2–4 or split-field `cool`/`heat` variants. With `coolingStatus='stage2'`, no aggregate fallback and fan false, it returns unknown; with fan true it reports fan instead of cooling. [Issue #8](https://github.com/billda/ha-aprilaire-cloud/issues/8) reports the symptom and [PR #14](https://github.com/billda/ha-aprilaire-cloud/pull/14) proposes an unmerged fix. Local `aprilaire/__init__.py:12–18` has no FAN platform and there is no `fan.py`, despite repeated README claims. The fan-mode select and LAT sensor **do exist** (`select.py:177–212`, `sensor.py:171–179`). Heat Blast is created unconditionally (`switch.py:15–25`) rather than gated on observed availability/model.

**Impact:** misleading HVAC action; documentation promises an entity that will never be created; other models get controls that may NACK. Fan mode is a request, while fan status is equipment operation; Auto/OFF does not guarantee the blower is stopped when IAQ or other zones call for it.

**Fix:** add captured operating-state variants and precedence tests; correct the fan documentation or implement a deliberately scoped fan entity; gate Heat Blast. Preserve separate requested mode and actual equipment status.

**Verify:** split/aggregate stage states, active IAQ with HVAC off, simultaneous status fields, unsupported Heat Blast and missing feature evidence.

## Units, authentication, security and maintainability: additional conclusions

**No blanket Celsius/Fahrenheit lock bug was established.** Known cloud model payloads normalize to native Celsius (`thermostat.py:427–435`), and HA converts service/display values. Constants 18/23 are therefore appropriate for that confirmed C wire contract. Unknown-model units remain a problem under finding 3. HA **2026.11.1 passes `target_temperature_step` through unchanged** in its climate entity capabilities, so following HA display units is not itself a current compatibility defect. [HA PR #190438](https://github.com/home-assistant/core/pull/190438), which would change that convention, is closed **without merging**. A future API migration needs a native/display unit test matrix; do not apply that PR's assumption prematurely. Profile step metadata is still 5/9°C while the encoder now rounds to 0.5°C, an internal contract inconsistency to resolve alongside finding 3.

**Frame pacing/concurrency:** `aprilaire/coordinator.py:77–92` puts a 0.30-second delay between writes from one protocol queue. This is a useful mitigation, but no included trace establishes 0.30 seconds as a universal minimum or proves physical RS-485 collisions were the cause; gateway buffering/processing limits are another explanation. The patch changes private classes and global packet mappings for every thermostat, including 8800 devices. It does not serialize a complete write/readback transaction across callers or establish command acknowledgement. Its pinned library starts a new unowned queue task for each connection; old loops can remain alive after their transport disappears. Prefer one lifecycle-owned sender per connection, model-specific pacing, bounded queues and sequence-correlated replies. Verify byte timestamps, interleaved producers and reconnect task counts with fake transports before making throughput claims. Do not remove pacing merely because the wire baud rate alone suggests shorter frames should fit.

**Cloud auth/error handling is substantially better than a simplistic REST client.** It serializes auth with an asyncio lock, runs Cognito blocking operations in an executor, refreshes then falls back to full login, distinguishes invalid credentials from transient/protocol failure, retries HTTP 401 once and bounds 429 retry delays. TLS endpoints are used. REST hydration is limited to four parallel requests per refresh, with 15-minute safety/2-minute fallback defaults. Per-device command locks prevent simultaneous PATCHes within this integration. WebSockets have application pings, pong timeout, resubscription and exponential reconnect delay. Preserve these features instead of rewriting around a smaller library.

**Specific cloud risks needing fixtures:** a ping task exception during token renewal/send is not directly supervised by the receive loop (`vendor/websocket.py:261–274,294–314`); with receive timeout disabled after initial sync, a failure could leave a stale connection until the server closes it. Auth-invalid failures in the WebSocket loop are caught generically and retried; REST refresh is the route that raises HA reauth. `mismatch_is_rejection=False` for every thermostat command (`thermostat.py:1031–1033`) plus a successful HTTP PATCH can return success after bounded deferred checks even when the device never applies the setting; a later warning is not a confirmation. These are reasons to test task failure and expose accepted/pending/confirmed/rejected status, not evidence of a breached account.

**Privacy finding:** the supposedly sanitized `tools/aprilaire_6003_probe_sample.json:43–55` still contains a complete MAC in hex and decimal bytes; the capture also encodes location and contractor details. `docs/PROTOCOL_6000_ZONING.md:97` includes contractor contact details in plaintext. Use synthetic captures that replace identifiers consistently in every representation, and recompute/check CRC metadata rather than pretending edited bytes are original captures. Remove site-specific location/contact details from shared documentation. No exposed password/token was identified in this bounded source review; this is not a forensic git-history secret scan. The integration's Cognito pool/client IDs are public client configuration, not account secrets.

Cloud diagnostics are a strength: export-scoped pseudonyms, payload shapes rather than raw values and token-free auth metadata (`diagnostics.py:30–52,179–220`). Passwords are still stored in HA config-entry data and tokens in memory; protect HA config/backups and keep raw auth exception chains out of public debug logs. No TLS verification bypass was found. Local automation TCP is a trusted-LAN control interface with CRC rather than cryptographic authentication; no evidence supports exposing it beyond that boundary. These are trust-model facts, not newly demonstrated vulnerabilities.

**Maintenance:** both integrations override standard domain names, so the custom local component shadows core updates. Cloud manifest still reports upstream `0.4.0b4` and upstream issue tracker despite modified behavior; use a distinguishable fork version/support URL. Preserve stable entity IDs (`device_id + zone key`) through changes; zone labels are not IDs. The cloud's explicit zone-key discovery, device/zone routing, settings-authoritative removal and dynamic entity reconciliation are useful existing design, not new features that need to be rebuilt. Use real hierarchy/configured zone names rather than assuming SZ2 means Basement. The current device-registry helper used locally remains present in HA 2026.11.1, although core has migrated to `async_get_or_create_from_info`; this is maintenance drift, not a confirmed startup incompatibility.

## Ranked roadmap and acceptance gates

1. **Stabilize control behavior:** restore per-connection initialization, replace/backport the parser correctly, constrain cloud write contracts and fix mode-aware deadband. Gate: offline frame/reconnect and command-encoding fixtures pass for existing 8920W and captured 6003 cases.
2. **Make the lock an explicit policy:** opt-in, per-device/per-zone, restored before enforcement, coordinator-owned, coalesced, mode/deadband-aware and rate-limited. Gate: startup-off, two-device, error/retry, disabled entity and unload scenarios pass.
3. **Repair lifecycle and observability:** base shutdown, local failure cleanup, real availability/fallback semantics; remove or redesign subnet scanning. Gate: repeated fake setup/unload leaves no tasks; disconnected devices are unavailable and faults stay visible.
4. **Reduce divergence:** rebase local contributions on `develop`, remove redundant model/length changes, contribute focused 6000 pacing/extended-ID/attribute support; keep HA platform additions separate. Rework cloud PR #13 as a captured 6003 contract, independent of the private range policy. Gate: upstream checks, sanitized fixtures, reviewable focused patches; eventual stable library + HA integration adoption permits removing overrides.
5. **Polish claims and packaging:** correct fan entity/core-introduction/protocol-byte claims, sanitize captures, distinguish fork version/support, add CI and supported-version matrix. Consider operating-state PR #14 with fixtures. Gate: documented entities match actual platform discovery and reported releases distinguish stable/candidate/open PRs.

No deployment or live acceptance run is part of this investigation. Later owner-authorized hardware validation should use one automation connection, verify model/firmware first, and separately confirm primary versus secondary zones, wire/display units, modes, fan semantics and device acknowledgement. Until then, the report supports improving the fork; it does not certify all newly enabled models or cloud-independent secondary-zone control.
