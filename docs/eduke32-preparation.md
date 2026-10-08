# Approved native EDuke32 preparation

Duke Nukem 3D follows the working guide's ordered upscale/voxel `-g` archives
and appended `-mh` definitions, with enabled local SC-55 autoload. The candidate's
`-usecwd` isolates state; existing root CFG/SAV/ESV files are imported unchanged,
and absent settings get starting presets rather than enforced preferences.
No fullscreen/input override or alternative engine.

Detection uses the guide's `~/Games/Duke-Nukem-3D/eduke32`,
`~/src/eduke32/eduke32`, then shared user-managed runtime storage. Executable
bytes remain unchanged. Exact installer evidence is bound to package digest and
native SHA-256; source revision or ELF header alone is not compatibility evidence.

Missing software has a separately approved pinned official source download,
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
