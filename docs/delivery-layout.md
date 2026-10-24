# Repository contents and launcher deliveries

The repository contains the application **and** its development material.
File count in a checkout is not the application's installed footprint.

| Contents | Purpose | Runtime delivery |
|---|---|---|
| Root Python modules and launch/install scripts | Launcher, imports, package orchestration and runtime adapters | Included |
| `web/` | Browser interface and branding | Included |
| Runtime evidence and runtime index JSON in `docs/` | Exact package/build gating and OpenBOR file verification | Included; not optional |
| User guide, README and current supporting documentation/images | Instructions and references | Included |
| `docs/acceptance-history.md`, `docs/history/` | Historical developer context | Acceptance bundles only |
| `docs/development.md` | Current engineering reference; commands require the source checkout | Acceptance bundles only |
| `start-isolated-test.sh` | Developer acceptance launch with separate test state | Acceptance bundles only |
| `tests/` | Regression suites and fixtures | Acceptance bundles only |
| `tools/` | Builders, release checks and prototypes | Acceptance bundles only |
| `.github/`, Git history | Contributor instructions and development metadata | Not needed by the runtime |
| `cleanup_shortcuts.py` | Optional legacy shortcut maintenance | Repository/acceptance bundles only |
| `games.json`, play history, `media/`, logs, jobs and backups | Personal library and recovery data | Never copied from the developer checkout |
| Imported game packages | Separately selected installer snapshots | Optional in either delivery profile |

## Build profiles

The existing default remains a **private acceptance bundle**, including tests
and developer tools. No existing delivery or installed game is changed.

For a smaller **runtime-only** delivery, use the same builder:

```bash
python3 tools/build-candidate.py /path/to/new-runtime.zip \
  --runtime-only --launcher-only
```

This ships the explicit allowlist in `tools/runtime-files.json`, without test
suites, build tools or contributor instructions, and bundles no games. Store
downloads, local package import, installed-game import, all runtime adapters and
exact compatibility evidence remain available.

Runtime deliveries include player-facing `START-HERE.txt` instructions and use
`runtime-delivery` metadata rather than private-acceptance labels. This describes
the archive's contents, not publication approval or completed release testing.
Use `start-candidate.sh` for a windowed first launch or `launch.sh` for the normal
fullscreen launch. Development-only isolated acceptance launch stays in source.
Existing data locations and runtime/helper bindings are unchanged.

To include a particular installer, replace `--launcher-only` with a selection:

```bash
python3 tools/build-candidate.py /path/to/new-runtime-with-game.zip \
  --runtime-only --package marvel-infinity-war
```

Game installer snapshots may contain their own tests/notices/support; they are
not stripped or rewritten. Their bytes and digest must remain exact.

Both profiles include `candidate-build.json` with a `delivery_profile`, source
revision, hashes of every shipped launcher file and selected package identities.
The builder refuses to overwrite an existing output. Neither profile publishes
anything, changes desktop shortcuts or copies personal settings.

Run the repository tests before producing a runtime-only delivery, then verify
its extracted imports, startup/API and evidence. A runtime-only ZIP intentionally
does not contain the test runner or builder; retain the repository for development.

## Cleanup boundaries

Do not delete tests or combine modules just to reduce file count. Do not treat
library artwork, imported packages, installation journals or backups as disposable
build files. Runtime-only delivery is an inventory choice, not a cleanup operation
on the working checkout or the user's home.
