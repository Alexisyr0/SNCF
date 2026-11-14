#!/bin/bash
# Installe le robot Première sur le Mac et le lance automatiquement à chaque démarrage.
#   bash installer.sh            installer / mettre à jour
#   bash installer.sh arreter    arrêter le robot
#   bash installer.sh journal    voir ce que fait le robot
set -e
cd "$(dirname "$0")"
ICI="$(pwd)"
PLIST="$HOME/Library/LaunchAgents/fr.premiere.robot.plist"
DOMAINE="gui/$(id -u)"

if [ "$1" = "arreter" ]; then
  launchctl bootout "$DOMAINE" "$PLIST" 2>/dev/null || true
  echo "Robot arrêté."; exit 0
fi
if [ "$1" = "journal" ]; then
  tail -n 60 -f "$ICI/robot.log"; exit 0
fi

echo "1/4  Environnement Python…"
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

echo "2/4  Navigateur…"
if [ ! -d "/Applications/Google Chrome.app" ]; then
  echo "     Google Chrome absent : j'installe le navigateur de Playwright."
  .venv/bin/python -m playwright install chromium
fi

echo "3/4  Configuration et test de connexion…"
if ! .venv/bin/python configurer.py; then
  launchctl bootout "$DOMAINE" "$PLIST" 2>/dev/null || true
  exit 1
fi

echo "4/4  Démarrage automatique…"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>fr.premiere.robot</string>
  <key>ProgramArguments</key><array>
    <string>$ICI/.venv/bin/python</string><string>-u</string><string>$ICI/robot.py</string>
  </array>
  <key>WorkingDirectory</key><string>$ICI</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$ICI/robot.log</string>
  <key>StandardErrorPath</key><string>$ICI/robot.log</string>
</dict></plist>
EOF
launchctl bootout "$DOMAINE" "$PLIST" 2>/dev/null || true
launchctl bootstrap "$DOMAINE" "$PLIST"
sleep 3
echo
echo "✅ Robot installé : il tourne maintenant en fond et redémarre avec le Mac."
echo "   Voir ce qu'il fait : bash $ICI/installer.sh journal   (Ctrl+C pour quitter)"
tail -n 5 "$ICI/robot.log" 2>/dev/null || true
