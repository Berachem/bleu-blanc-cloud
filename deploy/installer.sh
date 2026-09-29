#!/usr/bin/env bash
# Installation de Bleu Blanc Cloud dans un conteneur LXC Debian 12 (à lancer en root).
#
#   bash installer.sh
#
# Fonctionne avec un dépôt GitHub public ou privé (détection automatique) :
# - public : clonage en HTTPS, sans identifiant ;
# - privé  : le script génère une clé SSH de déploiement en lecture seule, l'affiche, attend
#            que vous l'ajoutiez au dépôt GitHub, puis clone en SSH. Les mises à jour
#            automatiques (bbcloud-maj-auto, git fetch) utilisent la même clé.
#
# Variables facultatives :
#   DEPOT=Berachem/bleu-blanc-cloud   dépôt GitHub (propriétaire/nom)
#   DEPOT_PRIVE=auto|1|0             forcer le mode privé (1) ou public (0)
#   AVEC_CHROMIUM=1                  installer Chromium (vérification « aucune requête externe »)
#
# Le script est idempotent : il peut être relancé sans risque (mise à jour, reprise).
set -euo pipefail

DEPOT="${DEPOT:-Berachem/bleu-blanc-cloud}"
DEPOT_PRIVE="${DEPOT_PRIVE:-auto}"
RACINE="${RACINE:-/opt/bleu-blanc-cloud}"
UTILISATEUR="bbcloud"
VERSION_NODE="${VERSION_NODE:-22}"          # branche LTS (Astro exige Node ≥ 22.12)
AVEC_CHROMIUM="${AVEC_CHROMIUM:-0}"
DOSSIER_SSH="/home/$UTILISATEUR/.ssh"
CLE_GITHUB="$DOSSIER_SSH/id_ed25519_github"
CLE_CODEBERG="$DOSSIER_SSH/id_ed25519_codeberg"

# Clé d'hôte officielle de GitHub (empreinte SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU),
# publiée sur https://docs.github.com/fr/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
# Elle est épinglée pour éviter toute interception lors de la première connexion.
CLE_HOTE_GITHUB="github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"

etape() { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }
avertir() { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
en_tant_que_bbcloud() { su - "$UTILISATEUR" -c "$*"; }

url_https() { echo "https://github.com/$DEPOT.git"; }
url_ssh() { echo "git@github.com:$DEPOT.git"; }

# Un dépôt public se liste sans identifiant ; sinon on bascule en mode privé.
depot_est_public() {
  GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/true timeout 30 \
    git ls-remote --heads "$(url_https)" >/dev/null 2>&1
}

mode_prive() {
  case "$DEPOT_PRIVE" in
    1 | oui | true) return 0 ;;
    0 | non | false) return 1 ;;
    *) ! depot_est_public ;;
  esac
}

# Ajoute un bloc « Host » à ~/.ssh/config s'il n'existe pas déjà (idempotent).
ajouter_hote_ssh() {
  local hote="$1" cle="$2" config="$DOSSIER_SSH/config"
  touch "$config"
  if ! grep -qx "Host $hote" "$config"; then
    printf 'Host %s\n  User git\n  IdentityFile %s\n  IdentitiesOnly yes\n\n' "$hote" "$cle" >> "$config"
  fi
  chown "$UTILISATEUR:$UTILISATEUR" "$config"
  chmod 600 "$config"
}

# Ajoute une ligne à known_hosts si elle n'y est pas déjà.
ajouter_hote_connu() {
  local ligne="$1" fichier="$DOSSIER_SSH/known_hosts"
  touch "$fichier"
  grep -qxF "$ligne" "$fichier" || echo "$ligne" >> "$fichier"
  chown "$UTILISATEUR:$UTILISATEUR" "$fichier"
  chmod 644 "$fichier"
}

generer_cle() {
  local cle="$1" commentaire="$2"
  if [ ! -f "$cle" ]; then
    en_tant_que_bbcloud "ssh-keygen -q -t ed25519 -N '' -C '$commentaire' -f '$cle'"
  fi
}

preparer_ssh() {
  install -d -m 700 -o "$UTILISATEUR" -g "$UTILISATEUR" "$DOSSIER_SSH"
}

acces_github_ok() {
  en_tant_que_bbcloud "GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=15' \
    git ls-remote --heads '$(url_ssh)' >/dev/null 2>&1"
}

# Mode privé : clé de déploiement GitHub en lecture seule, puis attente de son ajout.
configurer_acces_prive() {
  etape "Dépôt privé : clé de déploiement GitHub (lecture seule)"
  preparer_ssh
  generer_cle "$CLE_GITHUB" "bbcloud-lecture-$(hostname)"
  ajouter_hote_ssh "github.com" "$CLE_GITHUB"
  ajouter_hote_connu "$CLE_HOTE_GITHUB"

  if acces_github_ok; then
    echo "✓ Accès au dépôt privé $DEPOT confirmé."
    return 0
  fi

  cat <<CONSIGNES

  Ajoutez cette clé publique au dépôt GitHub :
    https://github.com/$DEPOT/settings/keys/new
  • Titre : bbcloud ($(hostname))
  • Clé   :

$(cat "$CLE_GITHUB.pub")

  • Laissez « Allow write access » DÉCOCHÉ (lecture seule suffit).

CONSIGNES
  if [ ! -t 0 ]; then
    avertir "Session non interactive : relancez « bash installer.sh » une fois la clé ajoutée."
    exit 2
  fi
  local tentative
  for tentative in 1 2 3 4 5; do
    read -r -p "Appuyez sur Entrée une fois la clé ajoutée (tentative $tentative/5)… " _
    if acces_github_ok; then
      echo "✓ Accès au dépôt privé $DEPOT confirmé."
      return 0
    fi
    avertir "Accès refusé : vérifiez la clé collée et le nom du dépôt ($DEPOT)."
  done
  avertir "Accès toujours refusé. Relancez « bash installer.sh » quand la clé sera en place."
  exit 2
}

# Clone (ou met à jour) le dépôt en tant que « bbcloud », en HTTPS ou en SSH selon le mode.
recuperer_code() {
  local url="$1"
  etape "Code source dans $RACINE"
  if [ ! -d "$RACINE/.git" ]; then
    install -d -o "$UTILISATEUR" -g "$UTILISATEUR" "$RACINE"
    en_tant_que_bbcloud "git clone --quiet '$url' '$RACINE'"
  else
    chown -R "$UTILISATEUR:$UTILISATEUR" "$RACINE"
    en_tant_que_bbcloud "git -C '$RACINE' remote set-url origin '$url'"
    en_tant_que_bbcloud "git -C '$RACINE' pull --ff-only --quiet" \
      || avertir "git pull impossible : on continue avec la version locale."
  fi
}

installer_paquets() {
  etape "Paquets système"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq git curl ca-certificates sqlite3 xz-utils gzip locales tzdata \
    openssh-client util-linux >/dev/null
  if [ "$AVEC_CHROMIUM" = "1" ]; then
    apt-get install -y -qq chromium >/dev/null
  fi
  sed -i 's/^# *fr_FR.UTF-8/fr_FR.UTF-8/' /etc/locale.gen && locale-gen >/dev/null
  timedatectl set-timezone Europe/Paris 2>/dev/null \
    || ln -sf /usr/share/zoneinfo/Europe/Paris /etc/localtime
}

installer_node() {
  etape "Node.js ${VERSION_NODE} LTS (binaire officiel, somme de contrôle vérifiée)"
  local arch arch_node version temp base_url archive
  arch="$(dpkg --print-architecture)"
  case "$arch" in
    amd64) arch_node="x64" ;;
    arm64) arch_node="arm64" ;;
    *) echo "Architecture non gérée : $arch" >&2; exit 1 ;;
  esac
  version="$(node --version 2>/dev/null || true)"
  if [[ "$version" != v${VERSION_NODE}.* ]]; then
    temp="$(mktemp -d)"
    base_url="https://nodejs.org/dist/latest-v${VERSION_NODE}.x"
    curl -fsSL "$base_url/SHASUMS256.txt" -o "$temp/SHASUMS256.txt"
    archive="$(grep -oE "node-v[0-9.]+-linux-${arch_node}\.tar\.xz" "$temp/SHASUMS256.txt" | head -1)"
    curl -fsSL "$base_url/$archive" -o "$temp/$archive"
    (cd "$temp" && grep " $archive\$" SHASUMS256.txt | sha256sum -c --quiet)
    tar -xJf "$temp/$archive" -C /usr/local --strip-components=1 --exclude='*.md' --exclude=LICENSE
    rm -rf "$temp"
  fi
  node --version
}

installer_uv() {
  etape "uv (gestionnaire Python)"
  if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh \
      | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
  fi
  uv --version
}

principal() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "Ce script doit être lancé en root (dans le conteneur LXC)." >&2
    exit 1
  fi

  installer_paquets
  installer_node
  installer_uv

  etape "Utilisateur dédié « $UTILISATEUR »"
  if ! id "$UTILISATEUR" >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash "$UTILISATEUR"
  fi
  preparer_ssh

  local prive=0
  if mode_prive; then
    prive=1
    configurer_acces_prive
    recuperer_code "$(url_ssh)"
  else
    echo "Dépôt public détecté : clonage en HTTPS."
    recuperer_code "$(url_https)"
  fi

  etape "Dépendances Python (scanner) et Node (site)"
  en_tant_que_bbcloud "cd '$RACINE/scanner' && uv sync --frozen --quiet"
  en_tant_que_bbcloud "cd '$RACINE/site' && npm ci --no-audit --no-fund --silent"

  etape "Configuration (.env)"
  if [ ! -f "$RACINE/.env" ]; then
    install -m 600 -o "$UTILISATEUR" -g "$UTILISATEUR" "$RACINE/.env.example" "$RACINE/.env"
    echo "→ $RACINE/.env créé : complétez MISTRAL_API_KEY, IPINFO_TOKEN et DEPOT_PAGES."
  fi
  mkdir -p /etc/bbcloud
  if [ ! -f /etc/bbcloud/sauvegarde.env ]; then
    printf 'DOSSIER_SAUVEGARDES=/mnt/sauvegardes\nJOURS_CONSERVATION=30\n' > /etc/bbcloud/sauvegarde.env
  fi
  mkdir -p /mnt/sauvegardes && chown "$UTILISATEUR:$UTILISATEUR" /mnt/sauvegardes

  etape "Clé SSH de publication (Codeberg Pages)"
  generer_cle "$CLE_CODEBERG" "bbcloud-publication"
  ajouter_hote_ssh "codeberg.org" "$CLE_CODEBERG"
  en_tant_que_bbcloud "ssh-keyscan -t ed25519 codeberg.org 2>/dev/null" | while read -r ligne; do
    [ -n "$ligne" ] && ajouter_hote_connu "$ligne"
  done

  etape "Services systemd"
  install -m 644 "$RACINE"/deploy/bbcloud-*.service "$RACINE"/deploy/bbcloud-*.timer /etc/systemd/system/
  systemctl daemon-reload
  chmod 755 "$RACINE"/deploy/*.sh
  systemctl enable --now bbcloud-sauvegarde.timer >/dev/null
  systemctl enable --now bbcloud-maj-auto.timer >/dev/null
  echo "→ Mise à jour automatique activée (toutes les heures) : journalctl -u bbcloud-maj-auto"
  echo "→ Timer de campagne installé mais NON activé : activez-le après votre première campagne de test."

  etape "Vérification"
  en_tant_que_bbcloud "cd '$RACINE/scanner' && uv run bbcloud version && uv run bbcloud referentiels verifier | head -2"

  cat <<FIN

✓ Installation terminée ($([ "$prive" = 1 ] && echo "dépôt privé, accès par clé de déploiement" || echo "dépôt public")).

Prochaines étapes (voir deploy/README.md) :
  1. Complétez $RACINE/.env (clé Mistral, jeton IPinfo, dépôt Codeberg Pages).
  2. Ajoutez cette clé publique comme « clé de déploiement » AVEC écriture du dépôt Codeberg Pages :
     $(cat "$CLE_CODEBERG.pub")
  3. Lancez la première campagne de test, puis activez le timer :
     systemctl enable --now bbcloud-campagne.timer
FIN
}

# Le script peut être « sourcé » par les tests sans rien exécuter.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  principal "$@"
fi
