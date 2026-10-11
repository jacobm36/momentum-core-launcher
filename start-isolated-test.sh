#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

TEST_HOME="$(python3 - <<'PY'
import os
from pathlib import Path
home = Path.home() / ".local/share/momentum-core/isolated-acceptance-home-v1"
for path in (home, *home.parents):
    if path.is_symlink():
        raise SystemExit("Isolated acceptance home contains a symlink; stop and inspect it.")
if home.exists() and (not home.is_dir() or home.stat().st_uid != os.getuid()):
    raise SystemExit("Isolated acceptance home is not owned by this user.")
home.mkdir(parents=True, exist_ok=True, mode=0o700)
print(home)
PY
)"
printf 'Isolated acceptance mode. Test games, engines and receipts stay under:\n%s\n' "$TEST_HOME"
printf 'Original engines, installed games and receipts are not migrated.\n'
export HOME="$TEST_HOME"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_STATE_HOME="$HOME/.local/state"
export MCL_TEST_ISOLATED_ENGINES=1
exec bash "$DIR/start-candidate.sh"
