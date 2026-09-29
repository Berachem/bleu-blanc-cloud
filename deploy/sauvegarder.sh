#!/usr/bin/env bash
# Sauvegarde cohérente de la base SQLite avec « sqlite3 .backup » et rotation.
#   DOSSIER_SAUVEGARDES  destination (point de montage du stockage Proxmox), défaut /mnt/sauvegardes
#   JOURS_CONSERVATION   nombre de jours conservés (défaut 30)
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="$RACINE/donnees/bleublanccloud.db"
DESTINATION="${DOSSIER_SAUVEGARDES:-/mnt/sauvegardes}"
JOURS="${JOURS_CONSERVATION:-30}"

if [ ! -f "$BASE" ]; then
  echo "Aucune base à sauvegarder ($BASE)."
  exit 0
fi
mkdir -p "$DESTINATION"
FICHIER="$DESTINATION/bleublanccloud-$(date +%Y-%m-%d).db"
sqlite3 "$BASE" ".backup '$FICHIER'"
sqlite3 "$FICHIER" "PRAGMA integrity_check;" | grep -qx ok
gzip -f "$FICHIER"
find "$DESTINATION" -name 'bleublanccloud-*.db.gz' -mtime "+$JOURS" -delete
echo "✓ Sauvegarde : $FICHIER.gz"
