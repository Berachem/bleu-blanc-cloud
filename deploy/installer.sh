#!/usr/bin/env bash
# Installation de Bleu Blanc Cloud dans un conteneur LXC Debian 12 (à lancer en root).
#
#   curl -fsSLO https://raw.githubusercontent.com/Berachem/bleu-blanc-cloud/main/deploy/installer.sh
#   bash installer.sh
#
# Le script est idempotent : il peut être relancé sans risque (mise à jour).
set -euo pipefail

DEPOT_CODE="${DEPOT_CODE:-https://github.com/Berachem/bleu-blanc-cloud.git}"
RACINE="${RACINE:-/opt/bleu-blanc-cloud}"
UTILISATEUR="bbcloud"
VERSION_NODE="${VERSION_NODE:-22}"          # branche LTS (Astro exige Node ≥ 22.12)
AVEC_CHROMIUM="${AVEC_CHROMIUM:-0}"        # 1 = vérification « aucune requête externe » à chaque publication

etape() { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Ce script doit être lancé en root (dans le conteneur LXC)." >&2
  exit 1
fi

etape "Paquets système"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates sqlite3 xz-utils gzip locales tzdata openssh-client >/dev/null
if [ "$AVEC_CHROMIUM" = "1" ]; then
  apt-get install -y -qq chromium >/dev/null
fi
sed -i 's/^# *fr_FR.UTF-8/fr_FR.UTF-8/' /etc/locale.gen && locale-gen >/dev/null
timedatectl set-timezone Europe/Paris 2>/dev/null || ln -sf /usr/share/zoneinfo/Europe/Paris /etc/localtime

etape "Node.js ${VERSION_NODE} LTS (binaire officiel, somme de contrôle vérifiée)"
ARCH="$(dpkg --print-architecture)"
case "$ARCH" in amd64) ARCH_NODE="x64" ;; arm64) ARCH_NODE="arm64" ;; *) echo "Architecture non gérée : $ARCH" >&2; exit 1 ;; esac
VERSION_ACTUELLE="$(node --version 2>/dev/null || true)"
if [[ "$VERSION_ACTUELLE" != v${VERSION_NODE}.* ]]; then
  TEMP="$(mktemp -d)"
  BASE_URL="https://nodejs.org/dist/latest-v${VERSION_NODE}.x"
  curl -fsSL "$BASE_URL/SHASUMS256.txt" -o "$TEMP/SHASUMS256.txt"
  ARCHIVE="$(grep -oE "node-v[0-9.]+-linux-${ARCH_NODE}\.tar\.xz" "$TEMP/SHASUMS256.txt" | head -1)"
  curl -fsSL "$BASE_URL/$ARCHIVE" -o "$TEMP/$ARCHIVE"
  (cd "$TEMP" && grep " $ARCHIVE\$" SHASUMS256.txt | sha256sum -c --quiet)
  tar -xJf "$TEMP/$ARCHIVE" -C /usr/local --strip-components=1 --exclude='*.md' --exclude=LICENSE
  rm -rf "$TEMP"
fi
node --version

etape "uv (gestionnaire Python)"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
fi
uv --version

etape "Utilisateur dédié « $UTILISATEUR »"
if ! id "$UTILISATEUR" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$UTILISATEUR"
fi

etape "Code source dans $RACINE"
if [ ! -d "$RACINE/.git" ]; then
  git clone --quiet "$DEPOT_CODE" "$RACINE"
else
  git -C "$RACINE" pull --ff-only --quiet || true
fi
chown -R "$UTILISATEUR:$UTILISATEUR" "$RACINE"

etape "Dépendances Python (scanner) et Node (site)"
sudo_bb() { su - "$UTILISATEUR" -c "cd '$RACINE' && $*"; }
sudo_bb "cd scanner && uv sync --frozen --quiet"
sudo_bb "cd site && npm ci --no-audit --no-fund --silent"

etape "Configuration (.env)"
if [ ! -f "$RACINE/.env" ]; then
  cp "$RACINE/.env.example" "$RACINE/.env"
  chown "$UTILISATEUR:$UTILISATEUR" "$RACINE/.env"
  chmod 600 "$RACINE/.env"
  echo "→ $RACINE/.env créé : complétez MISTRAL_API_KEY, IPINFO_TOKEN et DEPOT_PAGES."
fi
mkdir -p /etc/bbcloud
if [ ! -f /etc/bbcloud/sauvegarde.env ]; then
  printf 'DOSSIER_SAUVEGARDES=/mnt/sauvegardes\nJOURS_CONSERVATION=30\n' > /etc/bbcloud/sauvegarde.env
fi
mkdir -p /mnt/sauvegardes && chown "$UTILISATEUR:$UTILISATEUR" /mnt/sauvegardes

etape "Clé SSH de publication (Codeberg)"
CLE="/home/$UTILISATEUR/.ssh/id_ed25519_codeberg"
if [ ! -f "$CLE" ]; then
  su - "$UTILISATEUR" -c "mkdir -p ~/.ssh && chmod 700 ~/.ssh && ssh-keygen -q -t ed25519 -N '' -C 'bbcloud-publication' -f '$CLE'"
  cat > "/home/$UTILISATEUR/.ssh/config" <<CONFIG
Host codeberg.org
  User git
  IdentityFile $CLE
  IdentitiesOnly yes
CONFIG
  chown "$UTILISATEUR:$UTILISATEUR" "/home/$UTILISATEUR/.ssh/config"
fi
su - "$UTILISATEUR" -c "ssh-keyscan -t ed25519 codeberg.org >> ~/.ssh/known_hosts 2>/dev/null; sort -u -o ~/.ssh/known_hosts ~/.ssh/known_hosts"

etape "Services systemd"
install -m 644 "$RACINE"/deploy/bbcloud-*.service "$RACINE"/deploy/bbcloud-*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now bbcloud-sauvegarde.timer >/dev/null
echo "→ Timer de campagne installé mais NON activé : activez-le après votre première campagne de test."

etape "Vérification"
sudo_bb "cd scanner && uv run bbcloud version && uv run bbcloud referentiels verifier | head -2"

cat <<FIN

✓ Installation terminée.

Prochaines étapes (voir deploy/README.md) :
  1. Complétez $RACINE/.env (clé Mistral, jeton IPinfo, dépôt Codeberg Pages).
  2. Ajoutez cette clé publique comme « clé de déploiement » (avec écriture) du dépôt Codeberg :
     $(cat "$CLE.pub")
  3. Lancez la première campagne de test, puis activez le timer :
     systemctl enable --now bbcloud-campagne.timer
FIN
