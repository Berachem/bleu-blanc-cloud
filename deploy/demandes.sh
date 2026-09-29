#!/usr/bin/env bash
# Traitement des demandes « Analyser mon site » (lancé toutes les heures par
# bbcloud-demandes.timer). Le verrou partagé avec la campagne hebdomadaire et la mise à jour
# automatique est pris par la commande elle-même (même fichier, même mécanisme flock) :
# si une autre tâche tourne, le traitement est reporté au passage suivant.
# Journaux : journalctl -u bbcloud-demandes
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE/scanner"
exec uv run --frozen bbcloud demandes traiter
