# Runbook de déploiement

Ce document décrit l'installation, la publication et l'exploitation de Bleu Blanc Cloud : un conteneur LXC Debian 12 sur Proxmox exécute le scanner et construit le site, qui est publié sur Codeberg Pages à l'adresse `https://bleublanccloud.fr`.

Les noms utilisés (compte Codeberg `berachem`, dépôts `bleublanccloud-pages` et `bleublanccloud-redirection`, domaine `bleublanccloud.fr`) sont ceux de l'instance officielle ; ils sont à adapter pour toute autre instance. Sauf mention contraire, les commandes s'exécutent en `root` dans le conteneur ; celles du scanner s'exécutent en tant qu'utilisateur `bbcloud` (`su - bbcloud`, puis `cd /opt/bleu-blanc-cloud/scanner`).

```
Proxmox                                               Internet
┌──────────────────────────────────────────┐
│ LXC Debian 12 « bbcloud »                 │   git push   ┌────────────────────────┐
│  timer systemd (dimanche 3 h)             │ ───────────▶ │ Codeberg Pages (DE)    │
│   référentiels → campagne → rapports IA   │              │ bleublanccloud.fr      │
│   → export JSON → build Astro → publier   │              └────────────────────────┘
│  sauvegarde SQLite quotidienne (2 h)      │
└──────────────────────────────────────────┘
      aucun port entrant, uniquement des connexions sortantes
```

## Sommaire

1. [Prérequis](#1-prérequis)
2. [Conteneur LXC](#2-conteneur-lxc)
3. [Installation](#3-installation)
4. [Configuration](#4-configuration)
5. [Publication sur Codeberg Pages](#5-publication-sur-codeberg-pages)
6. [Premier lancement](#6-premier-lancement)
7. [Automatisation](#7-automatisation)
8. [Analyses sur demande](#8-analyses-sur-demande)
9. [Sauvegardes et restauration](#9-sauvegardes-et-restauration)
10. [Miroir du code sur Codeberg](#10-miroir-du-code-sur-codeberg)
11. [Liste de contrôle avant ouverture](#11-liste-de-contrôle-avant-ouverture)
12. [Opérations courantes](#12-opérations-courantes)
13. [Dépannage](#13-dépannage)

---

## 1. Prérequis

| Élément | Source | Obligatoire |
|---|---|---|
| Proxmox VE 8, accès administrateur | — | oui |
| Compte Codeberg | <https://codeberg.org/user/sign_up> | oui |
| Domaine et accès à sa zone DNS | OVHcloud, *Web Cloud → Noms de domaine* | oui |
| Clé API Mistral | <https://console.mistral.ai>, *API Keys* | pour les rapports IA |
| Jeton IPinfo (base IP → ASN) | <https://ipinfo.io/signup> | recommandé ; à défaut, repli sur RIPEstat, plus lent |

Durée indicative d'une première installation : une heure.

---

## 2. Conteneur LXC

### 2.1 Interface web de Proxmox

1. Modèle : *Datacenter → nœud → local → CT Templates → Templates*, télécharger `debian-12-standard`.
2. *Create CT* :
   - *General* : hostname `bbcloud`, *Unprivileged container* coché, mot de passe root ;
   - *Template* : `debian-12-standard` ;
   - *Disks* : 16 Go ;
   - *CPU* : 2 cœurs ; *Memory* : 2048 Mo, swap 512 Mo ;
   - *Network* : `vmbr0`, IPv4 en DHCP ou adresse fixe.
3. *Options* : *Start at boot* activé ; *Features* : *nesting* activé.

### 2.2 Ligne de commande (hôte Proxmox)

```bash
pveam update
pveam available --section system | grep debian-12
pveam download local debian-12-standard_12.7-1_amd64.tar.zst

pct create 120 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname bbcloud --unprivileged 1 --features nesting=1 \
  --cores 2 --memory 2048 --swap 512 --rootfs local-lvm:16 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp --onboot 1 --start 1
```

Remplacer `120` par un identifiant libre et le nom du modèle par celui affiché par `pveam available`.

### 2.3 Stockage des sauvegardes (recommandé)

Monter un dossier de l'hôte dans le conteneur pour les sauvegardes quotidiennes :

```bash
# Sur l'hôte Proxmox
mkdir -p /mnt/sauvegardes/bbcloud
chown 101000:101000 /mnt/sauvegardes/bbcloud   # utilisateur bbcloud (uid 1000) d'un conteneur non privilégié
pct set 120 -mp0 /mnt/sauvegardes/bbcloud,mp=/mnt/sauvegardes
pct reboot 120
```

Si `bbcloud` n'a pas l'uid 1000 dans le conteneur (`id bbcloud`), utiliser : uid hôte = 100000 + uid conteneur.

---

## 3. Installation

Entrer dans le conteneur (`pct enter 120` depuis l'hôte, ou console Proxmox), puis :

```bash
apt-get update && apt-get install -y curl
curl -fsSLO https://raw.githubusercontent.com/Berachem/bleu-blanc-cloud/main/deploy/installer.sh
bash installer.sh
```

Le script est idempotent et peut être relancé sans risque. Il :

- installe `git`, `sqlite3`, Node.js 22 LTS (binaire officiel, somme de contrôle vérifiée) et `uv` ;
- crée l'utilisateur système `bbcloud` ;
- clone le dépôt dans `/opt/bleu-blanc-cloud` (en HTTPS pour un dépôt public ; pour un dépôt privé, voir ci-dessous) ;
- installe les dépendances Python et Node ;
- crée `/opt/bleu-blanc-cloud/.env` à partir de `.env.example` (droits `600`) s'il n'existe pas ;
- génère la clé SSH de publication vers Codeberg (`/home/bbcloud/.ssh/id_ed25519_codeberg`) et affiche sa partie publique ;
- installe les services systemd, active la sauvegarde quotidienne, la mise à jour automatique et le traitement des demandes, et laisse le timer de campagne désactivé.

Options :

| Variable | Effet |
|---|---|
| `AVEC_CHROMIUM=1` | installe Chromium (environ 300 Mo) : chaque publication vérifie alors l'absence de requête externe et de cookie |
| `DEPOT_PRIVE=1` / `DEPOT_PRIVE=0` | force le mode d'accès au dépôt si la détection automatique se trompe |

Dépôt privé (fork non public) : l'installateur génère une clé de déploiement GitHub en lecture seule, affiche le lien vers *Settings → Deploy keys* du dépôt et attend son ajout (sans accès en écriture), puis clone en SSH. La clé d'hôte de GitHub est épinglée (empreinte officielle). Le script `installer.sh` lui-même se récupère alors avec un jeton GitHub temporaire en lecture seule :

```bash
read -rs -p "Jeton GitHub : " JETON && echo
curl -fsSL -H "Authorization: Bearer $JETON" -H "Accept: application/vnd.github.raw+json" \
  https://api.github.com/repos/<compte>/<depot>/contents/deploy/installer.sh -o installer.sh
unset JETON
```

---

## 4. Configuration

Éditer `/opt/bleu-blanc-cloud/.env` :

| Variable | Valeur |
|---|---|
| `MISTRAL_API_KEY` | clé API Mistral |
| `MISTRAL_MODELE` | `mistral-small-latest` (par défaut) |
| `MISTRAL_SERVEUR` | `eu` (serveur européen `api.eu.mistral.ai`) |
| `MISTRAL_PRIX_ENTREE_PAR_M`, `MISTRAL_PRIX_SORTIE_PAR_M` | tarifs en dollars par million de jetons, pour l'estimation `--dry-run` (<https://mistral.ai/pricing>) |
| `IPINFO_TOKEN` | jeton IPinfo (facultatif, recommandé) |
| `DEPOT_PAGES` | `git@codeberg.org:berachem/bleublanccloud-pages.git` (section 5.1) |
| `DOMAINE_SITE` | `bleublanccloud.fr` : URL du site au build (canoniques, plan du site, `robots.txt`), liens des réponses aux tickets, fichier `.domains`, User-Agent du robot |
| `CODEBERG_JETON` | jeton des analyses sur demande (section 8) ; vide : fonctionnalité désactivée |
| `DEPOT_DEMANDES` | `berachem/bleublanccloud-pages` : dépôt où les visiteurs ouvrent leurs tickets |

`USER_AGENT` n'est à renseigner que pour remplacer la valeur par défaut, `BleuBlancCloudBot/1.0 (+https://<DOMAINE_SITE>/methodologie)`. Les autres valeurs (politesse du robot, chemins) peuvent rester inchangées.

---

## 5. Publication sur Codeberg Pages

Codeberg utilise git-pages pour les nouveaux comptes : le domaine est autorisé par un enregistrement DNS `TXT` et chaque déploiement est déclenché par un webhook sur la branche `pages`. Avec git-pages, chaque nom d'hôte est un site distinct : un déploiement ne concerne que le domaine de l'URL du webhook, et seulement si le `TXT` `_git-pages-repository` de ce domaine autorise le dépôt (voir [ADR-0004](../docs/adr/0004-domaine-bleublanccloud-fr.md)).

Effectuer les étapes 5.1 à 5.4 dans l'ordre, avant la première publication : le certificat HTTPS n'est demandé qu'au premier déploiement réussi.

### 5.1 Dépôt de publication

1. Créer sur Codeberg un dépôt public et vide nommé `bleublanccloud-pages` (git-pages le clone en HTTPS, sans identifiant).
2. *Paramètres → Clés de déploiement → Ajouter une clé* : coller la clé publique affichée par l'installateur (`cat /home/bbcloud/.ssh/id_ed25519_codeberg.pub`) et cocher *Activer l'accès en écriture*.
3. Après la première publication, vérifier que `pages` est la branche par défaut (*Paramètres → Branches*) ; c'est automatique si le dépôt était vide. Forgejo y lit le modèle de ticket des analyses sur demande.

### 5.2 Enregistrements DNS (zone OVHcloud)

Console OVHcloud : *Web Cloud → Noms de domaine → bleublanccloud.fr → Zone DNS*. Ne modifier ni les enregistrements `NS` ni DNSSEC : OVHcloud re-signe la zone à chaque modification.

Enregistrements de parking à supprimer (valeurs variables selon la zone) :

| Type | Sous-domaine | Motif |
|---|---|---|
| `A`, et `AAAA` s'il existe | *(vide)* : apex | page de parking OVHcloud |
| `A`, `AAAA` ou `CNAME` | `www` | remplacé ci-dessous |
| `TXT` de valeur `"1\|www.bleublanccloud.fr"` | *(vide)* | marqueur de redirection web OVHcloud, s'il existe |

Si l'onglet *Redirection* du domaine contient une redirection, la supprimer au préalable ; à défaut, OVHcloud recrée ses propres enregistrements.

Enregistrements à créer (dans le formulaire OVHcloud, un sous-domaine vide désigne l'apex) :

| Type | Sous-domaine | Cible / valeur | Rôle |
|---|---|---|---|
| `A` | *(vide)* | `217.197.84.141` | apex vers Codeberg Pages |
| `AAAA` | *(vide)* | `2a0a:4580:103f:c0de::2` | apex vers Codeberg Pages (IPv6) |
| `TXT` | `_git-pages-repository` | `https://codeberg.org/berachem/bleublanccloud-pages.git` | autorise le dépôt du site sur l'apex |
| `CNAME` | `www` | `codeberg.page.` | `www` vers Codeberg Pages |
| `TXT` | `_git-pages-repository.www` | `https://codeberg.org/berachem/bleublanccloud-redirection.git` | autorise le dépôt de redirection sur `www` (section 5.5) |

- Un apex ne peut pas porter de `CNAME` : les adresses sont celles de `codeberg.page` indiquées par la documentation de Codeberg (vérifiées le 30 septembre 2026). En cas de changement par Codeberg, les mettre à jour ; le `CNAME` de `www` suit automatiquement.
- Le `TXT` contient l'URL HTTPS de clonage du dépôt, avec `.git`.
- Aucun `CAA` n'existe par défaut ; un `CAA` éventuel doit autoriser Let's Encrypt : `0 issue "letsencrypt.org"`.

Messagerie, selon l'usage du domaine :

- Aucune adresse sur le domaine : supprimer les `MX` OVHcloud (`mx1`, `mx2`, `mx3.mail.ovh.net`), le `TXT` SPF OVHcloud et les enregistrements `autoconfig`, `autodiscover` et `_autodiscover._tcp`, puis publier :

  | Type | Sous-domaine | Valeur |
  |---|---|---|
  | `MX` | *(vide)* | priorité `0`, cible `.` (MX nul, RFC 7505 ; si l'interface refuse `.`, ne créer aucun `MX`) |
  | `TXT` | *(vide)* | `v=spf1 -all` |
  | `TXT` | `_dmarc` | `v=DMARC1; p=reject;` |

- Messagerie hébergée par OVHcloud : conserver les `MX` et le SPF OVHcloud.

Dans les deux cas, le site obtient 100/100 sur son propre scan.

Vérification (`apt-get install -y dnsutils` si nécessaire) :

```bash
dig +short NS bleublanccloud.fr                              # serveurs OVHcloud
dig +short A bleublanccloud.fr                               # 217.197.84.141
dig +short AAAA bleublanccloud.fr                            # 2a0a:4580:103f:c0de::2
dig +short TXT _git-pages-repository.bleublanccloud.fr       # URL du dépôt bleublanccloud-pages
dig +short CNAME www.bleublanccloud.fr                       # codeberg.page.
dig +short TXT _git-pages-repository.www.bleublanccloud.fr   # URL du dépôt bleublanccloud-redirection
dig +dnssec A bleublanccloud.fr | grep RRSIG                 # signature présente : DNSSEC actif
```

### 5.3 Webhook de déploiement

Le dépôt du site a un seul webhook, vers le domaine principal. Dans `bleublanccloud-pages` : *Paramètres → Webhooks → Ajouter un webhook → Forgejo*.

| Champ | Valeur |
|---|---|
| URL cible | `http://bleublanccloud.fr/` pour le premier déploiement (voir 5.4) |
| Méthode HTTP | `POST` |
| Type de contenu | `application/json` |
| Déclencheur | évènements de push uniquement |
| Filtre de branche | `pages` |
| Actif | oui |

- Le premier déploiement utilise `http://` : le certificat n'existe pas encore et une URL en `https://` ferait échouer la livraison.
- Le bouton *Tester la livraison* échoue toujours avec git-pages ; le test réel est un push sur `pages`.

### 5.4 Premier déploiement et passage en HTTPS

1. Lancer la première publication (section 6, étape 8). Le push sur `pages` déclenche le webhook ; git-pages publie le site et demande le certificat Let's Encrypt.
2. Contrôler la livraison : *Paramètres → Webhooks → webhook → Livraisons récentes*, code 2xx attendu.
3. Après quelques minutes, vérifier le certificat : `curl -sI https://bleublanccloud.fr`.
4. Remplacer l'URL cible du webhook par `https://bleublanccloud.fr/` : une fois le certificat émis, le serveur peut rediriger le HTTP vers le HTTPS et faire échouer les livraisons suivantes.

Si la publication a eu lieu avant la création du webhook, relancer la dernière livraison depuis *Livraisons récentes*, ou pousser un commit vide :

```bash
su - bbcloud -c 'cd /opt/bleu-blanc-cloud/donnees/depot-pages && git commit --allow-empty -qm "redéploiement" && git push -q origin pages'
```

`publier.sh` écrit un fichier `.domains` (valeur de `DOMAINE_SITE`), ignoré par git-pages et conservé pour l'ancien serveur Pages. git-pages ne redirige pas `/page` vers `/page.html` ; le site n'est pas concerné, Astro générant des dossiers (`/methodologie/index.html`).

### 5.5 Redirection de www

Le dépôt du site ne peut pas servir `www` sans dupliquer le contenu. Un dépôt dédié, dont le fichier `_redirects` renvoie toutes les adresses vers l'apex (`/* https://bleublanccloud.fr/:splat 301!`, chemin et paramètres conservés), s'en charge. Son contenu se trouve dans [`deploy/redirection/`](redirection/) ; le même dépôt sert à l'ancien domaine (section 5.6).

1. Créer sur Codeberg un dépôt public et vide nommé `bleublanccloud-redirection`.
2. Y ajouter un webhook Forgejo avec les réglages de la section 5.3 et l'URL cible `http://www.bleublanccloud.fr/`.
3. Vérifier le `TXT` `_git-pages-repository.www.bleublanccloud.fr` (section 5.2), puis pousser le contenu sur la branche `pages` ; ce push déclenche le déploiement :
   ```bash
   cp -r bleu-blanc-cloud/deploy/redirection /tmp/redirection && cd /tmp/redirection
   git init -q -b pages && git add . && git commit -qm "Redirection vers bleublanccloud.fr"
   git push git@codeberg.org:berachem/bleublanccloud-redirection.git pages
   ```
   Sans accès SSH : téléverser les trois fichiers dans l'interface web, créer une branche `pages` à partir de ce commit, puis modifier une ligne de `README.md` sur la branche `pages` pour déclencher un push.
4. Après émission du certificat, passer l'URL du webhook en `https://www.bleublanccloud.fr/`.
5. Contrôler : `curl -sI https://www.bleublanccloud.fr/methodologie/` doit renvoyer `301` et `location: https://bleublanccloud.fr/methodologie/`.

### 5.6 Migration depuis bleublanccloud.berachem.dev

Procédure pour un serveur déjà en service sur l'ancienne adresse. L'ordre garantit la continuité du service.

1. Vérifier que le domaine est actif : `dig +short NS bleublanccloud.fr` renvoie les serveurs OVHcloud.
2. Créer les enregistrements DNS (section 5.2) et attendre leur propagation.
3. Laisser la mise à jour automatique (section 7.2) installer le code. Tant que `.env` contient `DOMAINE_SITE=bleublanccloud.berachem.dev`, le site reste construit pour l'ancienne adresse.
4. Remplacer l'URL cible du webhook de `bleublanccloud-pages` par `http://bleublanccloud.fr/`. L'ancien domaine ne reçoit plus de mises à jour mais reste en ligne.
5. Dans `/opt/bleu-blanc-cloud/.env` : `DOMAINE_SITE=bleublanccloud.fr`, et supprimer la ligne `USER_AGENT=`.
6. Republier : `su - bbcloud -c 'cd /opt/bleu-blanc-cloud/scanner && uv run bbcloud publier'`. URL canoniques, plan du site, `robots.txt`, liens du modèle de ticket et réponses aux tickets passent au nouveau domaine. Terminer par la section 5.4 (livraison 2xx, certificat, webhook en `https://`).
7. Rediriger l'ancien domaine :
   1. créer le dépôt de redirection et rediriger `www` (section 5.5) ;
   2. ajouter à ce dépôt un second webhook vers `https://bleublanccloud.berachem.dev/` (certificat existant) ;
   3. dans la zone de `berachem.dev`, remplacer la valeur du `TXT` `_git-pages-repository.bleublanccloud` par `https://codeberg.org/berachem/bleublanccloud-redirection.git`, en conservant le `CNAME` `bleublanccloud` vers `codeberg.page.` (non proxifié) ;
   4. déclencher un déploiement du dépôt de redirection (nouveau push sur `pages`) ;
   5. contrôler : `curl -sI https://bleublanccloud.berachem.dev/carte/` renvoie `301` et `location: https://bleublanccloud.fr/carte/`.
8. Mettre à jour l'adresse du site dans la description des dépôts GitHub et Codeberg, vérifier `uv run bbcloud scanner bleublanccloud.fr` (note A attendue) et conserver les enregistrements de `berachem.dev` au moins un an.

`installer.sh` n'a pas à être relancé : il ne gère pas le domaine et les services systemd sont inchangés.

---

## 6. Premier lancement

En tant que `bbcloud`, depuis `/opt/bleu-blanc-cloud/scanner` :

1. Référentiels (plages IP des clouds, base ASN, amorçage RDAP, contrôle SecNumCloud) :
   ```bash
   uv run bbcloud referentiels maj
   ```
2. Test sur un domaine autorisé :
   ```bash
   uv run bbcloud scanner berachem.dev
   ```
3. Import des cibles (communes de 10 000 habitants et plus, départements, régions) :
   ```bash
   uv run bbcloud cibles importer --population-min 10000
   uv run bbcloud cibles lister --limite 20
   ```
4. Campagne de test limitée à 10 organisations, à valider avant toute campagne complète :
   ```bash
   uv run bbcloud campagne lancer --limite 10 --dry-run   # liste des cibles, aucune requête
   uv run bbcloud campagne lancer --limite 10             # confirmation demandée
   uv run bbcloud referentiels inconnus                   # hébergeurs non identifiés
   uv run bbcloud scores couverture                       # part du poids encore inconnue
   ```
5. Rapports IA :
   ```bash
   uv run bbcloud rapports generer --max 3 --dry-run      # nombre d'appels et coût estimés
   uv run bbcloud rapports generer --max 3
   ```
6. Contours des communes (carte de situation des fiches) : téléchargés par `cibles importer` depuis `geo.api.gouv.fr` (licence Etalab 2.0), simplifiés et stockés en base ; seuls les manquants sont redemandés.
   ```bash
   uv run bbcloud cibles contours            # contours manquants
   uv run bbcloud cibles contours --forcer   # tout retélécharger
   ```
7. Aperçu local du site, sur `http://<IP-du-conteneur>:4321` :
   ```bash
   uv run bbcloud exporter
   cd ../site && npm run build && npx astro preview --host 0.0.0.0
   ```
8. Publication, puis contrôle de la note du site (A attendue) :
   ```bash
   cd ../scanner
   uv run bbcloud publier
   uv run bbcloud scanner bleublanccloud.fr
   ```
   Au premier push, contrôler la livraison du webhook et passer son URL en `https://` (section 5.4).

---

## 7. Automatisation

### 7.1 Campagne hebdomadaire

```bash
systemctl enable --now bbcloud-campagne.timer   # chaque dimanche à 3 h (heure de Paris)
systemctl list-timers 'bbcloud*'
systemctl start bbcloud-campagne.service        # exécution immédiate
journalctl -u bbcloud-campagne -f               # journaux
```

`deploy/campagne-hebdomadaire.sh` enchaîne : `uv sync`, `referentiels maj`, `cibles importer` (et contours des nouvelles communes), `campagne lancer --oui`, `scores recalculer`, `rapports generer --oui` (si une clé Mistral est présente ; le cache évite tout appel inutile), `publier`. Une campagne complète (environ 1 000 organisations, 1 requête par seconde et par domaine, 10 scans en parallèle) dure de 30 à 60 minutes.

### 7.2 Mise à jour automatique du code

`bbcloud-maj-auto.timer`, activé par l'installateur, exécute `deploy/maj-auto.sh` toutes les heures :

1. `git fetch`, arrêt immédiat si `main` n'a pas changé ;
2. `git merge --ff-only`, `uv sync`, et `npm ci` seulement si `site/package-lock.json` a changé ;
3. tests du scanner (`pytest`) ;
4. si les tests passent : recalcul des scores si les référentiels ont changé, téléchargement des contours manquants, puis export, build et publication à partir des données en base, sans nouveau scan. Rien n'est publié tant que la base ne contient aucune organisation notée.

En cas d'échec des tests, le serveur revient à la version précédente, rien n'est publié, le service passe en échec (`systemctl --failed`) et le commit n'est plus retenté : un correctif doit être poussé.

Un verrou (`flock` sur `donnees/bbcloud.verrou`) empêche l'exécution simultanée de la mise à jour, de la campagne et du traitement des demandes : pendant une campagne, la mise à jour est reportée à l'heure suivante ; pendant une mise à jour, la campagne attend (deux heures au maximum). La campagne s'exécute donc toujours sur une version testée.

```bash
systemctl start bbcloud-maj-auto.service         # vérification immédiate
journalctl -u bbcloud-maj-auto -f                # journaux (-p warning pour les alertes)
systemctl disable --now bbcloud-maj-auto.timer   # suspension
```

La mise à jour automatique n'installe pas les nouveaux services systemd : lorsqu'une version en ajoute, relancer `bash installer.sh`.

---

## 8. Analyses sur demande

Le bouton « Analyser mon site » propose un ticket sur le dépôt Codeberg `bleublanccloud-pages` (traitement automatique) ou un e-mail à l'adresse `SITE.contact` de `site/src/config.ts` (traitement manuel, section 12). Toutes les heures, à la demie, `bbcloud-demandes.timer` exécute `bbcloud demandes traiter` : lecture des tickets par l'API Codeberg, validation du domaine, analyse passive, publication de la fiche et réponse dans le ticket. Le serveur n'expose aucun port.

### 8.1 Étiquettes

Dans `bleublanccloud-pages` : *Tickets → Étiquettes → Nouvelle étiquette*. Créer les quatre étiquettes suivantes (noms exacts, accents compris) et vérifier que les tickets sont activés (*Paramètres → Unités → Tickets*).

| Étiquette | Rôle | Couleur |
|---|---|---|
| `analyse` | posée par le formulaire : identifie une demande | `#003399` |
| `traitée` | réponse publiée avec la fiche | `#2E7D32` |
| `refusée` | domaine invalide, retrait, limite atteinte (motif expliqué) | `#6B7280` |
| `erreur` | erreur technique ; nouvel essai automatique, trois tentatives au maximum | `#ED2939` |

### 8.2 Jeton Codeberg

1. Codeberg : *Paramètres → Applications → Générer un nouveau jeton*, nom `bbcloud-demandes`.
2. Accès aux dépôts : *Dépôts spécifiques*, uniquement `bleublanccloud-pages`.
3. Permissions : `issue` en lecture et écriture ; aucune autre permission.
4. Copier le jeton dans `/opt/bleu-blanc-cloud/.env` : `CODEBERG_JETON=…`.

Le jeton n'apparaît jamais dans les journaux ni dans les réponses. Les réponses sont publiées au nom du compte qui a créé le jeton ; pour une identité distincte, créer un compte robot, l'ajouter comme collaborateur (droit *Écriture*) de `bleublanccloud-pages` et générer le jeton depuis ce compte.

### 8.3 Activation et test

```bash
bash installer.sh   # installe et active bbcloud-demandes.timer si nécessaire
su - bbcloud -c 'cd /opt/bleu-blanc-cloud/scanner && uv run bbcloud demandes lister'
```

Ouvrir un ticket de test depuis le site avec le domaine `berachem.dev`, puis :

```bash
systemctl start bbcloud-demandes.service   # traitement immédiat
journalctl -u bbcloud-demandes -e
```

Résultat attendu : réponse dans le ticket (note, score, lien vers la fiche), étiquette `traitée`, ticket fermé.

### 8.4 Règles appliquées

- Validation stricte : nom de domaine seul (punycode accepté), sans chemin, port, adresse IP ni nom local (`localhost`, `.local`, `.internal`…) ; refus d'un domaine qui résout vers une adresse privée ou locale ; case d'engagement obligatoire ; respect de `retraits.yaml`.
- Garde réseau : pour tous les scans, campagnes comprises, aucune connexion vers une adresse non publique, y compris après redirection.
- Limites : 10 demandes acceptées par jour au total, une par jour et par compte (`DEMANDES_LIMITE_JOUR`, `DEMANDES_LIMITE_COMPTE`) ; une analyse de moins de 7 jours est réutilisée.
- Fiches « sur demande » : accessibles par leur lien et la recherche, exclues de la carte, des classements et des statistiques, jamais rescannées par la campagne. Si le domaine appartient déjà à une organisation de l'observatoire, sa fiche est mise à jour.
- Rapports IA : générés avec le cache habituel si `MISTRAL_API_KEY` est renseignée, 10 par jour au plus.
- Données personnelles : le nom du compte Codeberg du demandeur est conservé en base pour appliquer les limites, jamais publié, et effacé après 30 jours par `bbcloud demandes traiter` (durée annoncée dans les mentions légales ; les sauvegardes, conservées 30 jours, suivent).

---

## 9. Sauvegardes et restauration

`bbcloud-sauvegarde.timer` exécute chaque jour à 2 h un `sqlite3 .backup` compressé vers `/mnt/sauvegardes`, avec une rétention de 30 jours (réglable dans `/etc/bbcloud/sauvegarde.env`).

```bash
systemctl start bbcloud-sauvegarde.service   # sauvegarde immédiate
```

Restauration :

```bash
systemctl stop bbcloud-campagne.timer bbcloud-maj-auto.timer bbcloud-demandes.timer
gunzip -c /mnt/sauvegardes/bleublanccloud-AAAA-MM-JJ.db.gz > /opt/bleu-blanc-cloud/donnees/bleublanccloud.db
chown bbcloud:bbcloud /opt/bleu-blanc-cloud/donnees/bleublanccloud.db
systemctl start bbcloud-campagne.timer bbcloud-maj-auto.timer bbcloud-demandes.timer
```

Inclure également le conteneur dans les sauvegardes Proxmox (*Datacenter → Backup*).

---

## 10. Miroir du code sur Codeberg

Codeberg : *+ → Nouvelle migration → GitHub*, URL `https://github.com/Berachem/bleu-blanc-cloud`, option *Ce dépôt sera un miroir* cochée. La synchronisation est ensuite automatique.

---

## 11. Liste de contrôle avant ouverture

- [ ] Mentions légales : l'adresse de l'éditeur n'est pas publiée (particulier non professionnel, LCEN art. 1-1 II), à condition que son identité (nom, prénom, adresse) ait été communiquée à Codeberg e.V. (par exemple par e-mail à `contact@codeberg.org`, en indiquant le dépôt Pages). Conserver une trace de l'envoi.
- [ ] Adresse de contact (`SITE.contact`) opérationnelle.
- [ ] Référentiels relus : `uv run bbcloud referentiels verifier` liste les faits marqués `a_verifier`.
- [ ] Campagne de test de 10 organisations relue sur le site local.
- [ ] Première campagne complète lancée et publiée.
- [ ] Webhooks passés en `https://` après émission des certificats (sections 5.4 et 5.5).
- [ ] Analyses sur demande : étiquettes, jeton, ticket de test traité (section 8).
- [ ] Note du site sur son propre scan : `bbcloud scanner bleublanccloud.fr` donne A.
- [ ] Redirections 301 de `www.bleublanccloud.fr` et de `bleublanccloud.berachem.dev` vers `https://bleublanccloud.fr/`.
- [ ] Dépôt GitHub public et miroir Codeberg en place.

Le code se modifie uniquement dans le dépôt GitHub : le conteneur récupère chaque nouvelle version dans l'heure, après passage des tests, et republie le site.

---

## 12. Opérations courantes

| Besoin | Action |
|---|---|
| Retrait d'une organisation | ajouter le domaine à `scanner/src/bleublanccloud/referentiels/retraits.yaml` et committer ; le domaine n'est plus analysé et sa fiche disparaît à la publication suivante |
| Ajout d'un hébergeur non identifié | compléter `fournisseurs.yaml` (avec sources) à partir de `bbcloud referentiels inconnus` ; les réseaux de transit se déclarent dans `transitaires.yaml`, jamais comme fournisseurs |
| Application d'un référentiel mis à jour sans nouveau scan | automatique via `bbcloud-maj-auto` ; à la main : `uv run bbcloud scores recalculer --dry-run`, puis sans `--dry-run`, puis `uv run bbcloud publier`. Les rapports IA des fiches modifiées sont retirés jusqu'au prochain `rapports generer` |
| Poids encore inconnu de l'observatoire | `uv run bbcloud scores couverture` |
| Modification de la méthodologie | nouvelle version dans `analyse/score.py` et entrée dans `docs/methodologie.md` |
| Modification des consignes IA | incrémenter `VERSION_INVITE` dans `ia/invites.py` (rapports régénérés) |
| Mise à jour immédiate du code | `systemctl start bbcloud-maj-auto.service` |
| Demande d'analyse reçue par e-mail | vérifier qu'elle concerne le site du demandeur ou d'un organisme public, puis `su - bbcloud -c 'cd /opt/bleu-blanc-cloud/scanner && uv run bbcloud demandes analyser <domaine>'` : mêmes contrôles qu'un ticket, publication, puis réponse type à renvoyer |
| Demandes en attente | `su - bbcloud -c 'cd /opt/bleu-blanc-cloud/scanner && uv run bbcloud demandes lister'` |
| Suspension des demandes | `systemctl disable --now bbcloud-demandes.timer`, ou vider `CODEBERG_JETON` |
| Nouvelle tentative après un refus ou un échec | nouveau ticket : un ticket fermé puis rouvert n'est plus traité |

---

## 13. Dépannage

### Scanner et référentiels

| Symptôme | Cause probable et action |
|---|---|
| `referentiels maj` : « IPINFO_TOKEN absent » | aucun jeton IPinfo : repli sur RIPEstat. Renseigner `IPINFO_TOKEN`. |
| Hébergeurs souvent « inconnus » | lancer `referentiels maj`, compléter `fournisseurs.yaml` à partir de `referentiels inconnus`, puis `scores recalculer`. |
| Fournisseur ajouté toujours « inconnu » | constats non réattribués : `uv run bbcloud scores recalculer` (automatique quand le référentiel arrive par `git`). |
| « Origine indéterminée (réseau de transit) » | adresse annoncée par un opérateur de transit : l'hébergeur réel n'est pas identifiable par l'ASN. Chercher un nom d'hôte ou un en-tête révélateur. |
| Nombreux « robots.txt injoignable » | réseau sortant filtré ou sites indisponibles : aucune page n'est analysée (RFC 9309). |
| `cibles contours` : « introuvable » | code INSEE absent de `geo.api.gouv.fr` (commune fusionnée ou supprimée) : relancer `cibles importer`. |
| Fiche de commune avec illustration au lieu de la carte | contour non téléchargé : `uv run bbcloud cibles contours`, puis `uv run bbcloud publier` ; autoriser `geo.api.gouv.fr` si le réseau sortant est filtré. |
| `npm run build` : mémoire insuffisante | passer le conteneur à 3 ou 4 Go de RAM. |
| Rapports IA en erreur | `journalctl -u bbcloud-campagne` ; vérifier la clé et le quota Mistral ; nouvel essai à la campagne suivante. |

### Accès aux dépôts

| Symptôme | Cause probable et action |
|---|---|
| `Permission denied (publickey)` sur github.com (dépôt privé) | clé de déploiement absente de *Settings → Deploy keys* : `cat /home/bbcloud/.ssh/id_ed25519_github.pub`. Test : `su - bbcloud -c 'ssh -T git@github.com'`. |
| Mauvaise détection public / privé | relancer avec `DEPOT_PRIVE=1` ou `DEPOT_PRIVE=0`. |
| `Permission denied (publickey)` à la publication | clé Codeberg sans accès en écriture, ou `DEPOT_PAGES` pas en SSH. Test : `su - bbcloud -c 'ssh -T git@codeberg.org'`. |

### Codeberg Pages

| Symptôme | Cause probable et action |
|---|---|
| Message « old pages server » | requête reçue par l'ancien serveur Pages : enregistrements DNS incorrects (`A`/`AAAA` différents de `codeberg.page`, `CNAME` à l'ancienne forme, `TXT` absent ou différent de l'URL HTTPS exacte du dépôt) ou aucun déploiement git-pages effectué. Corriger le DNS (section 5.2), vérifier le webhook, redéclencher un déploiement (section 5.4). |
| `tls: internal error`, `SSL_ERROR_INTERNAL_ERROR_ALERT` | certificat non émis : il n'est demandé qu'après un déploiement réussi. Vérifier une livraison 2xx avec une URL en `http://`, les enregistrements DNS et les `CAA` éventuels, puis patienter. Diagnostic officiel : `curl -fsSL https://troubleshoot.codeberg.page/verify.sh -o verify.sh`, relire le script, puis `bash verify.sh bleublanccloud.fr`. |
| Site en ligne non à jour | contrôler la branche `pages` et la dernière livraison du webhook ; une URL restée en `http://` après l'émission du certificat fait échouer les livraisons. |
| Version du site (pied de page) antérieure au dernier commit | `systemctl status bbcloud-maj-auto.timer` (« Unit not found » : relancer `installer.sh`) et `journalctl -u bbcloud-maj-auto -n 80 --no-pager`. |

### Mise à jour automatique

| Symptôme | Cause probable et action |
|---|---|
| « Tests en échec » ou « déjà rejeté » | le serveur reste sur la version précédente : lire `journalctl -u bbcloud-maj-auto -p warning`, corriger et pousser un nouveau commit. |
| « Fusion en avance rapide impossible » | fichiers modifiés sur le serveur : `su - bbcloud -c 'git -C /opt/bleu-blanc-cloud status'`, puis annuler ces modifications. |
| « mise à jour reportée » | campagne en cours (verrou partagé) : nouvel essai à l'heure suivante. |

### Analyses sur demande

| Symptôme | Cause probable et action |
|---|---|
| « CODEBERG_JETON absent du fichier .env » | fonctionnalité non configurée (section 8). |
| « Codeberg injoignable : GET /issues : HTTP 401 » ou « HTTP 403 » | jeton invalide, expiré, révoqué, non limité au bon dépôt ou sans permission `issue` en écriture : le régénérer (section 8.2). |
| « HTTP 404 » | `DEPOT_DEMANDES` incorrect ou tickets désactivés sur le dépôt. |
| « Codeberg injoignable : … ConnectError » | réseau sortant coupé ou Codeberg indisponible : aucune modification, nouvel essai au passage suivant. |
| « Étiquette « traitée » absente du dépôt » | créer les quatre étiquettes (section 8.1) ; les réponses sont tout de même publiées. |
| Ticket vide, sans formulaire | modèle non lu : vérifier la présence de `.forgejo/issue_template/analyse.yaml` sur la branche `pages` et que `pages` est la branche par défaut (section 5.1). Le lien « Version simplifiée » reste utilisable (titre commençant par `[Analyse]`). |
| Ticket sans réponse | `journalctl -u bbcloud-demandes -e` ; traitement reporté pendant la campagne (verrou) ; un ticket sans étiquette `analyse` ni titre `[Analyse]` est ignoré. |
| Étiquette `erreur` | erreur technique (site injoignable, publication impossible) : nouvel essai à chaque passage, trois au maximum, puis fermeture motivée. Cause : `journalctl -u bbcloud-demandes -p warning`. |

### Nettoyage d'anciennes versions

Les photos Wikimedia des premières versions ne sont plus utilisées. Suppression facultative, après sauvegarde : `rm -rf /opt/bleu-blanc-cloud/donnees/photos` et `sqlite3 /opt/bleu-blanc-cloud/donnees/bleublanccloud.db "DROP TABLE IF EXISTS photos"`.
