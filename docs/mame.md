# Time Crisis II MAME integration

Time Crisis II adds one game-specific MAME integration, not a generic
arcade manager. Public package 0.1.1 keeps the accepted 0.1.0 candidate's runtime,
controls and seed, with public metadata/documentation corrected.
Use the matching current private launcher and the package store or ZIP import.
Restart an older running launcher first so it loads the new adapter and evidence.
Do not associate the candidate with the working manual library entry.

The package uses the owner's exact tested fullscreen/mouse/BGFX `default`
recipe and CFG/free-play NVRAM seed, explicitly approved for public inclusion
on October 22, 2026.
The original manual game, media, library tile and `~/.mame` state remain intact.
The candidate has a distinct name and package-ID destination.

## Runtime selection

`mame.py` reads both default Flatpak scopes and selects an evidence-backed
MAME 0.289 build. Matching system installations are reused read-only.
The exact app commit and KDE runtime commit are verified. Incompatible
installations are not upgraded, downgraded, reconfigured or removed.

When no compatible existing app is available, `mame_flatpak.py` offers a
separately approved build-specific isolated installation. It follows the
existing retained Flatpak helper's approval, durable journal, locking, graph
verification and immutable binding pattern. It pins both app and runtime
commits. No app/runtime download is initiated by ordinary detection.

The MAME helper uses its own `momentum-mame-flatpak-1` contract. It is a narrowly
scoped fork because published Flycast/UZDoom packages bind the original
`managed_flatpak.py` bytes by hash. That existing helper is unchanged.
No automatic cross-helper migration or engine/profile switching is introduced.

Partial slots and altered descriptors fail explicitly and retain journals.
Removal preserves the engine. Downloads require about 6 GiB free and their own
approval; a synthetic acquisition test does not establish network availability.

## State and launch

The retained package launcher binds the selected engine rather than choosing
user/system scope again on each launch. It checks the exact identity, resets
broad Flatpak filesystem access, maps only the game's media read-only and its
own writable profile, and sets HOME/XDG variables inside the sandbox.
MAME receives explicit CFG/NVRAM/save/output paths and an app-only INI search
path, so no personal MAME settings are imported implicitly.

Seed hashes are checked before seeding; absent-only hard-link publication never
replaces personal state. Repair and reinstall preserve settings/NVRAM.
The seed includes the owner's calibration, scores and bookkeeping, explicitly
approved for public inclusion. It is not a cleaned factory preset.

ROM audit runs during preflight and verification, without seed initialization.
The managed helper's audit path also avoids creating the game profile before
approval. Merged ROM archives may contain safe relative clone subdirectories.
Only `timecrs2.zip` is copied, never other games from the source directory.

## Evidence and checks

Exact installer evidence: [mame-installer-evidence.json](mame-installer-evidence.json).
The owner reported testing and accepting the package-installed 0.1.0 candidate
on October 22, 2026, separately from earlier manual setup acceptance. Public
0.1.1 retains that runtime and seed; no separate gameplay checklist is claimed.
New installations still require the player to confirm their own setup.
Final 0.1.1 existing-engine lifecycle and separately scoped synthetic
missing/incompatible-engine flows passed. No real network acquisition is claimed.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_mame.py'
python3 tools/check_mame_candidate.py --root /new/retained/validation-root \
    --archive ../momentum-packages/dist/time-crisis-ii-0.1.1.zip \
    --source /absolute/folder/containing/timecrs2.zip
```

The checker uses a new HOME, private catalog and temporary provisional evidence
for only the exact package digest under test. Production evidence checks are
not bypassed. Actual ROM audits run against the selected engine, but graphical
gameplay is never started by the checker. Its root contains a retained report,
jobs, receipt and installed candidate for inspection.

Use `--synthetic-managed missing` or `--synthetic-managed wrong` instead of
`--source` for bounded test-double acquisition/lifecycle checks, with no real
downloads or game execution. Normal engine mutation is forbidden by the fixture.
