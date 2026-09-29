#!/usr/bin/env bash
# Chaîne hebdomadaire complète (lancée par bbcloud-campagne.service).
# Chaque étape est journalisée dans journald (journalctl -u bbcloud-campagne).
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE/scanner"

echo "▶ Mise à jour du code (branche main)"
git -C "$RACINE" pull --ff-only --quiet || echo "⚠ git pull impossible : on continue avec la version locale"
uv sync --frozen --quiet

echo "▶ Mise à jour des référentiels (plages IP, base ASN, RDAP, SecNumCloud)"
uv run bbcloud referentiels maj || echo "⚠ mise à jour partielle des référentiels"

echo "▶ Mise à jour des cibles (communes ≥ 10 000 hab., départements, régions)"
uv run bbcloud cibles importer --population-min "${POPULATION_MIN:-10000}" || echo "⚠ import des cibles impossible : on garde la liste existante"

echo "▶ Campagne de scan"
uv run bbcloud campagne lancer --oui

echo "▶ Rapports IA (seuls les constats modifiés entraînent un appel)"
if grep -qE '^MISTRAL_API_KEY=.+' "$RACINE/.env" 2>/dev/null; then
  uv run bbcloud rapports generer --oui --max "${RAPPORTS_MAX:-2000}"
else
  echo "⚠ MISTRAL_API_KEY absente : rapports IA ignorés"
fi

echo "▶ Publication"
"$RACINE/deploy/publier.sh"
echo "✓ Campagne hebdomadaire terminée"
