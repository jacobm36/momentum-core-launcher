#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PORT="${MCL_PORT:-47615}"

if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/api/id" >/dev/null 2>&1 \
  || curl -fsS --max-time 2 "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then
  printf 'Port %s is already serving a launcher or another application.\n' "$PORT" >&2
  printf 'Close the old launcher, wait for its server to stop, and run this command again.\n' >&2
  exit 1
fi

export MCL_WINDOWED="${MCL_WINDOWED:-1}"
exec bash "$DIR/launch.sh"
