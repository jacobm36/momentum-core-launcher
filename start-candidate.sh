#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PORT="${MCL_PORT:-47615}"

if ! command -v python3 >/dev/null; then
  printf 'Momentum requires Python 3. Install python3 using your system tools first.\n' >&2
  exit 1
fi
if python3 "$DIR/launcher_probe.py" responding "$PORT"; then
  printf 'Port %s is already serving a launcher or another application.\n' "$PORT" >&2
  printf 'Close the old launcher, wait for its server to stop, and run this command again.\n' >&2
  exit 1
fi

export MCL_WINDOWED="${MCL_WINDOWED:-1}"
exec bash "$DIR/launch.sh"
