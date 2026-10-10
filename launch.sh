#!/usr/bin/env bash
# Starts the server if needed and opens the launcher in an app-style window.
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
if ! command -v python3 >/dev/null; then
  echo "Momentum requires Python 3. Install python3 using your system tools before launching." >&2
  exit 1
fi
PORT="${MCL_PORT:-47615}"
URL="http://127.0.0.1:$PORT/"
CACHE="$HOME/.cache/momentum-core-launcher"
mkdir -p "$CACHE"
# Our server answers /api/id; a server from before that endpoint is recognised by its page title.
ours() { python3 "$DIR/launcher_probe.py" ours "$PORT"; }
# One launch at a time, so two quick clicks can't start two servers.
exec 9>"$CACHE/launch.lock"
flock 9 || exit 1
if ! ours; then
  if python3 "$DIR/launcher_probe.py" responding "$PORT"; then
    echo "Port $PORT is in use by another program. Try: MCL_PORT=48000 $0" >&2
    exit 1
  fi
  nohup python3 "$DIR/server.py" >"$CACHE/server.log" 2>&1 9>&- &
  for _ in $(seq 50); do ours && break; sleep 0.1; done
  if ! ours; then
    echo "Momentum did not start. Check $CACHE/server.log for the error." >&2
    exit 1
  fi
fi
exec 9>&-
PROFILE="$CACHE/profile"
# Fullscreen kiosk by default (Chrome ignores --start-fullscreen in app mode).
# The autoplay flag lets the intro sound play before any click.
# MCL_WINDOWED=1 opens a normal maximized app window instead.
for b in google-chrome chromium chromium-browser; do
  if command -v "$b" >/dev/null; then
    if [ -n "$MCL_WINDOWED" ]; then
      exec "$b" --app="$URL" --user-data-dir="$PROFILE" --start-maximized --no-first-run --autoplay-policy=no-user-gesture-required
    fi
    exec "$b" --kiosk "$URL" --user-data-dir="$PROFILE" --no-first-run --autoplay-policy=no-user-gesture-required
  fi
done
exec xdg-open "$URL"
