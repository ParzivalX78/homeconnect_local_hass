# Core submission plan

This is the plan for getting Home Connect Local into Home Assistant core. It has four phases: what has to be done in the library before the first PR, the initial submission itself, porting everything else afterwards, and what happens to this repository once everything is in core.

Nothing here is scheduled yet. The first phase is blocked on a library rewrite (see [the license blocker](#1-license-the-library-blocker)), so treat this as the order of work, not a timeline.

> [!NOTE]
> Home Assistant's own rules this plan follows: the [review process](https://developers.home-assistant.io/docs/review-process/), the [integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/) and the [documentation standards](https://developers.home-assistant.io/docs/documenting/standards/). Where this plan and those pages disagree, those pages win.

## Phase 1: before the submission (the library)

### 1. License the library (blocker)

Core only accepts dependencies with an [OSI-approved license](https://opensource.org/licenses). `home-disconnect` is a fork of chris-mc1's [homeconnect_websocket](https://github.com/chris-mc1/homeconnect_websocket), which has no license at all ([upstream issue #69](https://github.com/chris-mc1/homeconnect_websocket/issues/69), open and unanswered). Without a license that code is all rights reserved, and only its author can license it. About 90% of the library's source is still his code, so the fork can't add a license by itself.

The plan is **home-disconnect v2.0.0: a reimplementation that can carry a license** (MIT or Apache-2.0):

- Write new code from the protocol, not by editing or translating the upstream files. Protocol facts (message format, resources, the AES and TLS-PSK schemes, handshake order) aren't copyrightable; the upstream code and its protocol document are.
- [hcpy](https://github.com/osresearch/hcpy) is MIT and covers the crypto and websocket protocol, so it can be used with attribution. openHAB's Home Connect Direct binding is EPL-2.0: reference only, don't copy.
- Write a new test suite too (the current one is also mostly upstream code).
- Document the provenance in the library's repository: what came from hcpy, what from protocol observation and what was moved from this integration.
- Keep the public API close to 1.x so this integration's migration stays small.

If chris-mc1 licenses upstream before v2 lands, the rewrite becomes optional.

### 2. Move protocol logic into the library

Core requires code that talks to a device or service to live in the library, not the integration. v2.0.0 of both repositories moves these out of the integration:

| In the integration today | Moves to |
| --- | --- |
| Hand-built messages: start with Finish-in (`__init__.py`), `fan.py` and `light.py` writes | Library methods (start a program with options, batch value writes) |
| Program and option rules in `helpers.py`: locking, `ensure_writable`, full vs known option sets, unplugged probes | Library `select_program()` / `start_program()` that own these rules |
| `hc_cloud_api.py` and `hc_legacy_oauth.py` (account sign-in and profile fetch) | One library module, something like `home_disconnect.account` (drop the "legacy" name, it's the app's own sign-in) |
| Profile ZIP reading and writing (`config_flow.py`, `export_profile.py`, `hc_cloud_api.py`) | One library profile loader and writer (the simulator can use it too) |
| Clock sync timestamp format | Something like `appliance.set_datetime()` |

Entities, entity descriptions, the config flow UI, storage paths, the error decorator and translations stay in the integration.

The integration is MIT (© chris_mc1), so code moved from here into the library is licensed. Keep the MIT notice and credit him.

### 3. Library release pipeline

Before the first review, the library needs:

- A real CI/CD pipeline: lint, tests, type checking, and publishing to PyPI with [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) from tagged GitHub releases. Reviewers check this on new dependencies.
- The license file and PyPI license metadata.
- A stable (non-pre-release) version for core to pin.
- One dependency bot (keep Renovate, drop Dependabot).

## Phase 2: the initial submission

The first core PR is as small as core allows: **one platform (`sensor`), the config flow and nothing else.**

### Decisions to make first

| Decision | Recommendation | Why |
| --- | --- | --- |
| Setup path | Home Connect sign-in only; the profile ZIP upload stays custom-only | Keeps setup inside Home Assistant with no third-party desktop tool. Core `simplisafe` also signs in with its vendor app's client and a pasted redirect. |
| Initial platform | `sensor` | Read-only, so none of the program/option write rules have to be reviewed in the first PR. Status sensors (operation state, door, remaining time) exist on nearly every appliance type. |
| Domain | Keep `homeconnect_ws` if reviewers accept it, otherwise pick a new one early | Same domain means custom users can switch without re-adding appliances (see [Phase 4](#phase-4-after-everything-is-ported)). A new domain means everyone re-adds their appliances. `ws` is an implementation detail, so expect reviewers to question it. If it has to change, `home_connect_local` follows core's `powerfox` / `powerfox_local` naming ("Powerfox Cloud" and "Powerfox Local", grouped under one Powerfox brand). |
| Config entry version | Ship core with the same `VERSION` / `MINOR_VERSION` as the custom integration's latest release | Home Assistant won't load an entry whose version is newer than the integration's. |
| Brand | Add the domain to core's existing Bosch brand (`homeassistant/brands/bosch.json`) | Core lists `home_connect` under Bosch, next to `bosch_alarm` and `bosch_shc`, so the local integration belongs in the same brand. There's no Siemens, Thermador or other BSH brand file to add it to. |

### What's in it

- Config flow: the Home Connect sign-in, appliance selection and connection test. Keep the test-before-setup split for washers and dryers, which cut their WiFi when off (see the `quality_scale.yaml` comment).
- The coordinator and connection handling (push updates, heartbeat, reconnect with backoff).
- Zeroconf discovery (`_homeconnect._tcp.local.`). Each appliance is its own config entry, so a discovered appliance that's already set up is ignored. The cloud `home_connect` integration listens for the same service type (and for DHCP), so on a fresh install both integrations can show a discovered card for the same appliance. That's accepted in core: `powerfox` (cloud) and `powerfox_local` both discover the same poweropti devices with the same zeroconf matcher, and both mark `discovery` as done. It's still worth saying in the PR description. Removing discovery from the cloud integration is its code owners' decision, not part of this plan.
- `sensor` entities, without the diagnostic ones. The custom integration has 74 sensor descriptions, and 9 of them are diagnostic: WiFi signal strength, IPv4 and IPv6 address, water and energy forecast, started and completed program counts, the program end trigger and the dishwasher's machine care reminder. Leaving them out also leaves out the WiFi signal sensor, the only entity that polls (`/ni/info`), so the first PR is push-only.
  - That still leaves 65, spread over every appliance type. The plan is to accept that: entity descriptions are declarative data, so most of the review is the entity classes and the coordinator, not the list.
  - If reviewers do want it smaller, cut by file, not by appliance: keep only the 11 shared sensors in `common.py` (operation state, door, power state, active program, remaining, elapsed and estimated time, progress, start in, finish in, flex start). Every appliance type reports those, so no appliance loses support, it just gets fewer sensors at first. The appliance-specific sensors then come back one family per PR (cooking, dishcare, laundry, refrigeration, coffee makers). Cutting out whole appliance types isn't needed.
- Tests with full config flow coverage, and tests for the sensor platform.
- The quality scale as far as the initial PR allows. Everything the custom integration already meets stays `done`, except the three rules for features left out of the initial PR: `diagnostics`, `reauthentication-flow` and `reconfiguration-flow` are `todo`. `dynamic-devices` and `stale-devices` stay exempt (one appliance per config entry). Rules about actions (`action-setup`, `docs-actions`) become exempt while there are no integration actions, and the rest are checked against the `sensor` platform alone. Because `reauthentication-flow` is a Silver rule, the manifest still declares **Bronze** at first, even though nearly every Silver, Gold and Platinum rule is already done.
- The documentation PR on home-assistant.io, opened at the same time.

### What's left out on purpose

| Left out | Why |
| --- | --- |
| Every other platform | Initial submissions are one platform. |
| Diagnostics | Not needed for the platform to work. |
| Reauthentication and reconfiguration flows | Not needed for the platform to work. |
| Options flow (Full profile export) | Not needed for the platform to work. |
| The `start_program`, `set_start_in` and `set_finish_in` actions | No custom actions in an initial submission. |

### Things to strip from the core copy

- The dev-only "setup from diagnostics dump" path: `CONF_DEV_SETUP_FROM_DUMP`, `CONF_DEV_OVERRIDE_HOST`, `CONF_DEV_OVERRIDE_PSK`, `CONFIG_SCHEMA`, the `HCConfig` / `hass.data` wiring, `process_json_file`, the `setup_from_dump` branch and the placeholder-host fallback that only exists for dump entries.
- The profile ZIP upload step and the `file_upload` after-dependency (if the sign-in is the chosen setup path).
- Every translation file except English: core keeps `strings.json` and translations come from Lokalise. The German requirement in this repository doesn't carry over.
- Anything written defensively for states the data model already rules out. Reviewers ask "why can this be None?", and if the honest answer is "it can't", the code goes.

### Pre-flight

- Run the integration against core's dev branch with core's own linters and hassfest, not only this repository's CI.
- Check every pattern (config entry data keys, selectors, quality scale exemptions) against an existing core integration instead of guessing.
- Give the docs page its own pass against the documentation standards. The linters don't catch broken entity references or discouraged terms.

### Timing

- Base the PR on the latest core `dev` and keep it rebased. A rebase can break CI through dependency drift (ruff, mypy) even when this code didn't change; that's usually a quick mechanical fix.
- Reviewers don't review on weekends.
- New integrations effectively have to be merged before a release's b0 beta to ship in that release.

## Phase 3: porting the rest

After the initial PR is merged, everything else comes over as small follow-up PRs, one thing per PR. Each PR is tested on real appliances through a custom build of the core integration first.

Suggested order:

0. **The other BSH brands.** Core has 8 virtual integrations that point people searching for another BSH brand to the cloud `home_connect` integration: Balay, Constructa, Gaggenau, Neff, Pitsos, Profilo, Siemens and Thermador. Each is a manifest with `"integration_type": "virtual"` and `"supported_by": "home_connect"`, and `supported_by` takes a single domain, so they can't also point to this integration. Someone searching "Thermador" or "Siemens" would only find the cloud integration. Options, to settle with reviewers:
   - Turn each of them into a brand (`homeassistant/brands/siemens.json` and so on) that lists both `home_connect` and this integration, the same way `bosch.json` lists several. This is a change to how the cloud integration is presented, so its code owners should agree.
   - Leave them as they are and rely on the Bosch brand plus the docs mentioning every brand.

   This has to come after the initial PR is merged, because hassfest checks that referenced domains exist. It doesn't block anything else, so it can run in parallel with the platform PRs.
1. **Diagnostics** (the `diagnostics` Gold rule), together with or followed by the **diagnostic sensors** left out of the initial PR (and any disabled-by-default sensors if those were cut too).
2. **`binary_sensor`** (75 descriptions): door, remote start allowed, problem events.
3. **`select`** (91 descriptions): program selection and options, including locked (read-only) entities and filtering unavailable programs.
4. **`switch`** (83) and **`number`** (34): settings and options.
5. **`button`** (13): Start, Stop, Pause and the rest. After `select`, since starting needs a selected program.
6. **`light`** (14) and **`fan`** (2): hood lighting and venting.
7. **`update`** (3): software updates.
8. **Reconfiguration flow, then reauthentication flow last.** Reconfiguration covers what changes in normal use (the appliance's address, or a new profile after a firmware update adds options). Reauthentication is only needed when the local key changes, which only happens when the appliance is unpaired and paired again, so it's the least urgent. Reauthentication is also the only Silver rule left, so the manifest stays at Bronze until it lands and then goes straight to Platinum: diagnostics and reconfiguration are the only Gold rules left and will already be in, and the Platinum rules are already done.
9. **Start with delay:** replace the `start_program` / `set_start_in` / `set_finish_in` actions with entities if possible (for example a Start-in / Finish-in entity), since core prefers entities over integration actions. Keep an action only if an entity can't express it.
10. **Profile export**, if it's still wanted in core.

Features that are on the custom integration's own roadmap (for example the per-appliance option-value calibration from [discussion #104](https://github.com/vemboy200/homeconnect_local_hass/discussions/104), or a single summary problem entity) go into whichever side is current at the time. Where core's cloud `home_connect` integration has the same limitation, fixing it isn't a condition for the port.

While porting, the custom integration stays the place to try new things. Anything added here before it's ported gets ported in the same way.

## Phase 4: after everything is ported

- **Deprecate the custom integration.** Once core has feature parity, stop adding features here and put a notice at the top of the README pointing to the core integration.
- **Migration guide.** If the domain stayed `homeconnect_ws`, removing the custom integration from HACS and restarting keeps every config entry, device and entity, because the core integration reads the same entries and unique IDs. Document the exact steps and test them on a real install first. If the domain changed, the guide is "remove and re-add each appliance".
- **Issues and discussions.** Point new reports to the core issue tracker. Keep this repository's issues open until the existing ones are resolved or moved.
- **Docs.** The user-facing pages in `docs/integration/` move into the home-assistant.io integration page. Developer notes (`docs/development/`) stay here or move to the library.
- **The library** stays maintained as a standalone project, since core depends on it. It becomes the place for protocol work.
- **The simulator** stays a development tool. It isn't part of the core submission.
- **Archiving** this repository is optional. Keeping it around for pre-releases of new features is fine, as long as the README makes clear core is the main version.

### Relationship with the cloud integration

Home Connect Local and the cloud `home_connect` integration will coexist in core. Home Assistant doesn't remove an integration because a newer one does more; removals happen when a service or library stops working or nobody maintains it. The cloud integration is actively maintained and uses BSH's official API, so plan around both staying.

Each has reasons to pick it:

| Pick Home Connect Local for | Pick the cloud integration for |
| --- | --- |
| More entities than the official API exposes | Setup with the official sign-in, no local key involved |
| Faster responses (no round trip through BSH's servers) | Support from BSH: firmware updates won't break it, while the local protocol is reverse-engineered |
| Keeps working without internet and with the cloud connection turned off | Setups where Home Assistant can't reach the appliance at all, such as a firewall blocking the appliance's network or Home Assistant running at a different site. A missing mDNS route alone isn't one of them, since Home Connect Local can connect by IP address |

The docs for both integrations should explain this so people can choose.

## Open questions

- Does the core review accept BSH's app client for the account sign-in? There's precedent (`simplisafe`, `roborock`), but BSH deliberately restricts the scopes for local keys to its own client.
- Is `homeconnect_ws` acceptable as a core domain?
- How should the 8 BSH brand virtual integrations (Siemens, Thermador, Neff and so on) point to both integrations?
