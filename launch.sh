#!/usr/bin/env bash
# Starts the server if needed and opens the launcher in an app-style window.
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PORT="${MCL_PORT:-47615}"
URL="http://127.0.0.1:$PORT/"
if ! curl -fs -o /dev/null "$URL"; then
  nohup python3 "$DIR/server.py" >/dev/null 2>&1 &
  for _ in $(seq 50); do curl -fs -o /dev/null "$URL" && break; sleep 0.1; done
fi
PROFILE="$HOME/.cache/momentum-core-launcher/profile"
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
