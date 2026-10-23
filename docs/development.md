# Launcher development and release guide

Commands below run from the source repository root. Developer tools and tests
are not included in runtime-only deliveries. For the product overview and
requirements, see [the README](../README.md); for current player instructions,
see [the user guide](../USER-GUIDE.md).

## Release consistency check

Run the read-only release checker from this repository:

```bash
python3 tools/check-release.py \
  ../momentum-packages/dist/star-wars-trilogy-arcade-0.2.1.zip \
  ../momentum-packages/dist/l-a-machineguns-0.2.2.zip \
  --launcher-archive /path/to/final-launcher.zip --public
```

It verifies final ZIP/source bytes and executable modes, immutable package tags
using the existing builder, package self-checks/tests, exact launcher evidence,
declared software, proposed catalog fields and checksum sidecars. `--public`
also anonymously downloads and verifies uploaded game assets; omit it before
upload. `--launcher-archive` checks the evidence in the actual launcher delivery
instead of only the working source. Override sibling paths with
`--package-repo` and `--distribution` when needed.

The final line is exactly `RELEASE CHECK: PASS` (exit 0) or
`RELEASE CHECK: FAIL` (exit 1). It never commits, uploads, updates the catalog,
changes evidence, or claims gameplay acceptance. Package tests run in temporary
copies with temporary home directories. Existing emulator/hardware support
still requires its own evidence. Publish only after human approval; verify
uploaded assets before promoting the catalog.

Time Crisis II uses the separate `momentum-mame-flatpak-1` contract. Release
checks bind its exact helper hash and package digest to MAME evidence, including
the pinned app and KDE runtime commits; older Flatpak contracts are unchanged.

## Private acceptance bundles

Build a complete local launcher with a selected set of exact-evidence candidates:

```bash
python3 tools/build-candidate.py /path/to/new-candidate.zip \
  --package quake-slave-zero-x \
  --package the-house-of-the-dead-2 \
  --package brutal-doom
```

The builder rejects missing exact installer evidence, duplicate selections and
existing output paths. It includes a testing guide and a package/build inventory,
but no personal library, original game media, journals or home-directory settings.
The default acceptance profile includes developer tests and tools. To ship only
the application and user references, without bundled game installers:

```bash
python3 tools/build-candidate.py /path/to/new-runtime.zip \
  --runtime-only --launcher-only
```

The runtime profile uses an explicit file inventory, retains every supported
engine adapter and required compatibility record, and omits developer tests,
tools, contributor instructions and historical acceptance notes. Game packages
can still be downloaded from the store or imported locally. To bundle an exact
installer, use `--package <id>` instead of `--launcher-only`.
See [repository and delivery contents](delivery-layout.md).
Neither build profile publishes the private frontend or changes the online store.

## Setup and safety

### Shared engine selection

The [Marvel Infinity War integration](openbor.md) reuses the supplied,
exact OpenBOR 6391 native runtime. It adds no general engine manager or automatic
controller mapping. Its author-hosted game download is separately approved;
the working configuration is seeded only when absent. The frontend remains private.

Engine discovery, package compatibility and software preparation are separate
responsibilities. `engines.py` selects from exact package-scoped supported builds;
adapters retain provider-specific identity, prerequisite and transaction checks.
For Flycast and UZDoom, the preferred user/default-system installation is reused
when tested. If an installed preferred build is untested, both default scopes are
inspected and a tested existing copy can be chosen without modifying either.
Untested builds are not labeled broken. Probe/identity errors remain explicit.

Selection details include the chosen identity, inspected candidates and supported
builds in setup and plan review. Scope is a reuse location, not a Flatpak version
compatibility requirement: existing user or default-system installations may be
reused; missing software is still prepared only in user scope after approval.
Changing the selected installation/build after plan review requires a new review.
Saved wrappers and receipts continue to record the chosen location.

To add another engine, register its adapter in `RUNTIME_RESOLVERS`, validate its
declared provider/source, and supply exact package/build evidence. Adapters expose
`detect()` (preferred installation), optional `discover()` (read-only alternative
facts), and their existing prerequisite/preparation hooks. `engines.select` owns
deterministic matching; adapters own safe provider-specific probing and commands.
Native providers must not inherit Flatpak's user/system scope exception.
Discovery is lazy to avoid extra probes on an already supported setup.

Existing-copy selection does not support named Flatpak installations, arbitrary
providers or version-range exemptions. Isolated known-working fallback is
separately gated by the exact package/helper contract below.
The [managed fallback implementation](shared-engine-fallback.md) uses
build-specific user-only Flatpak slots and separately approved per-game profiles,
gated by exact package/build evidence. Published HOD2/Brutal Doom 0.3.0 support the
explicit `momentum-flatpak-1` binding: reuse a tested existing copy first, otherwise
offer the primary tested isolated build after separate software approval.
The retained, hash-bound helper validates the app/dependency graph and per-game
profile on launch. Existing receipts never silently switch engine/profile.
There is no automatic update, migration, cleanup or deduplication.

For debug acceptance without disturbing existing installations, close the old
launcher and run `bash start-isolated-test.sh` in a new extracted private candidate.
It uses a separate acceptance HOME under the real user's
`~/.local/share/momentum-core/isolated-acceptance-home-v1`, forces the managed path
only for new supported candidate installations, and retains its receipts/state
for relaunch. Supply original media by absolute path and keep the default test
destination. Do not run shortcut installation in this mode. Normal
`start-candidate.sh` retains ordinary reuse behavior. Partial/uncertain slots
stop with their journals retained; there is no automatic destructive recovery.

See the [user guide](../USER-GUIDE.md#notifications-installs-and-backups) for folder
selection, separate software/game approvals, local import, cancellation and recovery.
**Add game → Add a game manually** keeps the original library editor.

Only exact package/runtime evidence enables installation; unknown builds remain gated.
Installer checks are not gameplay certification. All new installations report **setup required**.
Technical evidence: [HOD2](hod2-target-evidence.json),
[arcade](arcade-installer-evidence.json), [Episode Enyo](quake-installer-evidence.json),
[UZDoom games](doom-installer-evidence.json), [Duke Nukem 3D](duke-installer-evidence.json),
[QBJ3](qbj3-installer-evidence.json) and [OpenBOR](openbor-installer-evidence.json).
[UZDoom preparation](uzdoom-preparation.md) explains its scope and limits.
[EDuke32 preparation](eduke32-preparation.md) covers Duke's native engine
reuse/build, complete enhancements and isolated state.
[Ironwail/QBJ3 preparation](ironwail-preparation.md) covers separately approved
engine/source downloads, full inventory checks and retained shared caches.

No automatic upgrades, elevation or RetroArch. Originals, personal settings and saves
are preserved; ambiguous interrupted changes require reconciliation.
Package scripts run as your user, not in a sandbox: trust the publisher before approval.
Catalog downloads are bounded to 512 MiB and ten minutes, with exact size/hash checks.
The distinct trusted QBJ3 source preparer allows only its exact 2.7 GB pinned
archive, with a one-hour download deadline and no partial-download resume.
The server binds to `127.0.0.1`, validates the Host header and requires a session token for changes.

## Validation

Default tests: `python3 -m unittest discover -s tests`.
Package check without executing scripts: `python3 packages.py check <folder-or-zip>`.

| Optional check | Command |
|---|---|
| Headless package UI | `MCL_BROWSER_TESTS=1 python3 -m unittest tests.test_package_ui_browser` |
| Actual public downloads and GUI installs | `MCL_CATALOG_TESTS=1 python3 -m unittest tests.test_catalog_live_browser` |
| Arcade runner/lifecycle | `MCL_ARCADE_TESTS=1 python3 -m unittest tests.test_arcade_installs` |
| Episode Enyo runner/lifecycle | `MCL_QUAKE_TESTS=1 python3 -m unittest tests.test_quake_installs` |
| Four UZDoom games' runner/lifecycle | `MCL_DOOM_TESTS=1 python3 -m unittest tests.test_doom_installs` |
| Duke Nukem 3D runner/lifecycle | `MCL_DUKE_TESTS=1 python3 -m unittest tests.test_duke_installs` |
| QBJ3 full source and real preparation/lifecycle | `MCL_QBJ3_TESTS=1 python3 -m unittest tests.test_qbj3_installs` |
| HOD2 runner/lifecycle | `MCL_HOD_PACKAGE=/absolute/HOD-package.zip python3 -m unittest tests.test_hod_receipts` |
| OpenBOR exact acquisition/lifecycle | `MCL_OPENBOR_TESTS=1 python3 -m unittest tests.test_openbor_installs` |

Browser checks need Chrome/Chromium; public checks need internet access.
Runner checks need built packages in the sibling package repository and temporary storage.
Native software is copied from exact pinned installations or downloaded from official releases.
Flatpak is mocked; game media is synthetic and homes/settings are isolated.
QBJ3 checks use the full real mod and real pinned source/engine downloads;
only its commercial base PAK fixtures are synthetic. Run the large cases
sequentially with at least 17 GiB free.
These tests never launch games or engines and do not modify working installations.
The OpenBOR integration test uses the actual pinned author download (about 503 MiB)
unless `MCL_OPENBOR_SOURCE` points to an offline folder with the exact PAK. It
checks separate approvals, state preservation, repair and reinstall in an isolated
HOME. `MCL_PACKAGE_REPO` can locate the private built packages outside the sibling
checkout. Proposed evidence is tested only in memory with
`MCL_CANDIDATE_EVIDENCE=1`; a delivery requires a passing rerun against persisted
exact evidence without that flag.

## License

Launcher code is MIT; see [LICENSE](../LICENSE). Game content and package
components retain their own notices.
