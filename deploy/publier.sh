#!/usr/bin/env bash
# Export des données → construction du site → publication sur Codeberg Pages.
#
# Variables (lues dans .env) :
#   DEPOT_PAGES    URL git (SSH) du dépôt Pages, ex. git@codeberg.org:berachem/bleublanccloud-pages.git
#   BRANCHE_PAGES  branche publiée (défaut : pages)
#   DOMAINE_SITE   domaine personnalisé (défaut : bleublanccloud.berachem.dev)
#
# Variables d'exécution :
#   NPM_CI=0          ne pas relancer « npm ci » (déjà fait par maj-auto.sh si nécessaire)
#   EXIGER_DONNEES=1  ne rien construire ni publier si la base ne contient aucune organisation
#                     notée (évite de publier un site vide avant la première campagne)
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lire_env() { grep -E "^$1=" "$RACINE/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' || true; }
DEPOT_PAGES="${DEPOT_PAGES:-$(lire_env DEPOT_PAGES)}"
BRANCHE_PAGES="${BRANCHE_PAGES:-$(lire_env BRANCHE_PAGES)}"
BRANCHE_PAGES="${BRANCHE_PAGES:-pages}"
DOMAINE_SITE="${DOMAINE_SITE:-$(lire_env DOMAINE_SITE)}"
DOMAINE_SITE="${DOMAINE_SITE:-bleublanccloud.berachem.dev}"
CLONE_PAGES="${CLONE_PAGES:-$RACINE/donnees/depot-pages}"

echo "▶ Export des données"
(cd "$RACINE/scanner" && uv run bbcloud exporter --vers "$RACINE/site/public/donnees")
if [ "${EXIGER_DONNEES:-0}" = "1" ]; then
  nombre="$(grep -oE '"nombre_organisations": *[0-9]+' "$RACINE/site/public/donnees/meta.json" \
    2>/dev/null | grep -oE '[0-9]+$' || true)"
  if [ "${nombre:-0}" -eq 0 ]; then
    echo "⚠ Aucune organisation notée dans la base : site non régénéré ni publié."
    exit 0
  fi
fi

echo "▶ Construction du site"
cd "$RACINE/site"
if [ "${NPM_CI:-1}" = "1" ] || [ ! -d node_modules ]; then
  npm ci --no-audit --no-fund --silent
fi
ASTRO_TELEMETRY_DISABLED=1 npm run build --silent
if [ "${VERIFIER_EXTERNE:-1}" = "1" ] && command -v chromium >/dev/null 2>&1; then
  npm run verifier:externe --silent
fi

if [ -z "$DEPOT_PAGES" ]; then
  echo "⚠ DEPOT_PAGES non défini : site construit dans site/dist mais non publié."
  exit 0
fi

echo "▶ Publication vers $DEPOT_PAGES (branche $BRANCHE_PAGES)"
if [ ! -d "$CLONE_PAGES/.git" ]; then
  mkdir -p "$(dirname "$CLONE_PAGES")"
  git clone --quiet "$DEPOT_PAGES" "$CLONE_PAGES"
fi
cd "$CLONE_PAGES"
git fetch --quiet origin || true
if git show-ref --verify --quiet "refs/remotes/origin/$BRANCHE_PAGES"; then
  git checkout --quiet -B "$BRANCHE_PAGES" "origin/$BRANCHE_PAGES"
else
  git checkout --quiet --orphan "$BRANCHE_PAGES"
fi
# Remplace tout le contenu publié par le nouveau build (l'historique git est conservé)
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -a "$RACINE/site/dist/." .
printf '%s\n' "$DOMAINE_SITE" > .domains
git add --all
if git diff --cached --quiet; then
  echo "✓ Aucun changement à publier."
  exit 0
fi
git -c user.name="Bleu Blanc Cloud (robot)" -c user.email="robot@${DOMAINE_SITE}" \
  commit --quiet -m "publication : $(date -u +%Y-%m-%dT%H:%MZ)"
git push --quiet origin "$BRANCHE_PAGES"
echo "✓ Site publié sur https://$DOMAINE_SITE"
