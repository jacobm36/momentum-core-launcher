# Approved native EDuke32 preparation

Duke Nukem 3D follows the working guide's ordered upscale/voxel `-g` archives
and appended `-mh` definitions, with enabled local SC-55 autoload. The candidate's
`-usecwd` isolates state; existing root CFG/SAV/ESV files are imported unchanged,
and absent settings get starting presets rather than enforced preferences.
The 0.2.0 package requests fullscreen through its wrapper; supplied
arguments can override that preference. No resolution/input override or alternative engine.

Detection uses the guide's `~/Games/Duke-Nukem-3D/eduke32`,
`~/src/eduke32/eduke32`, then shared user-managed runtime storage. Executable
bytes remain unchanged. Exact installer evidence is bound to package digest and
native SHA-256; source revision or ELF header alone is not compatibility evidence.

The 0.2.0 package carries the exact working EDuke32 binary plus its
matching pinned official source archive. Missing software has a separately
approved copy into shared user-managed runtime storage, bound to the package
digest and exact binary/source hashes. No download, compiler or build
prerequisites are needed for this delivery; required host libraries still are.
The binary is inspected without execution before approval, then published
without replacing another engine. Runtime preparation and game installation
retain separate approvals. Source stays in retained package support; shared
runtime remains after game removal.

Legacy packages retain the separately approved pinned official source download,
bounded size/hash, safe tar extraction and `make -j2 eduke32`. No APT, elevation,
system writes or automatic upgrades. Required Ubuntu build prerequisites must
already be present. Active builds finish before acknowledging cancellation;
durable transaction records retain uncertainty and diagnostics after failures.
Publishing never replaces an existing executable. A newly compiled unknown hash
remains blocked before game writes until its installer evidence is established.

Host prerequisite checks read ELF/link metadata without engine invocation.
They do not test loader execution, OpenGL, audio, controls, loaded enhancements
or save/relaunch. The user confirms the source setup works; packaged gameplay
remains untested and readiness remains setup-required.

Tests: `python3 -m unittest tests.test_eduke32` and
`MCL_DUKE_TESTS=1 python3 -m unittest tests.test_duke_installs`.
Full-payload runner tests use synthetic GRP, isolated copied engine/home/settings.
They never run an actual engine or change the working installation.
The 0.2.0 package also reuses the owner's icon, portrait Grid and gameplay
screenshot. Retained screenshot URLs are served from launcher media, like other
package artwork, and later clears/edits are preserved. The owner reported that
the candidate looks amazing and approved publication. This does not establish
full campaign or individual save/input/audio checks. Public installation
requires launcher preview.2 or newer; preview.1 lacks bundled-engine support.
