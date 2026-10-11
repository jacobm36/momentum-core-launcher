# Historical acceptance notes

These notes describe earlier candidates, not the current store catalog or
instructions for new installations. They are retained for development context.
Exact package/build JSON evidence remains authoritative for installer gating.
For current use, see [the user guide](../USER-GUIDE.md).

## October 9 arcade and early priority candidates

The October 9 launcher release added exact-build runtime and recovery helpers
for SWTA 0.2.1 and L.A. Machineguns 0.2.2. Earlier acceptance bundles included
Episode Enyo 0.2.1 and HOD2 0.2.0. Brutal Doom 0.2.0 was initially not bundled
while content-distribution decisions were pending. These are historical
candidate identities, not recommendations to install withdrawn versions.

SWTA retains stock credit settings (3 for credit, 1 for Start); free play is a
manual cabinet setting. L.A. Machineguns 0.2.2 seeds only absent isolated NVRAM
with the clean calibration confirmed on the reference and debug laptops.
Existing NVRAM is preserved and may still require manual AIM SET.

Enyo's fullscreen startup does not copy the reference laptop's display
configuration or force its resolution. Later Enyo 0.3.0 obtains the mod directly
from its publisher rather than bundling it.

## October 10 shared-engine and import milestones

The r6 shared-engine candidate received owner-reported acceptance. HOD2 and
Brutal Doom 0.3.0 were subsequently published with separately approved isolated
Flatpak fallback support. Existing installations and profiles were not migrated.

Additional exact Flycast v2.7 runtime-26.08 and UZDoom 5.0.3 builds received
build-specific acquisition/lifecycle evidence, not a blanket version-range
exemption. Installer tests and windowed boot checks do not imply fullscreen,
input or gameplay acceptance for every package/build combination.

The r7 candidate added installed-game shortcut review/selection and preservation
of edited commands. This feature was pushed to the private canonical launcher.

## OpenBOR milestone

Marvel Infinity War 0.2.0 used the supplied pinned OpenBOR 6391 runtime and
absent-only configuration seed. Actual author download and isolated lifecycle
checks passed. The owner reported flawless r1 debug-PC setup and supplied a
gameplay screenshot; no individual target checklist was reported.

The r2 launcher fixed cover/video overlap without changing the game package.
The unchanged 0.2.0 package became the sixth published store title. The frontend
and acceptance bundles remained private.

## Evidence limits

Synthetic media tests prove installer behavior, not fresh-system graphics,
calibration, input or campaign completion. Native runtime provisioning and
real OpenBOR acquisition were checked in disposable homes. Some Flatpak tests
use command fixtures; their individual reports distinguish actual acquisition
from mocks. Preserve those distinctions instead of inferring broader acceptance.
