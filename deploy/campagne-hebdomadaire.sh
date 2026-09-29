#!/usr/bin/env bash
# Chaîne hebdomadaire complète (lancée par bbcloud-campagne.service).
# Chaque étape est journalisée dans journald (journalctl -u bbcloud-campagne).
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERROU="${VERROU:-$RACINE/donnees/bbcloud.verrou}"
cd "$RACINE/scanner"

# Verrou partagé avec la mise à jour automatique (maj-auto.sh) : jamais les deux en même
# temps. Si une mise à jour est en cours (tests, build), la campagne l'attend.
mkdir -p "$(dirname "$VERROU")"
exec 9>"$VERROU"
if ! flock --nonblock 9; then
  echo "▶ Mise à jour automatique en cours : attente de sa fin (2 h au maximum)"
  flock --wait "${ATTENTE_VERROU_S:-7200}" 9 || { echo "✗ Verrou toujours occupé : campagne annulée." >&2; exit 1; }
fi

# Le code n'est plus tiré ici : bbcloud-maj-auto ne fusionne une nouvelle version qu'après
# le passage des tests. La campagne tourne donc toujours sur une version testée.
echo "▶ Code en version $(git -C "$RACINE" rev-parse --short HEAD)"
uv sync --frozen --quiet

echo "▶ Mise à jour des référentiels (plages IP, base ASN, RDAP, SecNumCloud)"
uv run bbcloud referentiels maj || echo "⚠ mise à jour partielle des référentiels"

echo "▶ Mise à jour des cibles (communes ≥ 10 000 hab., départements, régions)"
uv run bbcloud cibles importer --population-min "${POPULATION_MIN:-10000}" || echo "⚠ import des cibles impossible : on garde la liste existante"

echo "▶ Campagne de scan"
uv run bbcloud campagne lancer --oui

echo "▶ Photos des organisations (Wikimedia Commons, licences libres, auto-hébergées)"
uv run bbcloud photos maj || echo "⚠ photos non mises à jour : les fiches gardent les précédentes"

echo "▶ Rapports IA (seuls les constats modifiés entraînent un appel)"
if grep -qE '^MISTRAL_API_KEY=.+' "$RACINE/.env" 2>/dev/null; then
  uv run bbcloud rapports generer --oui --max "${RAPPORTS_MAX:-2000}"
else
  echo "⚠ MISTRAL_API_KEY absente : rapports IA ignorés"
fi

echo "▶ Publication"
"$RACINE/deploy/publier.sh"
echo "✓ Campagne hebdomadaire terminée"
