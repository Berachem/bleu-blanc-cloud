#!/usr/bin/env bash
# Envoi programmé de la prospection badge « Note A » (bbcloud-prospection.timer : du mardi
# au jeudi à 9 h 05). Le mardi, le classeur est d'abord mis à jour (nouvelles communes
# notées A et leur adresse de contact, suivi conservé) : celles qui viennent de passer en A
# reçoivent le mail « Bravo, vous venez d'obtenir la note A » en priorité. Puis : lecture de
# la boîte de réception (réponses, rebonds) et quota du jour, avec 3 à 6 minutes entre deux
# mails. Verrou propre au classeur : n'empêche jamais la campagne, les demandes ni la mise à
# jour automatique.
# Journaux : journalctl -u bbcloud-prospection
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE/scanner"
if [ "$(date +%u)" = "2" ]; then
  echo "▶ Mise à jour du classeur (nouvelles communes notées A)"
  uv run --frozen --with openpyxl bbcloud prospection badge \
    || echo "⚠ Classeur non mis à jour (annuaire injoignable ?) : envoi avec la liste existante"
fi
exec uv run --frozen --with openpyxl bbcloud prospection envoyer
