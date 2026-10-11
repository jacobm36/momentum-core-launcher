# Shared engine fallback design

Status: private integrated HOD2/Brutal Doom 0.3.0 candidate, October 10, 2026.
Debug-PC acceptance pending; no public launcher release.

## Decisions

The owner approved automatic reuse of tested existing installations first.
When none exists, offer a separately approved Momentum-managed engine without
changing existing engines. Share managed engine files between games that use
the same tested build; keep each fallback game's settings and saves separate.
Settings/save migration is a later explicit action, never an implicit copy.

This design extends [shared selection](../engines.py), not a universal package
manager. First providers: Flathub Flycast and UZDoom. The launcher stays private;
this design does not publish software or change the five-title store scope.

## User experience

1. Detect the preferred existing engine. If supported, reuse it unchanged.
2. If untested, inspect supported alternative locations using the adapter.
3. If an existing supported copy is found, reuse it unchanged.
4. Otherwise look for a complete, verified managed slot for a supported build.
5. If no usable slot exists, offer **Prepare a tested engine for this game**.
   Explain the download/storage estimate, chosen version and separate profile.
   Existing software is untested, not necessarily broken.
6. Review and approve engine preparation. No game files are installed yet.
7. Verify the completed slot and required capabilities, then present a separate
   game installation plan with the selected engine identity and state location.
8. Install only after game approval. Confirm gameplay on the target system.

Cancel, skip or a failed preparation must not choose another engine silently.
No supported package evidence means no fallback offer. Missing host prerequisites
still show manual system commands; there is no automatic administrator access.

Existing game receipts remain bound to their recorded location and engine.
Discovery of a newer supported engine must not switch an installed game's
wrapper. Switching engine or profile requires an explicit repair/migration plan.

## Provider-independent responsibilities

Extend the existing adapter registry and selection layer rather than create a
second registry or duplicate compatibility evidence.

| Responsibility | Owner |
|---|---|
| Supported package/build identities and default preparation build | Existing exact compatibility evidence |
| Read-only preferred and alternative installation discovery | Engine adapter |
| Deterministic supported selection | Shared selector |
| Fallback support and provider-specific prerequisite checks | Engine adapter |
| Plan, approval, locks, transaction journal and recovery | Existing job infrastructure plus shared managed-slot helpers |
| Provider acquisition, complete-install verification and launch binding | Engine adapter |
| Game arguments, media and per-game state contract | Package |

Introduce optional adapter operations for managed-slot inspection, preparation
planning, acquisition/verification and launch-binding generation. Engines without
fallback support continue with reuse or explicit guidance; they do not receive
generic guessed commands. Keep facts serializable and plans deterministic.

A binding needs separate fields for:

- Engine identity: provider, app/ref, version, app commit or executable hash.
- Location identity: existing user/system path or Momentum-owned slot path.
- Ownership: borrowed versus managed.
- Launch-contract revision: the verified way to invoke this provider/build.
- State policy and per-game profile root.

Do not overload `scope` with a made-up Flatpak scope. A managed Flatpak slot is
still a user installation, with an explicit installation directory. Include that
directory and the launch-contract revision in `engines.identity()` and receipts
before managed slots become selectable.

The primary tested build remains the preparation default. Alternative builds
may be selected only according to explicit evidence and approved plans, not by
version sorting or "latest". If the chosen build is unavailable, fail visibly;
offering another supported build requires a new plan.

## Flatpak installation isolation

Use Flatpak's documented `FLATPAK_USER_DIR` with `--user`, not named system
installations, changed global environment, root permissions or altered app IDs.
Every inspection, remote operation, install, update, mask and launch of a managed
slot must carry the explicit directory in that child process's environment.
Normal user/system operations must not inherit it.

Proposed final layout:

```text
~/.local/share/momentum-core/software/flatpak/<app-id>/<arch>/<branch>/<app-commit>/
    flatpak/             # independent per-user installation
    slot.json            # verified immutable descriptor, published last

~/.local/share/momentum-core/state/<package-id>/<profile-id>/
    home/
    config/
    data/
    cache/
    state/
```

Use full commit identities, not version strings. A build-specific installation
slot permits two games requiring different commits of the same app to coexist.
Games using the same slot share its binaries and runtime storage.

Start with independent slots rather than an elaborate custom OSTree sharing
scheme. Separate slots can duplicate runtime/storage downloads. Display a
conservative space estimate and available space; do not promise cross-slot
deduplication. This is the deliberate cost of avoiding destructive version
switches. Optimize storage only after measuring real usage.

The final installation path must be its path during provisioning: Flatpak
deployments and exports may contain path-dependent details. Do not build at a
temporary path and assume renaming the whole installation is safe.

Create a slot under an ownership-checked lock, journal its creation and provision
at the final path. No selector may use it until its final descriptor is durably
published and reverified. An incomplete slot is recovery state, not an engine.
Reject symlinks, foreign ownership and unexpected pre-existing contents.

## Acquisition and verification

1. Check host Flatpak support, trusted source and exact package/build evidence.
2. Inspect an existing slot read-only. Unknown or partial contents are not
   overwritten, adopted or recursively removed automatically.
3. Acquire a per-slot lock and recheck facts after locking.
4. Journal slot creation before creating directories or starting a transaction.
5. Add only the trusted Flathub remote inside the managed slot.
6. Confirm that the approved commit is available and inspect its declared
   runtime. Source/signature verification remains Flatpak's responsibility;
   Momentum must not disable GPG verification.
7. Install and deploy the exact supported app commit. Existing preparation uses
   install followed by a pinned update; in a fresh managed slot this sequence is
   acceptable only while the slot is unpublished. Reconcile actual metadata
   after every transaction.
8. Resolve the pinned app's runtime and normal related graphics extensions.
   Do not use `--no-related` or `--no-deps` to make installation look smaller.
   Provisioning an older app after an initial current install must ensure its
   own runtime is present, not merely the current app's runtime.
9. Verify app identity, version, commit, architecture, branch, origin, declared
   command, runtime availability and complete deployment. Record resolved
   runtime/extension identities and scope.
10. Verify the provider's managed launch/state contract. Metadata alone is not
    graphics, input or gameplay evidence.
11. Prevent automatic app updates within the managed slot using an app-specific
    Flatpak mask after provisioning. Verify the mask. Never mask or pin the
    user's normal installations.
12. Publish a durable descriptor last. Then expose the slot to selection and
    separately review game installation.

App commit pinning does not prove runtime/graphics-extension identity or
compatibility forever. Record the resolved dependency graph and validate the
whole launch contract. Decide runtime/extension update policy from real probes
before implementing it; do not silently freeze obsolete security fixes or
silently update a previously certified graph. New approved graphs require
revalidation and an explicit maintenance plan.

Do not rely on `flatpak run --commit` alone: it selects an already available
commit, does not acquire its dependencies or isolate the app's writable profile.

## State and launch isolation

Separate installation storage does **not** by itself isolate settings.
Flatpak normally rewrites XDG variables to `~/.var/app/<app-id>/...`.

Provide a versioned provider launch helper that binds the exact managed slot,
verifies its descriptor, prepares absent per-game state directories safely and
launches the expected app command with the package's normal flags.

The helper must set the required HOME/XDG state paths inside the sandbox at the
point the engine is executed; host-side XDG values alone are insufficient.
The exact profile mapping and minimal filesystem permissions are a prototype
gate, not yet certified. Test HOME-dependent paths as well as XDG-dependent
paths, especially Flycast mappings/VMUs and UZDoom configuration/save discovery.

Grant read-only game media and writable access only to the intended profile and
required provider resources. Review broad manifest home permissions and
per-user overrides; do not assume an isolated directory is a security boundary.
Preserve display/audio/controller/portal functionality and validate the reduced
permissions before claiming isolation.

No shared profile/config copies, Flatpak global overrides or host environment
changes. Fresh state does not mean missing controls: package-required fullscreen,
input and mod flags remain part of the recipe. Where mappings require files,
ship only a separately verified minimal preset and seed it absent-only.
Do not import personal laptop configuration.

Use a stable profile identity tied to the game and state-contract revision, not
automatically to every engine commit. A new engine must not automatically use
existing save state if compatibility is unknown, or silently hide it behind an
empty new directory. Any incompatible state-contract change requires a reviewed
migration/new-profile choice with old state preserved.

## Package and receipt integration

Current HOD2 and Brutal Doom packages construct ordinary `flatpak run --user`
or `--system` commands and validate that exact form. They cannot use managed
slots unchanged. Add a new explicit launch-binding contract and immutable package
revisions; do not slip environment variables into old packages or broaden their
argv guards without tests.

The helper must be installed in stable retained support, not depend on the
location of a temporary launcher ZIP or the user's PATH. Bind helper bytes and
supported contract revision in the approved plan/receipt.

Receipts record managed slot identity, descriptor identity, launch binding and
profile root, alongside existing media/integration ownership. Approval checks
revalidate these fields and refuse changes after review. Preparation must not
change an already-approved game's engine selection.

For missing engines with no conflicting copy, retain the existing ordinary
user-scope preparation path in this first fallback iteration. The managed path
addresses an installed-but-untested conflict; do not silently migrate every
working installation to the new storage model.

## Failure, cancellation and lifecycle

- Reuse the existing dependency transaction journal and uncertainty checks.
  Generalize journal records to include slot/location identity so recovery
  cannot mistake a normal installation for a managed one.
- Lock provisioning/maintenance per slot across launcher instances, in addition
  to current job serialization. Never mutate a slot while a bound game runs.
- Cancellation waits for an active Flatpak transaction, then stops before the
  next operation. Do not kill package-manager processes to fake rollback.
- Preserve completed transactions and partial slots. After interruption,
  inspect exact paths/metadata and show a recovery plan before continuing.
- No success descriptor after a nonzero transaction exit, wrong build,
  missing runtime, failed verification or uncertain journal.
- If game installation fails, the verified slot remains available for retry.
- Game uninstall keeps shared engines and per-game state, as today.
- No automatic shared-engine cleanup in the first release. Later removal must
  prove no receipt references the slot, no game/process uses it and ownership is
  established, then request explicit approval. A receipt count alone is not
  proof that user-created external launchers no longer use it.
- Descriptor corruption, version drift or a missing deployment produces clear
  repair guidance, not automatic reinstall or an untested alternative launch.

## Validation gates and implementation order

| Gate | Required result |
|---|---|
| Directory isolation | All managed commands inspect/write only their selected installation; normal user/system commits/remotes unchanged |
| Exact acquisition | Approved app commit plus its actual runtime and graphics dependencies usable; missing historical commit fails clearly |
| Profile isolation | Config, saves, VMUs and caches stay under per-game roots across launch/exit/relaunch; normal profiles unchanged |
| Functional recipe | HOD2 fullscreen, Start, aim/fire/reload; UZDoom canonical mod order, fullscreen, controls/audio and save/relaunch |
| Shared reuse | Two games reuse one verified build slot; different app commits coexist without switching deployments |
| Consent binding | Changed slot/build/helper/profile/receipt after review invalidates approval |
| Recovery | Failures, cancellation, interruption, uncertain transactions, disk exhaustion and partial slots preserve evidence and existing installs |
| Lifecycle | Repeat/repair/remove/reinstall preserve saves and do not remove a shared engine |
| Regression | Existing user/system reuse and missing-engine approval paths remain working |

Implementation order:

1. A bounded real-Flatpak prototype proves complete provisioning at the final
   slot path and sandbox profile mapping for both engines. Do not publish it or
   run the existing personal game profiles. Produce concise test evidence.
2. Define the launch-binding schema from that evidence; implement shared slot
   paths/descriptors/locks/journaling and adapter-specific verification.
3. Add separate fallback review, preparation and diagnostics to the current job
   flow. Keep the feature disabled until package/helper contracts are validated.
4. Build new HOD2 and Brutal Doom package revisions and run the full gate matrix.
5. Deliver a complete private launcher candidate for target acceptance. Enable
   only the tested provider/build combinations; no generic compatibility ranges.

No additional user design decision is needed to start the bounded prototype.
If storage or profile tests require a materially different isolation strategy,
stop and present the measured trade-off before changing this design.

## Implemented prototype and measured results

The opt-in [provisioning/launch experiment](../tools/managed-flatpak-prototype.py)
and [real state checker](../tools/check-managed-flatpak-prototype.py) are separate
from production discovery, jobs, packages and candidate delivery. Their
`prototype-1` descriptors certify provisioning metadata only; production must
not adopt them as complete managed slots or approved game bindings.
See [scoped evidence](shared-engine-fallback-evidence.json).

Fresh final-path slots acquired the primary tested Flycast v2.7 and UZDoom
5.0.1 commits with their own runtime-25.08 deployments and ordinary related
graphics extensions. `/.flatpak-info` inside each sandbox confirmed that both
app and runtime paths came from that slot, not the default user/system storage.
The app masks were checked. No signature/dependency checks were disabled.

Two profiles per engine retained independent HOME/XDG sentinels across relaunch.
Reduced permissions denied writes to media and access to the other profile.
The real HOD2 recipe, changed only to windowed for this development check,
initialized OpenGL/HLE BIOS, created VMUs under each profile and retained idle
VMU bytes after exit/relaunch. UZDoom initialized Vulkan/audio, saved vanilla
Doom II separately in each profile, then discovered and loaded profile A's
save by name after restart without altering profile B. The canonical Brutal
Doom load order matched the original 5.0.1 content-init diagnostics and exit 57;
known voxel script diagnostics remain explicit, not a new gameplay pass.

Normal installation/ref/remotes and existing profile-file fingerprints matched
their pre-provisioning baseline. Original reference media/mod files were
hash-checked unchanged. Failed test windows/processes were closed; no test
engine remained running. Full resolved dependency commits and logs are retained
under the explicit experiment root.

Measured combined software storage was approximately 5.3 GiB on this host
(Flycast 3.2 GiB, UZDoom 2.2 GiB, rounded independently). Flycast's install-then-pin
sequence retained both initially acquired 26.08 and required 25.08 runtimes.
The prototype does not automatically remove either. This is actual host usage,
not a universal download estimate; graphics extensions vary by host.

Reproduce with a new, dedicated absolute experiment directory, never a normal
engine/game directory:

```bash
python3 tools/check-managed-flatpak-prototype.py \
  --root /absolute/path/to/new-experiment --record-baseline
python3 tools/managed-flatpak-prototype.py \
  --root /absolute/path/to/new-experiment --engine flycast --prepare
python3 tools/managed-flatpak-prototype.py \
  --root /absolute/path/to/new-experiment --engine uzdoom --prepare
python3 tools/check-managed-flatpak-prototype.py \
  --root /absolute/path/to/new-experiment \
  --flycast-media "/absolute/path/to/House of the Dead 2, The (USA)" \
  --doom-media /absolute/path/to/iwads
```

`--prepare` explicitly approves downloads only into the experiment root.
The real checker requires local reference media, X11, `wmctrl`, `xprop` and the
host X11/XTest libraries. It temporarily focuses only newly created matching
test windows to use UZDoom's console, then exits the engines. Normal-state
baselines cannot be silently overwritten. Partial slots fail visibly and are
retained for manual inspection; this experiment has no automatic recovery UI.
Game launches use `--die-with-parent`: terminating only `flatpak run` otherwise
can leave its sandbox/game alive. This is launch-process supervision, never a
reason to kill an active provisioning transaction. Window identity is checked
using observed WM_CLASS (Flycast uses `flycast`, not its Flatpak app ID).

The narrow integrated candidate now supplies the helper/binding schema, full
dependency-graph identity, retained support, approval/job/receipt wiring and
new HOD2/Brutal Doom 0.3.0 revisions. Exact final helper/package bytes passed
fresh real Flatpak acquisition and install/no-change-repeat; installed wrappers
and retained helper launch were checked independently of the launcher location.
Automated guards cover low disk, changed descriptors/profiles/helpers, partial
slots, failed transactions/inspection, cancellation boundaries and competing
slot locks. Eight exact runner checks cover ordinary primary/additional builds,
system reuse and missing-user preparation for the new package revisions.

Normal selection still reuses a tested existing copy. Only the new, exact-evidence
packages accept `momentum-flatpak-1`; historical packages cannot accidentally
receive managed bindings. When no supported existing copy is available, a fresh
installation offers the primary tested isolated build, then a separate game plan.
Existing receipts preserve their recorded binding. Engine/profile migration,
updates, automatic cleanup and storage deduplication are deliberately excluded.
Graph drift requires explicit repair guidance rather than launching unvalidated
dependencies. Partial/uncertain provisioning stops with journals retained;
automatic transaction recovery is not claimed.

For debug-PC acceptance, use `bash start-isolated-test.sh` from the extracted
private candidate. It creates a separate acceptance HOME beneath the real
user's Momentum data directory and enables the managed path for new candidate
installs even if an ordinary supported engine exists. Real-user engine
installations, game folders, receipts and browser profile remain untouched.
Use the same script for relaunch; do not install desktop shortcuts in test mode.
Normal startup does not force isolation.

Still required: debug-PC fullscreen/controls/gameplay/save acceptance and a
later explicit runtime maintenance policy. Idle VMU persistence is not a HOD2
in-game save test; vanilla Doom II save/load is not Brutal Doom save acceptance.
Superseded prototype/intermediate Flatpak downloads were removed after the final
real checks to recover local disk space; their reports, descriptors and journals
remain. Final validation slots are retained separately.

## Evidence and sources

Observed locally on Flatpak 1.14.6, October 10, 2026:

- The installed `flatpak(1)` manual documents `FLATPAK_USER_DIR` as the per-user
  installation location, defaulting to `$XDG_DATA_HOME/flatpak`.
- The installed `flatpak-run(1)` manual documents sandbox XDG rewriting and
  host-prefixed variables. Earlier isolated Flycast tests also required setting
  profile variables inside the sandbox.
- Read-only `flatpak info --user --show-commit` using only an explicit
  `FLATPAK_USER_DIR` selected the isolated Flycast `0f8d2124...` and UZDoom
  `6c574dec...` builds, while normal installation commits remained unchanged.
- Earlier Flycast runtime-26.08 provisioning without related graphics extensions
  failed GLX; ordinary related-extension installation enabled OpenGL/game boot.
- `flatpak mask`, `update --commit`, `run --commit` and separate directory
  selection are present. This is API feasibility evidence, not fallback gameplay
  or save-isolation certification.

Reference: [Flatpak command documentation](https://docs.flatpak.org/en/latest/flatpak-command-reference.html).
The installed manuals describe the actual host version used for these checks.
