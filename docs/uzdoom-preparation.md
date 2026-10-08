# Approved UZDoom setup

Brutal Doom 64, Brutal Doom v21, Aliens: Eradication 2.0 and Ashes 2063:
Enriched 2.23 follow their guides' `org.zdoom.UZDoom` Flatpak, exact mod
load order and per-invocation read-only filesystem grant. No fallback engines,
forced video/input settings or persistent Flatpak overrides.

Detection prefers installed user scope, then default system scope. Both require
the official Flathub remote, x86_64 stable app/ref and exact installer evidence
for package digest, version and commit. Named system installations are not used.
Missing software gets current-user-only remote/install commands after separate
approval; no upgrades, system writes or elevation. Redetection after each command
and durable active-command/detection-pending records guard uncertain transactions.
Cancellation waits for an active transaction. Unknown installed commits remain
gated before game mutation; users never select an engine.

`check_host` checks metadata, application/runtime refs and installed runtime
without executing the engine. Exact installer evidence permits the independently
tested file lifecycle, not a claim that these checks prove Flatpak launch,
content access, graphics/audio, input or real save/relaunch. The legacy
`capabilities_checked` lifecycle field signifies the bound installer gate;
`host_checks` explicitly leaves graphical/CLI/gameplay checks false.
Readiness remains setup-required.

Brutal Doom bundles Doom Metal Volume 5 but loads it only with the guide's
explicit `--metal` option; the incompatible Complete voxel addon is excluded.
Aliens loads TC first, then campaign WAD; its player guide calls out required
mouse-look/jumping/crouching and recommended lighting without overwriting
shared preferences. Ashes uses the Doom II baseline and main Enriched PK3,
not the undocumented Freedoom patch or copied engine support files.
All three retain exact upstream payloads, original embedded credits and
guide-selected artwork converted to valid PNG, with explicit provenance gaps.

Validate with `MCL_DOOM_TESTS=1 python3 -m unittest tests.test_doom_installs`
and `python3 -m unittest tests.test_uzdoom`. Complete mod runner tests use isolated
HOME/source/configuration and synthetic IWAD, with mocked Flatpak transactions.
No actual engine invocation or fresh user Flatpak install is tested.
