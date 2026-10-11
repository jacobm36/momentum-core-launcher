# Shared engine fallback

HOD2 and Brutal Doom 0.3.0 support separately approved, build-specific managed
Flatpak fallback. Both packages are published and received owner-reported
debug-PC acceptance. The launcher remains private.

## Selection and approval

Momentum first reuses an exact supported existing engine, without changing its
location or profile. For Flycast and UZDoom, it checks supported user and
default-system installations. An untested engine is not labeled broken.

When an existing engine is incompatible and no tested existing copy is found,
setup offers a private tested engine. A complete verified managed slot can be
reused; otherwise the software plan prepares it after separate approval.
The game installation plan is reviewed afterward. Missing software without a
conflicting installation retains the ordinary approved user-scope preparation
path. Unsupported package/build evidence never enables fallback.

Existing installations, global Flatpak overrides and system remotes are not
modified. There are no automatic upgrades, downgrades, migrations or engine
switches for existing game receipts.

## Files and player state

Managed storage is build-specific:

```text
~/.local/share/momentum-core/software/flatpak/<app-id>/<arch>/<branch>/<app-commit>/
    flatpak/
    slot.json
```

Games using the same verified slot share engine files. Their fallback settings
and saves use separate profiles under
`~/.local/share/momentum-core/state/<package-id>/<profile-id>/`.
Existing personal profiles are not copied. Different slots can duplicate runtime
downloads; Momentum does not promise cross-slot storage deduplication.

The versioned `momentum-flatpak-1` helper is retained in stable support and bound
by hash to the approved plan/receipt. It verifies the slot descriptor,
app/dependency graph and per-game profile on launch, then sets the sandbox's
HOME/XDG state paths. Merely changing host XDG variables is not sufficient.
Isolation is for reproducible engine/player state, not a general security sandbox.

## Failure and recovery

Provisioning occurs at the final slot path under an ownership-checked lock, with
durable transaction intents. A descriptor is published only after verification.
Partial slots, altered files, uncertain transactions and unexpected ownership
stop with explicit guidance; they are not automatically overwritten or removed.

Cancellation waits for an active Flatpak transaction and stops between steps.
Closing the interface does not kill the transaction. Retain jobs and journals
for reconciliation. A verified engine remains if later game setup fails.
Game-only removal preserves the shared engine and player state.

## Testing and limits

Exact records live in
[fallback evidence](shared-engine-fallback-evidence.json) and the individual
package evidence. Installer/lifecycle tests do not certify every graphics driver,
controller or game campaign.

For isolated acceptance, extract a new launcher bundle, close the old server and
run `bash start-isolated-test.sh`. It uses a separate HOME under the real user's
`~/.local/share/momentum-core/isolated-acceptance-home-v1` and forces the managed
path only for new supported test installations. Use the same script for relaunch;
do not install desktop shortcuts in this mode.

Normal `start-candidate.sh` retains existing-engine reuse. See
[the user guide](../USER-GUIDE.md#notifications-installs-and-backups) for approvals
and recovery. Source-checkout tests use `tests/test_managed_installs.py` and
`tests/test_managed_flatpak.py`; opt-in real lifecycle checks are documented in
the repository README. No broader provider or automatic cleanup framework is
implemented.
