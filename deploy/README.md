# Mise en production sur Proxmox — guide pas à pas 🇫🇷

Ce guide installe Bleu Blanc Cloud dans un **conteneur LXC Debian 12** sur ton Proxmox, puis publie le site sur **Codeberg Pages** à l'adresse `https://bleublanccloud.berachem.dev`.

⏱️ Compter environ **1 heure** la première fois. Tout est déjà prêt dans le dépôt : il reste à créer le conteneur, lancer le script d'installation et renseigner quelques clés.

```
Proxmox (chez toi)                                    Internet
┌──────────────────────────────────────────┐
│ LXC Debian 12 « bbcloud »                 │   git push   ┌────────────────────────┐
│  timer systemd (dimanche 3 h)             │ ───────────▶ │ Codeberg Pages (DE)    │
│   référentiels → campagne → rapports IA   │              │ bleublanccloud.        │
│   → export JSON → build Astro → publier   │              │ berachem.dev           │
│  sauvegarde SQLite quotidienne (2 h)      │              └────────────────────────┘
└──────────────────────────────────────────┘
      aucun port entrant, uniquement des connexions sortantes
```

---

## 0. Ce qu'il te faut

| Élément | Où l'obtenir | Obligatoire ? |
|---|---|---|
| Proxmox VE 8 avec un accès administrateur | — | oui |
| Un compte **Codeberg** | <https://codeberg.org/user/sign_up> | oui |
| L'accès à la zone DNS de `berachem.dev` | ton fournisseur DNS actuel (Cloudflare) | oui |
| Une clé API **Mistral** | <https://console.mistral.ai> → *API Keys* | pour les rapports IA |
| Un jeton **IPinfo** gratuit (base IP → ASN) | <https://ipinfo.io/signup> | recommandé (sinon repli sur RIPEstat, plus lent) |

> 💡 Si le dépôt GitHub `Berachem/bleu-blanc-cloud` est **privé**, rends-le public (le code est sous EUPL-1.2) ou remplace `DEPOT_CODE` par une URL contenant un jeton d'accès en lecture.

---

## 1. Créer le conteneur LXC

### Option A — interface web de Proxmox

1. **Modèle** : *Datacenter → ton nœud → local → CT Templates → Templates* → télécharger `debian-12-standard`.
2. **Create CT** :
   - *General* : hostname `bbcloud`, **Unprivileged container** coché, un mot de passe root.
   - *Template* : `debian-12-standard`.
   - *Disks* : 16 Go.
   - *CPU* : 2 cœurs · *Memory* : 2048 Mo, swap 512 Mo.
   - *Network* : `vmbr0`, IPv4 en DHCP (ou une IP fixe).
   - *Options* (après création) : **Start at boot** = oui ; *Features* : **nesting** coché.

### Option B — en ligne de commande (sur l'hôte Proxmox)

```bash
pveam update
pveam available --section system | grep debian-12        # repère le nom exact du modèle
pveam download local debian-12-standard_12.7-1_amd64.tar.zst

pct create 120 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname bbcloud --unprivileged 1 --features nesting=1 \
  --cores 2 --memory 2048 --swap 512 --rootfs local-lvm:16 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp --onboot 1 --start 1
```

(Remplace `120` par un identifiant libre et le nom du modèle par celui affiché.)

### Stockage des sauvegardes (recommandé)

Monte un dossier de l'hôte dans le conteneur pour y déposer les sauvegardes quotidiennes :

```bash
# Sur l'hôte Proxmox
mkdir -p /mnt/sauvegardes/bbcloud
chown 101000:101000 /mnt/sauvegardes/bbcloud     # utilisateur « bbcloud » (uid 1000) d'un conteneur non privilégié
pct set 120 -mp0 /mnt/sauvegardes/bbcloud,mp=/mnt/sauvegardes
pct reboot 120
```

> Si `bbcloud` n'a pas l'uid 1000 dans le conteneur (`id bbcloud`), adapte : uid hôte = 100000 + uid conteneur.

---

## 2. Lancer l'installation automatique

```bash
pct enter 120                      # ou connexion SSH/console au conteneur, en root
apt-get update && apt-get install -y curl
curl -fsSLO https://raw.githubusercontent.com/Berachem/bleu-blanc-cloud/main/deploy/installer.sh
bash installer.sh
```

Le script (idempotent, relançable sans risque) :

- installe `git`, `sqlite3`, **Node.js 22 LTS** (binaire officiel, somme de contrôle vérifiée) et **uv** ;
- crée l'utilisateur système `bbcloud` et clone le code dans `/opt/bleu-blanc-cloud` ;
- installe les dépendances Python et Node ;
- crée `/opt/bleu-blanc-cloud/.env` à partir de `.env.example` (droits `600`) ;
- génère une **clé SSH de publication** pour Codeberg et l'affiche ;
- installe les services systemd, active la **sauvegarde quotidienne** et laisse le **timer de campagne désactivé** jusqu'à ta validation.

> Option : `AVEC_CHROMIUM=1 bash installer.sh` installe Chromium pour que chaque publication vérifie automatiquement l'absence de requête externe et de cookie (≈ 300 Mo).

---

## 3. Renseigner la configuration

```bash
nano /opt/bleu-blanc-cloud/.env
```

| Variable | Valeur |
|---|---|
| `MISTRAL_API_KEY` | ta clé Mistral |
| `MISTRAL_MODELE` | `mistral-small-latest` (par défaut) |
| `MISTRAL_SERVEUR` | `eu` (serveur européen `api.eu.mistral.ai`) |
| `MISTRAL_PRIX_ENTREE_PAR_M` / `…_SORTIE_…` | tarifs en $ par million de jetons, pour l'estimation `--dry-run` (vérifie-les sur <https://mistral.ai/pricing>) |
| `IPINFO_TOKEN` | ton jeton IPinfo (facultatif mais conseillé) |
| `DEPOT_PAGES` | `git@codeberg.org:<ton-pseudo>/bleublanccloud-pages.git` (étape 4) |

Les autres valeurs (politesse du robot, chemins) peuvent rester telles quelles.

---

## 4. Codeberg Pages et nom de domaine

1. Sur Codeberg, crée un dépôt **public et vide** nommé `bleublanccloud-pages`.
2. *Paramètres du dépôt → Deploy Keys → Add Key* : colle la clé publique affichée par l'installateur
   (ou `cat /home/bbcloud/.ssh/id_ed25519_codeberg.pub`) et coche **Enable write access**.
3. Dans la zone DNS de `berachem.dev`, ajoute :

   | Type | Nom | Cible |
   |---|---|---|
   | `CNAME` | `bleublanccloud` | `bleublanccloud-pages.<ton-pseudo>.codeberg.page.` |

   ⚠️ **Chez Cloudflare, mets l'enregistrement en « DNS only » (nuage gris)**. Proxifié (nuage orange), le site serait servi par Cloudflare : Codeberg ne pourrait pas émettre le certificat, et le site perdrait sa note A sur son propre scan (hébergement masqué par un CDN américain → niveau C).

4. Le script `publier.sh` pousse le site sur la branche `pages` et écrit le fichier `.domains` ; Codeberg obtient ensuite automatiquement le certificat HTTPS (quelques minutes après la propagation DNS).

> 💡 Pour un **100/100** au lieu de 87/100 (A) : héberger la zone DNS de `berachem.dev` chez un fournisseur européen (deSEC, Gandi, OVHcloud…) plutôt que chez Cloudflare. Ce n'est pas obligatoire pour obtenir la note A.

---

## 5. Premier lancement (manuel)

Toutes les commandes se lancent en tant qu'utilisateur `bbcloud` :

```bash
su - bbcloud
cd /opt/bleu-blanc-cloud/scanner
```

1. **Référentiels** (plages IP des clouds, base ASN, amorçage RDAP, contrôle SecNumCloud) :
   ```bash
   uv run bbcloud referentiels maj
   ```
2. **Test sur un domaine autorisé** :
   ```bash
   uv run bbcloud scanner berachem.dev
   ```
3. **Import des cibles** (communes ≥ 10 000 habitants, départements, régions) :
   ```bash
   uv run bbcloud cibles importer --population-min 10000
   uv run bbcloud cibles lister --limite 20
   ```
4. **Campagne de test limitée à 10 organisations** (à valider avant toute campagne complète) :
   ```bash
   uv run bbcloud campagne lancer --limite 10 --dry-run   # liste les cibles, aucune requête
   uv run bbcloud campagne lancer --limite 10             # confirmation demandée
   uv run bbcloud referentiels inconnus                   # hébergeurs non identifiés à ajouter au référentiel
   ```
5. **Rapports IA** :
   ```bash
   uv run bbcloud rapports generer --max 3 --dry-run      # nombre d'appels et coût estimés
   uv run bbcloud rapports generer --max 3
   ```
6. **Aperçu local du site** (depuis ton réseau, sur `http://<IP-du-conteneur>:4321`) :
   ```bash
   uv run bbcloud exporter
   cd ../site && npm run build && npx astro preview --host 0.0.0.0
   ```
7. **Publication**, puis **dogfooding** (le site doit obtenir A) :
   ```bash
   cd ../scanner
   uv run bbcloud publier
   uv run bbcloud scanner bleublanccloud.berachem.dev
   ```

---

## 6. Automatiser

```bash
exit                                               # retour en root
systemctl enable --now bbcloud-campagne.timer      # chaque dimanche à 3 h (heure de Paris)
systemctl list-timers 'bbcloud*'
```

- Lancer la chaîne complète tout de suite : `systemctl start bbcloud-campagne.service`
- Suivre les journaux : `journalctl -u bbcloud-campagne -f`
- La chaîne hebdomadaire (`deploy/campagne-hebdomadaire.sh`) : `git pull` → `referentiels maj` → `cibles importer` → `campagne lancer --oui` → `rapports generer --oui` (seulement si la clé Mistral est présente ; le cache évite tout appel si rien n'a changé) → `publier`.
- Durée indicative d'une campagne complète (~1 000 organisations, 1 requête/s/domaine, 10 scans en parallèle) : **30 à 60 minutes**.

---

## 7. Sauvegardes et restauration

- `bbcloud-sauvegarde.timer` : tous les jours à 2 h, `sqlite3 .backup` vers `/mnt/sauvegardes` (compressé, 30 jours conservés ; réglable dans `/etc/bbcloud/sauvegarde.env`).
- Lancer une sauvegarde : `systemctl start bbcloud-sauvegarde.service`
- Restaurer :
  ```bash
  systemctl stop bbcloud-campagne.timer
  gunzip -c /mnt/sauvegardes/bleublanccloud-AAAA-MM-JJ.db.gz > /opt/bleu-blanc-cloud/donnees/bleublanccloud.db
  chown bbcloud:bbcloud /opt/bleu-blanc-cloud/donnees/bleublanccloud.db
  systemctl start bbcloud-campagne.timer
  ```
- Pense aussi à inclure le conteneur dans tes sauvegardes Proxmox (*Datacenter → Backup*).

---

## 8. Miroir du code sur Codeberg

Codeberg → **+** → *Nouvelle migration* → *GitHub* → URL `https://github.com/Berachem/bleu-blanc-cloud` → coche **« Ce dépôt sera un miroir »**. Codeberg se synchronise ensuite automatiquement.

---

## 9. Avant d'ouvrir le site au public ✅

- [ ] **Mentions légales** : complète `site/src/config.ts` (adresse de l'éditeur ou recours à l'anonymat LCEN, adresse de contact) — l'adresse de l'hébergeur Codeberg e.V. est aussi à vérifier.
- [ ] **Adresse de contact** pour les retraits et corrections (`SITE.contact`, actuellement `contact@berachem.dev`).
- [ ] **Référentiels** : relire les faits marqués « à vérifier » (`uv run bbcloud referentiels verifier` liste les remarques), puis passer `a_verifier: false` fait par fait.
- [ ] **Campagne de test** (10 organisations) relue sur le site local.
- [ ] **Première campagne complète** lancée puis publiée.
- [ ] **Dogfooding** : `bbcloud scanner bleublanccloud.berachem.dev` donne A.

Toute modification de ces fichiers se fait dans le dépôt GitHub (le conteneur récupère la dernière version chaque dimanche par `git pull`).

---

## 10. Opérations courantes

| Besoin | Action |
|---|---|
| Demande de **retrait** d'une organisation | ajouter le domaine dans `scanner/src/bleublanccloud/referentiels/retraits.yaml`, committer ; il n'est plus jamais analysé et sa fiche disparaît à la publication suivante |
| Ajouter un **hébergeur** non identifié | compléter `fournisseurs.yaml` (avec sources) à partir de `bbcloud referentiels inconnus` |
| Changer la **méthodologie** | nouvelle version dans `analyse/score.py` + entrée dans `docs/methodologie.md` |
| Changer les **consignes IA** | incrémenter `VERSION_INVITE` dans `ia/invites.py` (les rapports seront régénérés) |
| Mettre à jour le code tout de suite | `su - bbcloud -c 'cd /opt/bleu-blanc-cloud && git pull && cd scanner && uv sync'` |

---

## 11. Dépannage

| Symptôme | Piste |
|---|---|
| `referentiels maj` : « IPINFO_TOKEN absent » | normal sans jeton : le scanner interroge RIPEstat (plus lent). Ajoute `IPINFO_TOKEN` dans `.env`. |
| Hébergeurs souvent « inconnus » | lancer `referentiels maj` ; compléter `fournisseurs.yaml` avec `referentiels inconnus`. |
| `Permission denied (publickey)` à la publication | la clé de déploiement Codeberg n'a pas l'accès en écriture, ou `DEPOT_PAGES` n'est pas en SSH. Test : `su - bbcloud -c 'ssh -T git@codeberg.org'`. |
| Le site affiche encore une ancienne version / pas de HTTPS | vérifier le CNAME (« DNS only »), patienter quelques minutes, contrôler la branche `pages` du dépôt Codeberg. |
| `npm run build` échoue par manque de mémoire | passer le conteneur à 3–4 Go de RAM. |
| Beaucoup de « robots.txt injoignable » | réseau sortant filtré ou sites en panne : le robot n'analyse alors aucune page, par respect de la RFC 9309. |
| Rapports IA en erreur | `journalctl -u bbcloud-campagne` ; vérifier la clé et le quota Mistral ; les rapports en erreur sont retentés à la campagne suivante. |
