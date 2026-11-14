#!/bin/sh
# Adds "TV Control" to the app menu. Run again if you move the tv-debloat folder.
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.local/bin ~/.local/share/applications
printf '#!/bin/sh\nexec python3 "%s/tvcontrol.py" "$@"\n' "$HERE" > ~/.local/bin/tv-control
chmod +x ~/.local/bin/tv-control "$HERE/tvcontrol.py"
cat > ~/.local/share/applications/local.tvcontrol.desktop <<DESKTOP
[Desktop Entry]
Type=Application
Name=TV Control
Comment=Turn features on and off on Android TV, Google TV and Fire TV devices
Exec=$HOME/.local/bin/tv-control
Icon=$HERE/icon.png
Categories=Utility;Network;
Keywords=tv;android;firestick;chromecast;adb;debloat;
StartupWMClass=local.tvcontrol
Terminal=false
DESKTOP
update-desktop-database ~/.local/share/applications 2>/dev/null
echo "Installed: find 'TV Control' in your app menu, or run: tv-control"
