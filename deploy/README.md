# Mise en production sur Proxmox — guide pas à pas 🇫🇷

Ce guide installe Bleu Blanc Cloud dans un **conteneur LXC Debian 12** sur ton Proxmox, puis publie le site sur **Codeberg Pages** à l'adresse `https://bleublanccloud.fr`.

> 🔀 **Le site était auparavant publié sur `bleublanccloud.berachem.dev`** : pour basculer un serveur existant vers `bleublanccloud.fr`, suis la [section 4.6 « Migration depuis bleublanccloud.berachem.dev »](#46-migration-depuis-bleublanccloudberachemdev).

⏱️ Compter environ **1 heure** la première fois. Tout est déjà prêt dans le dépôt : il reste à créer le conteneur, lancer le script d'installation et renseigner quelques clés.

```
Proxmox (chez toi)                                    Internet
┌──────────────────────────────────────────┐
│ LXC Debian 12 « bbcloud »                 │   git push   ┌────────────────────────┐
│  timer systemd (dimanche 3 h)             │ ───────────▶ │ Codeberg Pages (DE)    │
│   référentiels → campagne → rapports IA   │              │ bleublanccloud.fr      │
│   → export JSON → build Astro → publier   │              │                        │
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
| Le domaine `bleublanccloud.fr` et l'accès à sa zone DNS | OVHcloud (*Web Cloud → Noms de domaine*) | oui |
| Une clé API **Mistral** | <https://console.mistral.ai> → *API Keys* | pour les rapports IA |
| Un jeton **IPinfo** gratuit (base IP → ASN) | <https://ipinfo.io/signup> | recommandé (sinon repli sur RIPEstat, plus lent) |

> 💡 Le dépôt GitHub `Berachem/bleu-blanc-cloud` peut rester **privé** : l'installateur le détecte et configure une clé de déploiement en lecture seule (étape 2). Pense seulement à le passer en public avant d'ouvrir le site, car le site renvoie vers le code source.

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

### 2.1 Déposer le script dans le conteneur

Entre dans le conteneur en root (`pct enter 120` depuis l'hôte, ou la console du conteneur dans l'interface Proxmox), puis :

**Dépôt public**

```bash
apt-get update && apt-get install -y curl
curl -fsSLO https://raw.githubusercontent.com/Berachem/bleu-blanc-cloud/main/deploy/installer.sh
```

**Dépôt privé** — au choix :

- **Avec un jeton GitHub temporaire** (le plus simple) : crée un [jeton « fine-grained »](https://github.com/settings/personal-access-tokens/new) limité au dépôt `bleu-blanc-cloud`, permission *Contents : Read-only*, expiration 1 jour, puis :
  ```bash
  apt-get update && apt-get install -y curl
  read -rs -p "Jeton GitHub : " JETON && echo
  curl -fsSL -H "Authorization: Bearer $JETON" -H "Accept: application/vnd.github.raw+json" \
    https://api.github.com/repos/Berachem/bleu-blanc-cloud/contents/deploy/installer.sh -o installer.sh
  unset JETON
  ```
  Supprime ensuite le jeton sur GitHub : il ne sert qu'à cette étape.
- **Par copier-coller** : ouvre `deploy/installer.sh` sur GitHub, copie son contenu, puis dans le conteneur `nano installer.sh`, colle, enregistre (`Ctrl+O`, `Entrée`, `Ctrl+X`).

### 2.2 Lancer l'installation

```bash
bash installer.sh
```

Le script (idempotent, relançable sans risque) :

- installe `git`, `sqlite3`, **Node.js 22 LTS** (binaire officiel, somme de contrôle vérifiée) et **uv** ;
- crée l'utilisateur système `bbcloud` ;
- **détecte si le dépôt est public ou privé** :
  - public : clone en HTTPS ;
  - privé : génère une **clé de déploiement GitHub en lecture seule**, l'affiche avec le lien direct vers *Settings → Deploy keys → Add deploy key* du dépôt, et **attend** que tu l'ajoutes (laisse « Allow write access » décoché), puis clone en SSH. La clé d'hôte de GitHub est épinglée (empreinte officielle vérifiée) ;
- installe les dépendances Python et Node ;
- crée `/opt/bleu-blanc-cloud/.env` à partir de `.env.example` (droits `600`) ;
- génère une **clé SSH de publication** pour Codeberg et l'affiche ;
- installe les services systemd, active la **sauvegarde quotidienne** et laisse le **timer de campagne désactivé** jusqu'à ta validation.

Les mises à jour automatiques du code (`bbcloud-maj-auto`, toutes les heures) utilisent ensuite la même clé de déploiement.

> Options : `AVEC_CHROMIUM=1 bash installer.sh` installe Chromium pour que chaque publication vérifie automatiquement l'absence de requête externe et de cookie (≈ 300 Mo). `DEPOT_PRIVE=1` ou `DEPOT_PRIVE=0` force le mode si la détection automatique se trompe.
>
> Si tu passes plus tard le dépôt en public, rien à changer : l'accès par clé de déploiement continue de fonctionner (tu peux aussi relancer `bash installer.sh`, qui repassera en HTTPS).

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
| `CODEBERG_JETON` | jeton des analyses sur demande (étape 6 bis) ; vide = fonctionnalité désactivée |
| `DEPOT_DEMANDES` | `<ton-pseudo>/bleublanccloud-pages` : dépôt où les visiteurs ouvrent leurs tickets |

Les autres valeurs (politesse du robot, chemins) peuvent rester telles quelles.

---

## 4. Codeberg Pages (git-pages) et nom de domaine

Codeberg impose désormais **git-pages** aux nouveaux comptes : l'ancien serveur Pages v2 (fichier `.domains`) ne fonctionne plus pour eux. Avec git-pages, le domaine est **autorisé par le DNS** (enregistrement TXT) et chaque déploiement est **déclenché par un webhook** sur la branche `pages`.

Fais ces étapes **dans l'ordre, avant la première publication** (étape 5) : le certificat HTTPS n'est demandé qu'au premier déploiement réussi.

### 4.1 Dépôt de publication

1. Sur Codeberg, crée un dépôt **public et vide** nommé `bleublanccloud-pages` (git-pages le clone en HTTPS, sans identifiant).
2. *Paramètres du dépôt → Clés de déploiement → Ajouter une clé* : colle la clé publique affichée par l'installateur
   (ou `cat /home/bbcloud/.ssh/id_ed25519_codeberg.pub`) et coche **Activer l'accès en écriture** : c'est elle que `publier.sh` utilise pour pousser.
3. Après la première publication, vérifie que **`pages` est la branche par défaut** du dépôt (*Paramètres → Branches*) : c'est le cas automatiquement si le dépôt était vide. Forgejo y lit le modèle de ticket « Analyser mon site » (étape 6 bis).

### 4.2 Enregistrements DNS (zone OVHcloud de `bleublanccloud.fr`)

Console OVHcloud : *Web Cloud → Noms de domaine → `bleublanccloud.fr` → Zone DNS*. Ne touche ni aux enregistrements **NS** (`dnsXX.ovh.net` / `nsXX.ovh.net`) ni à **DNSSEC** : OVHcloud re-signe la zone automatiquement à chaque modification.

**1. Supprimer les enregistrements de parking** créés par OVHcloud à l'achat (repère-les dans la zone, leurs valeurs varient) :

| Type | Sous-domaine | Pourquoi |
|---|---|---|
| `A` (et `AAAA` s'il existe) | *(vide)*, c'est-à-dire l'apex `bleublanccloud.fr` | adresse de la page de parking OVHcloud, remplacée par Codeberg Pages |
| `A`, `AAAA` ou `CNAME` | `www` | remplacé par le `CNAME` ci-dessous |
| `TXT` de valeur `"1\|www.bleublanccloud.fr"` | *(vide)* | marqueur de la redirection web OVHcloud, s'il existe |

> ⚠️ Si l'onglet **Redirection** du domaine contient une redirection, supprime-la d'abord : sinon OVHcloud recrée ses propres `A`/`TXT`.

**2. Créer** (dans le formulaire OVHcloud, le champ *Sous-domaine* vide désigne l'apex) :

| Type | Sous-domaine | Cible / valeur | Rôle |
|---|---|---|---|
| `A` | *(vide)* | `217.197.84.141` | apex → Codeberg Pages |
| `AAAA` | *(vide)* | `2a0a:4580:103f:c0de::2` | apex → Codeberg Pages (IPv6) |
| `TXT` | `_git-pages-repository` | `https://codeberg.org/berachem/bleublanccloud-pages.git` | autorise le dépôt du site à publier sur l'apex |
| `CNAME` | `www` | `codeberg.page.` | `www` → Codeberg Pages |
| `TXT` | `_git-pages-repository.www` | `https://codeberg.org/berachem/bleublanccloud-redirection.git` | autorise le dépôt de redirection (étape 4.5) sur `www` |

- Un apex ne peut pas porter de `CNAME` : on y met les adresses de `codeberg.page` indiquées par la documentation de Codeberg (vérifiées le 30 septembre 2026 avec `dig +short A codeberg.page` et `AAAA`). Si Codeberg en change un jour, il faudra les mettre à jour ; le `CNAME` de `www` suit tout seul. (`www` peut aussi recevoir les mêmes `A`/`AAAA` que l'apex, mais le `CNAME` est préférable.)
- Le **TXT** contient l'**URL HTTPS de clonage** du dépôt (avec `.git`) ; OVHcloud ajoute lui-même les guillemets.
- Aucun `CAA` n'existe par défaut. Si tu en ajoutes un, il doit autoriser Let's Encrypt : `0 issue "letsencrypt.org"`.

**3. Messagerie** (au choix) :

- **Aucune adresse sur `bleublanccloud.fr`** (recommandé tant que le contact reste `contact@berachem.dev`) : supprime les `MX` OVHcloud (`mx1`, `mx2`, `mx3.mail.ovh.net`), le `TXT` SPF `v=spf1 include:mx.ovh.com ~all` et les enregistrements `autoconfig` / `autodiscover` / `_autodiscover._tcp`, puis protège le domaine contre l'usurpation :

  | Type | Sous-domaine | Valeur |
  |---|---|---|
  | `MX` | *(vide)* | priorité `0`, cible `.` (« MX nul », RFC 7505 ; si l'interface refuse `.`, ne mets simplement aucun `MX`) |
  | `TXT` | *(vide)* | `v=spf1 -all` |
  | `TXT` | `_dmarc` | `v=DMARC1; p=reject;` |

- **Une adresse `contact@bleublanccloud.fr` chez OVHcloud** (messagerie française, qui remplacerait l'actuelle adresse relayée par un service américain) : garde les `MX` et le SPF OVHcloud. Le site reste à 100/100 sur son propre scan.

Vérifie la propagation (depuis n'importe quelle machine ; dans le conteneur : `apt-get install -y dnsutils`) :

```bash
dig +short NS bleublanccloud.fr                              # → serveurs OVHcloud (sinon : domaine pas encore actif)
dig +short A bleublanccloud.fr                               # → 217.197.84.141
dig +short AAAA bleublanccloud.fr                            # → 2a0a:4580:103f:c0de::2
dig +short TXT _git-pages-repository.bleublanccloud.fr       # → "https://codeberg.org/berachem/bleublanccloud-pages.git"
dig +short CNAME www.bleublanccloud.fr                       # → codeberg.page.
dig +short TXT _git-pages-repository.www.bleublanccloud.fr   # → "https://codeberg.org/berachem/bleublanccloud-redirection.git"
dig +dnssec A bleublanccloud.fr | grep RRSIG                 # une signature : DNSSEC actif
```

### 4.3 Webhook de déploiement

Avec git-pages, **chaque domaine est un site distinct** : un déploiement ne concerne que le domaine de l'URL du webhook, et seulement si le `TXT` `_git-pages-repository` de ce domaine autorise le dépôt. Le dépôt du site n'a donc qu'**un seul webhook**, vers `bleublanccloud.fr`.

Dans le dépôt `bleublanccloud-pages` : *Paramètres → Webhooks → Ajouter un webhook → **Forgejo***.

| Champ | Valeur |
|---|---|
| URL cible | `http://bleublanccloud.fr/` (**http://** pour le tout premier déploiement, voir ci-dessous) |
| Méthode HTTP | `POST` |
| Type de contenu | `application/json` |
| Déclencheur | *Évènements de push* uniquement |
| Filtre de branche | `pages` |
| Actif | coché |

- **Pourquoi `http://` ?** Au premier déploiement, le certificat HTTPS du domaine **n'existe pas encore** : une URL en `https://` ferait échouer la livraison (erreur TLS), donc aucun déploiement, donc jamais de certificat.
- N'utilise **pas** le bouton *Tester la livraison* : il échoue toujours avec git-pages, c'est normal. Le vrai test est un push sur `pages`.
- Le **filtre de branche** évite qu'un push sur une autre branche ne déclenche un déploiement.

### 4.4 Premier déploiement et passage en HTTPS

1. Lance la première publication (étape 5, point 7 : `uv run bbcloud publier`). Le push sur `pages` déclenche le webhook : git-pages récupère le site, le publie et demande le certificat Let's Encrypt.
2. Contrôle la livraison dans *Paramètres → Webhooks → (ton webhook) → Livraisons récentes* : un code **2xx** est attendu.
3. Après quelques minutes, `https://bleublanccloud.fr` doit répondre avec un certificat valide (`curl -sI https://bleublanccloud.fr`).
4. **Modifie alors l'URL cible du webhook en `https://bleublanccloud.fr/`** : une fois le certificat émis, le serveur peut rediriger le HTTP vers le HTTPS, ce qui ferait échouer les livraisons suivantes.

> 💡 **Publication faite avant le webhook ?** Le site n'est alors pas déployé et une nouvelle publication sans changement ne pousse rien. Relance la dernière livraison depuis *Livraisons récentes* (bouton de renvoi), ou pousse un commit vide sur `pages` :
> ```bash
> su - bbcloud -c 'cd /opt/bleu-blanc-cloud/donnees/depot-pages && git commit --allow-empty -qm "redéploiement" && git push -q origin pages'
> ```

> ℹ️ `publier.sh` écrit toujours un fichier `.domains` (valeur de `DOMAINE_SITE`) : git-pages l'ignore (l'autorisation passe par le TXT), il ne sert qu'aux comptes encore sur l'ancien serveur. git-pages ne redirige plus `/page` vers `/page.html`, ce qui ne gêne pas le site : Astro génère des dossiers (`/methodologie/index.html`) et les liens internes se terminent par `/`.

> 💡 Avec Codeberg Pages (Allemagne, réseau de l'association IN-Berlin) et la zone DNS chez OVHcloud (France), le site obtient **100/100** sur son propre scan.

### 4.5 Redirection de `www` (dépôt de redirection)

Comme chaque domaine est un site distinct, `www` ne peut pas être redirigé par le dépôt du site (le même contenu y serait servi en double). Un petit dépôt dédié, dont le fichier `_redirects` renvoie **toutes** les adresses vers l'apex par une redirection permanente (`/* https://bleublanccloud.fr/:splat 301!`, chemin et paramètres conservés), s'en charge. Son contenu est prêt dans [`deploy/redirection/`](redirection/). Le même dépôt sert à l'ancien domaine (étape 4.6).

1. Sur Codeberg, crée un dépôt **public et vide** nommé `bleublanccloud-redirection`.
2. *Paramètres → Webhooks → Ajouter un webhook → Forgejo*, mêmes réglages qu'à l'étape 4.3 (POST, `application/json`, push uniquement, filtre de branche `pages`), avec l'URL cible **`http://www.bleublanccloud.fr/`**.
3. Vérifie que le `TXT` `_git-pages-repository.www.bleublanccloud.fr` est en place (étape 4.2), puis **pousse le contenu sur la branche `pages`** : ce push déclenche le déploiement.
   - Depuis ton ordinateur (clé SSH enregistrée dans ton compte Codeberg) :
     ```bash
     cp -r bleu-blanc-cloud/deploy/redirection /tmp/redirection && cd /tmp/redirection
     git init -q -b pages && git add . && git commit -qm "Redirection vers bleublanccloud.fr"
     git push git@codeberg.org:berachem/bleublanccloud-redirection.git pages
     ```
   - Ou dans l'interface web : téléverse `_redirects`, `index.html` et `README.md`, crée une branche `pages` à partir de ce commit, puis modifie une ligne de `README.md` **sur la branche `pages`** pour déclencher un push sur cette branche.
4. Après quelques minutes, repasse l'URL du webhook en **`https://www.bleublanccloud.fr/`**.
5. Contrôle : `curl -sI https://www.bleublanccloud.fr/methodologie/` doit répondre `301` avec `location: https://bleublanccloud.fr/methodologie/`.

### 4.6 Migration depuis bleublanccloud.berachem.dev

Pour un serveur déjà en service sur l'ancienne adresse. **L'ordre compte** : le site reste en ligne à chaque étape.

1. **Domaine actif** : `dig +short NS bleublanccloud.fr` doit renvoyer les serveurs OVHcloud (un domaine tout juste acheté peut mettre un peu de temps à apparaître dans la zone `.fr`).
2. **DNS OVHcloud** : étape 4.2, puis attends que les `dig` répondent.
3. **Code du serveur** : la mise à jour automatique (étape 6) installe le nouveau code. Tant que le `.env` du serveur contient `DOMAINE_SITE=bleublanccloud.berachem.dev`, le site continue d'être construit pour l'ancienne adresse : rien ne change encore.
4. **Webhook du dépôt `bleublanccloud-pages`** : remplace son URL cible par **`http://bleublanccloud.fr/`** (étape 4.3). L'ancien domaine ne reçoit plus de mises à jour mais reste en ligne tel quel.
5. **`.env` du serveur** (`nano /opt/bleu-blanc-cloud/.env`) :
   - `DOMAINE_SITE=bleublanccloud.fr` ;
   - **supprime la ligne `USER_AGENT=`** : le User-Agent est désormais construit à partir de `DOMAINE_SITE` (`BleuBlancCloudBot/1.0 (+https://bleublanccloud.fr/methodologie)`).
6. **Republication** : `su - bbcloud -c 'cd /opt/bleu-blanc-cloud/scanner && uv run bbcloud publier'`. Les URL canoniques, le plan du site, `robots.txt`, les liens du modèle de ticket et les réponses aux tickets passent à `bleublanccloud.fr` ; le push déclenche le premier déploiement sur le nouveau domaine. Puis étape 4.4 (livraison 2xx, certificat, webhook en `https://`).
7. **Redirection de l'ancien domaine** :
   1. dépôt `bleublanccloud-redirection` et redirection de `www` : étape 4.5 ;
   2. ajoute dans ce dépôt un second webhook (mêmes réglages) vers **`https://bleublanccloud.berachem.dev/`** : son certificat existe déjà, `https://` fonctionne tout de suite ;
   3. dans la zone de `berachem.dev` (Cloudflare), **remplace la valeur du `TXT` `_git-pages-repository.bleublanccloud`** par `https://codeberg.org/berachem/bleublanccloud-redirection.git`. **Garde le `CNAME` `bleublanccloud` → `codeberg.page.`** (toujours en « DNS only ») ;
   4. déclenche un déploiement du dépôt de redirection (nouveau push sur `pages`, par exemple une ligne modifiée dans `README.md`) ;
   5. contrôle : `curl -sI https://bleublanccloud.berachem.dev/carte/` → `301`, `location: https://bleublanccloud.fr/carte/`.
8. **Finitions** : adresse du site dans la description des dépôts GitHub et Codeberg ; `uv run bbcloud scanner bleublanccloud.fr` (A attendu) ; garde les enregistrements de `berachem.dev` **au moins un an** pour que les anciens liens continuent de rediriger.

> ℹ️ Inutile de relancer `installer.sh` : il ne gère pas le domaine (il ne crée le `.env` que s'il n'existe pas) et les services systemd sont inchangés.

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
   uv run bbcloud scores couverture                       # part du poids encore inconnue
   ```
5. **Rapports IA** :
   ```bash
   uv run bbcloud rapports generer --max 3 --dry-run      # nombre d'appels et coût estimés
   uv run bbcloud rapports generer --max 3
   ```
6. **Contours des communes** (carte de situation des fiches) : téléchargés automatiquement par `cibles importer`, un par code INSEE sur `geo.api.gouv.fr` (licence Etalab 2.0), simplifiés puis stockés en base ; seuls les manquants sont redemandés. Pour les (re)télécharger à part :
   ```bash
   uv run bbcloud cibles contours            # contours manquants seulement
   uv run bbcloud cibles contours --forcer   # tout retélécharger (rarement utile)
   ```
7. **Aperçu local du site** (depuis ton réseau, sur `http://<IP-du-conteneur>:4321`) :
   ```bash
   uv run bbcloud exporter
   cd ../site && npm run build && npx astro preview --host 0.0.0.0
   ```
8. **Publication**, puis **dogfooding** (le site doit obtenir A) :
   ```bash
   cd ../scanner
   uv run bbcloud publier
   uv run bbcloud scanner bleublanccloud.fr
   ```
   Au premier push, vérifie la livraison du webhook puis repasse son URL en `https://` (étape 4.4).

---

## 6. Automatiser

```bash
exit                                               # retour en root
systemctl enable --now bbcloud-campagne.timer      # chaque dimanche à 3 h (heure de Paris)
systemctl list-timers 'bbcloud*'
```

- Lancer la chaîne complète tout de suite : `systemctl start bbcloud-campagne.service`
- Suivre les journaux : `journalctl -u bbcloud-campagne -f`
- La chaîne hebdomadaire (`deploy/campagne-hebdomadaire.sh`) : `uv sync` → `referentiels maj` → `cibles importer` (et contours des nouvelles communes) → `campagne lancer --oui` → `scores recalculer` → `rapports generer --oui` (seulement si la clé Mistral est présente ; le cache évite tout appel si rien n'a changé) → `publier`.
- Durée indicative d'une campagne complète (~1 000 organisations, 1 requête/s/domaine, 10 scans en parallèle) : **30 à 60 minutes**.

### Mise à jour automatique du code (toutes les heures)

`bbcloud-maj-auto.timer` est activé par l'installateur. Chaque heure, `deploy/maj-auto.sh` :

1. fait un `git fetch` et **s'arrête aussitôt s'il n'y a rien de nouveau** sur `main` ;
2. sinon : `git merge --ff-only`, `uv sync`, puis `npm ci` **seulement si** `site/package-lock.json` a changé ;
3. lance les tests (`pytest`) ;
4. **uniquement s'ils passent**, régénère et publie le site à partir des données déjà en base (export → build → push), **sans relancer de scan**. Auparavant, les scores sont recalculés si les référentiels ont changé (`scores recalculer`), et les contours de communes manquants sont téléchargés (`cibles contours`, aucune requête s'ils sont tous en base). Tant que la base ne contient aucune organisation notée, rien n'est publié.

Si les tests échouent, le serveur **revient à la version précédente**, rien n'est publié, le service passe en échec (`systemctl --failed`) et ce commit n'est plus retenté : il faut pousser un correctif.

Un verrou (`flock` sur `donnees/bbcloud.verrou`) empêche la mise à jour et la campagne hebdomadaire de tourner en même temps : pendant une campagne, la mise à jour est reportée à l'heure suivante ; pendant une mise à jour, la campagne attend sa fin (2 h au maximum). La campagne ne tire plus le code elle-même : elle tourne toujours sur une version qui a passé les tests.

```bash
systemctl start bbcloud-maj-auto.service   # lancer une vérification tout de suite
journalctl -u bbcloud-maj-auto -f          # suivre les journaux (priorités : -p warning pour les alertes)
systemctl list-timers 'bbcloud*'           # prochaines exécutions
systemctl disable --now bbcloud-maj-auto.timer   # suspendre les mises à jour automatiques
```

> ⚠️ La mise à jour automatique récupère le code, mais **n'installe pas de nouveaux services systemd**. Quand une version en ajoute (par exemple `bbcloud-demandes`, étape 6 bis), relance simplement `bash installer.sh` en root : il est idempotent.

---

## 6 bis. Analyses sur demande (« Analyser mon site »)

Le bouton « Analyser mon site » ouvre une fenêtre qui propose d'abord un **ticket** sur le dépôt Codeberg `bleublanccloud-pages` (automatique), puis un **e-mail** à l'adresse `SITE.contact` de `site/src/config.ts` (traitement manuel, voir plus bas). Toutes les heures (à la demie), `bbcloud-demandes.timer` lance `bbcloud demandes traiter`, qui lit les tickets via l'API Codeberg, valide le domaine, lance l'analyse passive, publie la fiche et répond dans le ticket. **Aucun port entrant** : c'est le serveur qui va chercher les tickets.

### Étiquettes

Dans le dépôt `bleublanccloud-pages` : *Tickets → Étiquettes → Nouvelle étiquette*, crée ces quatre étiquettes (noms exacts, accents compris) :

| Étiquette | Rôle | Couleur suggérée |
|---|---|---|
| `analyse` | posée automatiquement par le formulaire : c'est une demande | `#003399` |
| `traitée` | le robot a répondu avec la fiche | `#2E7D32` |
| `refusée` | domaine invalide, retrait, limite atteinte… (la raison est expliquée) | `#6B7280` |
| `erreur` | erreur technique ; nouvel essai automatique (3 tentatives au maximum) | `#ED2939` |

Vérifie aussi que les **tickets sont activés** (*Paramètres → Unités → Tickets*).

### Jeton Codeberg aux droits minimaux

1. Codeberg → avatar → *Paramètres → Applications → Générer un nouveau jeton*.
2. **Nom** : `bbcloud-demandes`.
3. **Accès aux dépôts** : **Dépôts spécifiques** → sélectionne uniquement `bleublanccloud-pages`.
4. **Permissions** : `issue` en **Lecture et écriture** ; **tout le reste sans accès**.
5. Copie le jeton (il ne sera plus affiché) dans `/opt/bleu-blanc-cloud/.env` : `CODEBERG_JETON=…` (le fichier est en droits `600`).

Le jeton n'apparaît jamais dans les journaux ni dans les réponses. Les réponses du robot sont publiées au nom du compte qui a créé le jeton ; pour une identité séparée, crée un compte robot dédié, ajoute-le comme collaborateur (droit *Écriture*) de `bleublanccloud-pages` et génère le jeton depuis ce compte.

### Activer et tester

```bash
bash installer.sh                                   # installe et active bbcloud-demandes.timer
su - bbcloud -c 'cd /opt/bleu-blanc-cloud/scanner && uv run bbcloud demandes lister'
```

Ouvre ensuite un ticket de test depuis le bouton du site, **avec le domaine `berachem.dev`** (domaine autorisé pour les tests), puis :

```bash
systemctl start bbcloud-demandes.service   # traitement immédiat au lieu d'attendre la demie
journalctl -u bbcloud-demandes -e          # journaux du traitement
```

Le ticket doit recevoir une réponse (note, score, lien vers la fiche), l'étiquette `traitée`, puis être fermé.

### Règles appliquées

- **Validation stricte** : nom de domaine seul (punycode accepté), ni chemin, ni port, ni adresse IP, ni `localhost` / `.local` / `.internal`… ; un domaine qui résout vers une adresse privée ou locale est refusé. La case d'engagement doit être cochée. `retraits.yaml` est respecté.
- **Garde réseau** : pour tous les scans (campagnes comprises), le robot refuse de se connecter à une adresse non publique, même après une redirection.
- **Limites** : 10 demandes acceptées par jour au total, 1 par jour et par compte (`DEMANDES_LIMITE_JOUR`, `DEMANDES_LIMITE_COMPTE`). Une analyse de moins de 7 jours est réutilisée.
- **Fiches « sur demande »** : visibles par leur lien et la recherche, exclues de la carte, des classements et des statistiques, jamais rescannées par la campagne hebdomadaire. Si le domaine appartient déjà à une organisation de l'observatoire, c'est sa fiche qui est mise à jour.
- **Rapport IA** : généré avec le cache habituel si `MISTRAL_API_KEY` est renseignée (10 rapports par jour au plus).
- Le compte Codeberg de l'auteur est conservé dans la base locale pour appliquer les limites ; il n'est jamais publié et `bbcloud demandes traiter` l'efface au bout de 30 jours (durée annoncée dans les mentions légales ; les sauvegardes, gardées 30 jours, suivent).
- Même **verrou** que la campagne et la mise à jour automatique : si l'une d'elles tourne, le traitement est reporté au passage suivant.

---

## 7. Sauvegardes et restauration

- `bbcloud-sauvegarde.timer` : tous les jours à 2 h, `sqlite3 .backup` vers `/mnt/sauvegardes` (compressé, 30 jours conservés ; réglable dans `/etc/bbcloud/sauvegarde.env`).
- Lancer une sauvegarde : `systemctl start bbcloud-sauvegarde.service`
- Restaurer :
  ```bash
  systemctl stop bbcloud-campagne.timer bbcloud-maj-auto.timer bbcloud-demandes.timer
  gunzip -c /mnt/sauvegardes/bleublanccloud-AAAA-MM-JJ.db.gz > /opt/bleu-blanc-cloud/donnees/bleublanccloud.db
  chown bbcloud:bbcloud /opt/bleu-blanc-cloud/donnees/bleublanccloud.db
  systemctl start bbcloud-campagne.timer bbcloud-maj-auto.timer bbcloud-demandes.timer
  ```
- Pense aussi à inclure le conteneur dans tes sauvegardes Proxmox (*Datacenter → Backup*).

---

## 8. Miroir du code sur Codeberg

Codeberg → **+** → *Nouvelle migration* → *GitHub* → URL `https://github.com/Berachem/bleu-blanc-cloud` → coche **« Ce dépôt sera un miroir »**. Codeberg se synchronise ensuite automatiquement.

Tant que le dépôt GitHub est privé, renseigne dans le formulaire de migration un jeton GitHub en lecture seule (champ du jeton d'accès), ou attends simplement le passage en public pour créer le miroir.

---

## 9. Avant d'ouvrir le site au public ✅

- [ ] **Mentions légales** : l'adresse de l'éditeur n'est pas publiée (régime des particuliers non professionnels, LCEN art. 1-1 II). Condition : avoir **communiqué ton identité (nom, prénom, adresse) à Codeberg e.V.**, par exemple par e-mail à `contact@codeberg.org` en indiquant le dépôt Pages concerné. Garde une trace de l'envoi.
- [ ] **Adresse de contact** `contact@berachem.dev` (`SITE.contact`) : vérifier qu'elle arrive bien dans ta boîte (mentions légales, retraits, demandes par e-mail).
- [ ] **Référentiels** : relire les faits marqués « à vérifier » (`uv run bbcloud referentiels verifier` liste les remarques), puis passer `a_verifier: false` fait par fait.
- [ ] **Campagne de test** (10 organisations) relue sur le site local.
- [ ] **Première campagne complète** lancée puis publiée.
- [ ] **Webhook Codeberg** repassé en `https://` après l'émission du certificat (étape 4.4).
- [ ] **Analyses sur demande** : étiquettes créées, jeton renseigné, ticket de test traité (étape 6 bis).
- [ ] **Dogfooding** : `bbcloud scanner bleublanccloud.fr` donne A (100/100 attendu : Codeberg Pages via le réseau IN-Berlin, DNS chez OVHcloud).
- [ ] **Redirections** : `www.bleublanccloud.fr` et `bleublanccloud.berachem.dev` renvoient une 301 vers `https://bleublanccloud.fr/` (étapes 4.5 et 4.6).
- [ ] **Dépôt GitHub passé en public** : le site renvoie vers le code source, la méthodologie et les référentiels.

Toute modification de ces fichiers se fait dans le dépôt GitHub : le conteneur récupère la nouvelle version dans l'heure (`bbcloud-maj-auto`), après passage des tests, et republie le site.

---

## 10. Opérations courantes

| Besoin | Action |
|---|---|
| Demande de **retrait** d'une organisation | ajouter le domaine dans `scanner/src/bleublanccloud/referentiels/retraits.yaml`, committer ; il n'est plus jamais analysé et sa fiche disparaît à la publication suivante |
| Ajouter un **hébergeur** non identifié | compléter `fournisseurs.yaml` (avec sources) à partir de `bbcloud referentiels inconnus` ; ne pas y ajouter les **réseaux de transit** (tableau à part), à déclarer dans `transitaires.yaml` |
| Appliquer un référentiel mis à jour **sans rescanner** | automatique : `bbcloud-maj-auto` lance `bbcloud scores recalculer` quand les référentiels changent. À la main : `uv run bbcloud scores recalculer --dry-run` (aperçu des notes modifiées), puis sans `--dry-run`, puis `uv run bbcloud publier`. Les rapports IA des fiches modifiées sont retirés jusqu'au prochain `rapports generer` |
| Mesurer le **poids encore inconnu** de l'observatoire | `uv run bbcloud scores couverture` |
| Changer la **méthodologie** | nouvelle version dans `analyse/score.py` + entrée dans `docs/methodologie.md` |
| Changer les **consignes IA** | incrémenter `VERSION_INVITE` dans `ia/invites.py` (les rapports seront régénérés) |
| Mettre à jour le code tout de suite | `systemctl start bbcloud-maj-auto.service` (tests puis republication) |
| Traiter une **demande reçue par e-mail** | vérifier que la demande concerne le site du demandeur ou d'un organisme public, puis `su - bbcloud -c 'cd /opt/bleu-blanc-cloud/scanner && uv run bbcloud demandes analyser mairie-exemple.fr'` : mêmes contrôles qu'un ticket (domaine, retraits, adresses publiques), fiche « sur demande » (ou fiche existante de l'observatoire), publication du site, puis réponse type à copier dans l'e-mail |
| Voir les **demandes d'analyse** en attente | `su - bbcloud -c 'cd /opt/bleu-blanc-cloud/scanner && uv run bbcloud demandes lister'` |
| Suspendre les **demandes d'analyse** | `systemctl disable --now bbcloud-demandes.timer` (ou vider `CODEBERG_JETON`) |
| Relancer une demande **refusée ou en échec** | demander au visiteur d'ouvrir un nouveau ticket : un ticket fermé puis rouvert n'est plus traité par le robot |

---

## 11. Dépannage

| Symptôme | Piste |
|---|---|
| `referentiels maj` : « IPINFO_TOKEN absent » | normal sans jeton : le scanner interroge RIPEstat (plus lent). Ajoute `IPINFO_TOKEN` dans `.env`. |
| Hébergeurs souvent « inconnus » | lancer `referentiels maj` ; compléter `fournisseurs.yaml` avec `referentiels inconnus`, puis `scores recalculer`. |
| Un fournisseur ajouté reste « inconnu » dans `referentiels inconnus` | les constats enregistrés n'ont pas encore été réattribués : `uv run bbcloud scores recalculer` (lancé automatiquement par `bbcloud-maj-auto` quand le référentiel arrive par `git`). |
| « Origine indéterminée (réseau de transit) » sur une fiche | l'adresse est annoncée par un opérateur de transit (Cogent…) : l'hébergeur réel n'est pas identifiable par l'ASN. Chercher un nom d'hôte ou un en-tête révélateur ; ne pas ajouter le transitaire comme fournisseur. |
| `Permission denied (publickey)` sur **github.com** (dépôt privé) | la clé de déploiement n'est pas (ou plus) dans *Settings → Deploy keys* du dépôt. Clé à ajouter : `cat /home/bbcloud/.ssh/id_ed25519_github.pub`. Test : `su - bbcloud -c 'ssh -T git@github.com'` (réponse attendue : « successfully authenticated »). |
| L'installateur choisit le mauvais mode (public/privé) | relancer avec `DEPOT_PRIVE=1 bash installer.sh` ou `DEPOT_PRIVE=0 bash installer.sh`. |
| `Permission denied (publickey)` à la publication | la clé de déploiement Codeberg n'a pas l'accès en écriture, ou `DEPOT_PAGES` n'est pas en SSH. Test : `su - bbcloud -c 'ssh -T git@codeberg.org'`. |
| Message mentionnant l'**« old pages server »** | la requête arrive sur l'ancien serveur Pages v2, fermé aux nouveaux comptes. Causes possibles : CNAME encore à l'ancienne forme (`bleublanccloud-pages.<ton-pseudo>.codeberg.page.`) au lieu de `codeberg.page.` ; TXT `_git-pages-repository.bleublanccloud` absent ou différent de l'URL HTTPS exacte du dépôt (avec `.git`) ; aucun déploiement git-pages encore effectué (webhook absent, filtré sur une autre branche que `pages`, ou jamais déclenché). Corriger le DNS (`dig`, étape 4.2), vérifier le webhook, puis redéclencher un déploiement (étape 4.4). |
| **`tls: internal error`** (ou `tlsv1 alert internal error` avec curl, `SSL_ERROR_INTERNAL_ERROR_ALERT` dans Firefox) | le certificat HTTPS n'est pas (encore) émis. Il n'est demandé qu'après un **déploiement réussi par le webhook** : vérifier dans *Livraisons récentes* qu'une livraison a abouti (code 2xx) avec une URL cible en **`http://`** ; sinon corriger l'URL et relancer la livraison. Vérifier aussi : `A`/`AAAA` de l'apex exactement égaux à ceux de `codeberg.page` (et `CNAME` de `www` vers `codeberg.page.`), TXT présent, enregistrements CAA autorisant `letsencrypt.org`. Puis patienter quelques minutes. Outil officiel de diagnostic : `curl -fsSL https://troubleshoot.codeberg.page/verify.sh -o verify.sh`, relire le script, puis `bash verify.sh bleublanccloud.fr`. |
| Le site en ligne a un **ancien design** ou pas la dernière fonctionnalité | comparer la « Version du site » en pied de page avec le dernier commit du dépôt. Puis, sur le serveur : `systemctl status bbcloud-maj-auto.timer` (« Unit not found » : relancer `bash deploy/installer.sh` après un `git pull`) et `journalctl -u bbcloud-maj-auto -n 80 --no-pager`. « Tests en échec » ou « déjà rejeté » : corriger puis pousser un nouveau commit (jusqu'au commit qui isole les tests du `.env`, les tests échouaient sur le serveur à cause des vraies clés du `.env`) ; « Fusion en avance rapide impossible » : `git -C /opt/bleu-blanc-cloud status` et annuler les modifications locales. Forcer une vérification : `systemctl start bbcloud-maj-auto.service`. |
| Le site affiche encore une ancienne version | contrôler la branche `pages` du dépôt Codeberg et la dernière livraison du webhook (une URL cible restée en `http://` après l'émission du certificat peut faire échouer les livraisons : la passer en `https://`). |
| Une fiche de commune affiche l'illustration au lieu de la carte | contour pas encore téléchargé (serveur installé avant la carte de situation, ou `geo.api.gouv.fr` injoignable lors de l'import) : `uv run bbcloud cibles contours`, puis `uv run bbcloud publier`. Si le réseau sortant est filtré, autoriser `geo.api.gouv.fr`. |
| `cibles contours` : « introuvable » | code INSEE absent de `geo.api.gouv.fr` (commune fusionnée ou supprimée) : relancer `cibles importer` pour mettre la liste des cibles à jour. |
| Anciennes photos Wikimedia sur le serveur | elles ne servent plus (remplacées par la carte de situation). Nettoyage facultatif : `rm -rf /opt/bleu-blanc-cloud/donnees/photos` et `sqlite3 /opt/bleu-blanc-cloud/donnees/bleublanccloud.db "DROP TABLE IF EXISTS photos"` (faire une sauvegarde avant). |
| `npm run build` échoue par manque de mémoire | passer le conteneur à 3–4 Go de RAM. |
| Beaucoup de « robots.txt injoignable » | réseau sortant filtré ou sites en panne : le robot n'analyse alors aucune page, par respect de la RFC 9309. |
| `bbcloud-demandes` : « CODEBERG_JETON absent du fichier .env » | normal tant que la fonctionnalité n'est pas configurée (étape 6 bis). |
| `bbcloud-demandes` : « Codeberg injoignable : GET /issues : HTTP 401 » ou « HTTP 403 » | jeton invalide, expiré ou révoqué, non limité au bon dépôt, ou sans la permission `issue` en écriture : régénérer le jeton (étape 6 bis). |
| `bbcloud-demandes` : « HTTP 404 » | `DEPOT_DEMANDES` ne correspond pas au dépôt (`<pseudo>/bleublanccloud-pages`), ou les tickets sont désactivés sur le dépôt. |
| `bbcloud-demandes` : « Codeberg injoignable : … ConnectError » | réseau sortant coupé ou Codeberg en panne : rien n'est modifié, nouvel essai à la demie suivante. |
| Journal : « Étiquette « traitée » absente du dépôt » | créer les quatre étiquettes avec leur nom exact (étape 6 bis) ; les réponses sont tout de même publiées. |
| Le bouton ouvre un ticket **vide**, sans formulaire | le modèle n'est pas lu : vérifier que `.forgejo/issue_template/analyse.yaml` est présent sur la branche `pages` (publié par `publier.sh`) et que `pages` est la branche par défaut (étape 4.1). En attendant, le lien « Version simplifiée » fonctionne (ticket reconnu par son titre `[Analyse]`). |
| Un ticket reste **sans réponse** | vérifier `journalctl -u bbcloud-demandes -e` ; le traitement est reporté pendant la campagne du dimanche (verrou) ; un ticket sans étiquette `analyse` ni titre commençant par `[Analyse]` est ignoré. |
| Ticket avec l'étiquette `erreur` | erreur technique (site injoignable, publication impossible…) : nouvel essai automatique à chaque passage, 3 tentatives au maximum, puis fermeture avec explication. Cause dans `journalctl -u bbcloud-demandes -p warning`. |
| `bbcloud-maj-auto` en échec : « Tests en échec » | le serveur est resté sur l'ancienne version. Lire `journalctl -u bbcloud-maj-auto -p warning`, corriger dans le dépôt et pousser : le nouveau commit est testé à l'heure suivante. |
| `bbcloud-maj-auto` : « Fusion en avance rapide impossible » | des fichiers ont été modifiés à la main sur le serveur : `su - bbcloud -c 'git -C /opt/bleu-blanc-cloud status'`, puis annuler ces modifications (le code se modifie dans le dépôt GitHub). |
| `bbcloud-maj-auto` : « mise à jour reportée » | normal pendant la campagne hebdomadaire (verrou partagé) : nouvel essai à l'heure suivante. |
| Rapports IA en erreur | `journalctl -u bbcloud-campagne` ; vérifier la clé et le quota Mistral ; les rapports en erreur sont retentés à la campagne suivante. |
