#!/usr/bin/env bash
# Envoi programmé de la prospection badge « Note A » (bbcloud-prospection.timer : du mardi
# au jeudi à 9 h 05). Relit la boîte de réception (réponses, rebonds), puis envoie le quota du
# jour avec une pause de 3 à 6 minutes entre deux mails. Verrou propre au classeur : n'empêche
# jamais la campagne, les demandes ni la mise à jour automatique.
# Journaux : journalctl -u bbcloud-prospection
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE/scanner"
exec uv run --frozen --with openpyxl bbcloud prospection envoyer
