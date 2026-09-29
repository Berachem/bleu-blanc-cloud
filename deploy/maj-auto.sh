#!/usr/bin/env bash
# Mise à jour automatique du serveur (lancée toutes les heures par bbcloud-maj-auto.timer).
#
#   1. git fetch : s'arrête tout de suite s'il n'y a rien de nouveau sur origin/main ;
#   2. git merge --ff-only, uv sync, npm ci (seulement si site/package-lock.json a changé) ;
#   3. tests du scanner (pytest) : en cas d'échec, retour à la version précédente, rien n'est
#      publié et le commit fautif n'est plus retenté tant qu'un nouveau commit n'arrive pas ;
#   4. si les tests passent : régénération et publication du site à partir des données déjà
#      en base (export → build → push), SANS relancer de scan. Si les référentiels ou le
#      calcul du score ont changé, les scores sont d'abord recalculés depuis les constats
#      enregistrés (bbcloud scores recalculer), et les contours de communes manquants sont
#      téléchargés (carte de situation des fiches).
#
# Un verrou (flock) partagé avec la campagne hebdomadaire garantit que les deux ne tournent
# jamais en même temps : si la campagne est en cours, la mise à jour est reportée à l'heure
# suivante. Tout est journalisé dans journald : journalctl -u bbcloud-maj-auto
#
# Variables facultatives : BRANCHE (main), VERROU, FICHIER_REJET.
set -euo pipefail

RACINE="${RACINE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BRANCHE="${BRANCHE:-main}"
VERROU="${VERROU:-$RACINE/donnees/bbcloud.verrou}"
FICHIER_REJET="${FICHIER_REJET:-$RACINE/donnees/maj-auto-rejet}"

# Sous systemd, les préfixes « <N> » fixent la priorité du message dans journald (sd-daemon).
if [ -n "${JOURNAL_STREAM:-}" ]; then P_INFO="<6>" P_AVERT="<4>" P_ERREUR="<3>"; else
  P_INFO="" P_AVERT="" P_ERREUR=""
fi
info() { echo "${P_INFO}$*"; }
avertir() { echo "${P_AVERT}⚠ $*"; }
erreur() { echo "${P_ERREUR}✗ $*" >&2; }
court() { git -C "$RACINE" rev-parse --short "$1"; }

# Python toujours ; Node seulement si le fichier de verrouillage npm a changé (ou manque).
synchroniser_dependances() {
  local de="$1" vers="$2"
  info "▶ Dépendances Python (uv sync)"
  (cd "$RACINE/scanner" && uv sync --frozen --quiet) || return 1
  if ! git -C "$RACINE" diff --quiet "$de" "$vers" -- site/package-lock.json \
    || [ ! -d "$RACINE/site/node_modules" ]; then
    info "▶ Dépendances Node (npm ci) : package-lock.json modifié"
    (cd "$RACINE/site" && npm ci --no-audit --no-fund --silent) || return 1
  else
    info "  package-lock.json inchangé : npm ci inutile"
  fi
}

# Échec après la fusion : retour à la version précédente, le commit est mémorisé comme rejeté.
revenir() {
  local ancien="$1" nouveau="$2" raison="$3"
  erreur "$raison : retour à $(court "$ancien"), rien n'est publié."
  echo "$nouveau" > "$FICHIER_REJET"
  git -C "$RACINE" reset --quiet --keep "$ancien"
  synchroniser_dependances "$nouveau" "$ancien" || erreur "Resynchronisation des dépendances impossible."
  return 1
}

principal() {
  mkdir -p "$(dirname "$VERROU")"
  exec 9>"$VERROU"
  if ! flock --nonblock 9; then
    info "Une autre tâche Bleu Blanc Cloud (campagne hebdomadaire ?) est en cours : mise à jour reportée."
    return 0
  fi

  # Dépôt privé : la clé de déploiement de ~/.ssh/config est utilisée, sans jamais rien demander.
  export GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=15"
  cd "$RACINE"

  if ! git fetch --quiet origin "$BRANCHE"; then
    erreur "git fetch impossible (réseau ou clé de déploiement) : nouvel essai à l'heure suivante."
    return 1
  fi
  local ancien nouveau
  ancien="$(git rev-parse HEAD)"
  nouveau="$(git rev-parse "origin/$BRANCHE")"

  if [ "$ancien" = "$nouveau" ] || git merge-base --is-ancestor "$nouveau" "$ancien"; then
    info "✓ Rien de nouveau sur origin/$BRANCHE ($(court "$ancien"))."
    return 0
  fi
  if [ -f "$FICHIER_REJET" ] && [ "$(cat "$FICHIER_REJET")" = "$nouveau" ]; then
    avertir "$(court "$nouveau") déjà rejeté (tests en échec) : en attente d'un nouveau commit."
    return 0
  fi

  info "▶ Mise à jour $(court "$ancien") → $(court "$nouveau")"
  git log --no-decorate --format='  • %h %s' "$ancien..$nouveau"
  if ! git merge --ff-only --quiet "origin/$BRANCHE"; then
    erreur "Fusion en avance rapide impossible (modifications locales sur le serveur ?)."
    erreur "Voir : git -C $RACINE status"
    return 1
  fi

  if ! synchroniser_dependances "$ancien" "$nouveau"; then
    revenir "$ancien" "$nouveau" "Installation des dépendances en échec"
    return 1
  fi

  info "▶ Tests du scanner (pytest)"
  if ! (cd "$RACINE/scanner" && uv run pytest -q -p no:cacheprovider); then
    revenir "$ancien" "$nouveau" "Tests en échec"
    return 1
  fi
  rm -f "$FICHIER_REJET"

  # Référentiels ou méthodologie modifiés : constats réattribués et scores recalculés en base
  if ! git diff --quiet "$ancien" "$nouveau" -- \
    scanner/src/bleublanccloud/referentiels/ scanner/src/bleublanccloud/analyse/; then
    info "▶ Référentiels ou calcul du score modifiés : recalcul des scores (aucun scan)"
    (cd "$RACINE/scanner" && uv run bbcloud scores recalculer)
  fi

  # Contours des communes (carte de situation) : seuls les manquants sont demandés à
  # geo.api.gouv.fr ; aucune requête s'ils sont tous en base. Un échec n'empêche rien : la
  # fiche garde son illustration jusqu'au prochain essai.
  (cd "$RACINE/scanner" && uv run bbcloud cibles contours) \
    || avertir "Contours des communes non mis à jour (geo.api.gouv.fr injoignable ?)."

  info "▶ Régénération et publication du site (données existantes, aucun scan)"
  NPM_CI=0 EXIGER_DONNEES=1 "$RACINE/deploy/publier.sh"
  info "✓ Serveur à jour en $(court "$nouveau")."
}

# Tout le script est lu avant exécution (fonction) : la fusion peut donc le modifier sans risque.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  principal "$@"
  exit $?
fi
