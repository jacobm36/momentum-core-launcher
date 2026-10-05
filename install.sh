#!/usr/bin/env bash
set -e
# Adds Momentum Core Launcher to the app menu and Desktop.
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
chmod +x "$DIR/launch.sh" "$DIR/server.py"
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
F="$APPS/momentum-core-launcher.desktop"
# Desktop-entry Exec values are quoted, with backslash, quote, $ and backtick escaped.
EXEC_PATH="$(printf '%s' "$DIR/launch.sh" | sed 's/[\\"$`]/\\&/g')"
cat > "$F" <<EOT
[Desktop Entry]
Type=Application
Name=Momentum Core Launcher
Comment=Launch all my games
Exec="$EXEC_PATH"
Icon=$DIR/web/icon-256.png
Categories=Game;
Terminal=false
EOT
chmod +x "$F"
D="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
[ -d "$D" ] && cp "$F" "$D/" && chmod +x "$D/momentum-core-launcher.desktop" && gio set "$D/momentum-core-launcher.desktop" metadata::trusted true 2>/dev/null || true
update-desktop-database "$APPS" 2>/dev/null || true
echo "Installed."
