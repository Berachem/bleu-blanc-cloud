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

Les autres valeurs (politesse du robot, chemins) peuvent rester telles quelles.

---

## 4. Codeberg Pages (git-pages) et nom de domaine

Codeberg impose désormais **git-pages** aux nouveaux comptes : l'ancien serveur Pages v2 (fichier `.domains`) ne fonctionne plus pour eux. Avec git-pages, le domaine est **autorisé par le DNS** (enregistrement TXT) et chaque déploiement est **déclenché par un webhook** sur la branche `pages`.

Fais ces étapes **dans l'ordre, avant la première publication** (étape 5) : le certificat HTTPS n'est demandé qu'au premier déploiement réussi.

### 4.1 Dépôt de publication

1. Sur Codeberg, crée un dépôt **public et vide** nommé `bleublanccloud-pages` (git-pages le clone en HTTPS, sans identifiant).
2. *Paramètres du dépôt → Clés de déploiement → Ajouter une clé* : colle la clé publique affichée par l'installateur
   (ou `cat /home/bbcloud/.ssh/id_ed25519_codeberg.pub`) et coche **Activer l'accès en écriture** : c'est elle que `publier.sh` utilise pour pousser.

### 4.2 Enregistrements DNS

Dans la zone DNS de `berachem.dev`, ajoute :

| Type | Nom | Valeur |
|---|---|---|
| `CNAME` | `bleublanccloud` | `codeberg.page.` |
| `TXT` | `_git-pages-repository.bleublanccloud` | `https://codeberg.org/<ton-pseudo>/bleublanccloud-pages.git` |

- Le **CNAME pointe vers `codeberg.page.`** tout court, et non plus vers `bleublanccloud-pages.<ton-pseudo>.codeberg.page.` (forme de l'ancien serveur).
- Le **TXT** se place sur le sous-domaine `_git-pages-repository.<sous-domaine>`, soit ici `_git-pages-repository.bleublanccloud.berachem.dev`. Il contient l'**URL HTTPS de clonage** du dépôt (avec `.git`) : c'est lui qui autorise ce dépôt à publier sur ce domaine.
- ⚠️ **Chez Cloudflare, mets le CNAME en « DNS only » (nuage gris)**. Proxifié (nuage orange), le site serait servi par Cloudflare : Codeberg ne pourrait pas émettre le certificat, et le site perdrait sa note A sur son propre scan (hébergement masqué par un CDN américain → niveau C).
- Si la zone contient des enregistrements **CAA**, ils doivent autoriser Let's Encrypt (`0 issue "letsencrypt.org"`).

Vérifie la propagation (depuis n'importe quelle machine ; dans le conteneur : `apt-get install -y dnsutils`) :

```bash
dig +short CNAME bleublanccloud.berachem.dev                    # → codeberg.page.
dig +short TXT _git-pages-repository.bleublanccloud.berachem.dev # → "https://codeberg.org/<ton-pseudo>/bleublanccloud-pages.git"
```

### 4.3 Webhook de déploiement

Dans le dépôt `bleublanccloud-pages` : *Paramètres → Webhooks → Ajouter un webhook → **Forgejo***.

| Champ | Valeur |
|---|---|
| URL cible | `http://bleublanccloud.berachem.dev/` (**http://** pour le tout premier déploiement, voir ci-dessous) |
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
3. Après quelques minutes, `https://bleublanccloud.berachem.dev` doit répondre avec un certificat valide (`curl -sI https://bleublanccloud.berachem.dev`).
4. **Modifie alors l'URL cible du webhook en `https://bleublanccloud.berachem.dev/`** : une fois le certificat émis, le serveur peut rediriger le HTTP vers le HTTPS, ce qui ferait échouer les livraisons suivantes.

> 💡 **Publication faite avant le webhook ?** Le site n'est alors pas déployé et une nouvelle publication sans changement ne pousse rien. Relance la dernière livraison depuis *Livraisons récentes* (bouton de renvoi), ou pousse un commit vide sur `pages` :
> ```bash
> su - bbcloud -c 'cd /opt/bleu-blanc-cloud/donnees/depot-pages && git commit --allow-empty -qm "redéploiement" && git push -q origin pages'
> ```

> ℹ️ `publier.sh` écrit toujours un fichier `.domains` : git-pages l'ignore (l'autorisation passe par le TXT), il ne sert qu'aux comptes encore sur l'ancien serveur. git-pages ne redirige plus `/page` vers `/page.html`, ce qui ne gêne pas le site : Astro génère des dossiers (`/methodologie/index.html`) et les liens internes se terminent par `/`.

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
- La chaîne hebdomadaire (`deploy/campagne-hebdomadaire.sh`) : `uv sync` → `referentiels maj` → `cibles importer` → `campagne lancer --oui` → `rapports generer --oui` (seulement si la clé Mistral est présente ; le cache évite tout appel si rien n'a changé) → `publier`.
- Durée indicative d'une campagne complète (~1 000 organisations, 1 requête/s/domaine, 10 scans en parallèle) : **30 à 60 minutes**.

### Mise à jour automatique du code (toutes les heures)

`bbcloud-maj-auto.timer` est activé par l'installateur. Chaque heure, `deploy/maj-auto.sh` :

1. fait un `git fetch` et **s'arrête aussitôt s'il n'y a rien de nouveau** sur `main` ;
2. sinon : `git merge --ff-only`, `uv sync`, puis `npm ci` **seulement si** `site/package-lock.json` a changé ;
3. lance les tests (`pytest`) ;
4. **uniquement s'ils passent**, régénère et publie le site à partir des données déjà en base (export → build → push), **sans relancer de scan**. Tant que la base ne contient aucune organisation notée, rien n'est publié.

Si les tests échouent, le serveur **revient à la version précédente**, rien n'est publié, le service passe en échec (`systemctl --failed`) et ce commit n'est plus retenté : il faut pousser un correctif.

Un verrou (`flock` sur `donnees/bbcloud.verrou`) empêche la mise à jour et la campagne hebdomadaire de tourner en même temps : pendant une campagne, la mise à jour est reportée à l'heure suivante ; pendant une mise à jour, la campagne attend sa fin (2 h au maximum). La campagne ne tire plus le code elle-même : elle tourne toujours sur une version qui a passé les tests.

```bash
systemctl start bbcloud-maj-auto.service   # lancer une vérification tout de suite
journalctl -u bbcloud-maj-auto -f          # suivre les journaux (priorités : -p warning pour les alertes)
systemctl list-timers 'bbcloud*'           # prochaines exécutions
systemctl disable --now bbcloud-maj-auto.timer   # suspendre les mises à jour automatiques
```

---

## 7. Sauvegardes et restauration

- `bbcloud-sauvegarde.timer` : tous les jours à 2 h, `sqlite3 .backup` vers `/mnt/sauvegardes` (compressé, 30 jours conservés ; réglable dans `/etc/bbcloud/sauvegarde.env`).
- Lancer une sauvegarde : `systemctl start bbcloud-sauvegarde.service`
- Restaurer :
  ```bash
  systemctl stop bbcloud-campagne.timer bbcloud-maj-auto.timer
  gunzip -c /mnt/sauvegardes/bleublanccloud-AAAA-MM-JJ.db.gz > /opt/bleu-blanc-cloud/donnees/bleublanccloud.db
  chown bbcloud:bbcloud /opt/bleu-blanc-cloud/donnees/bleublanccloud.db
  systemctl start bbcloud-campagne.timer bbcloud-maj-auto.timer
  ```
- Pense aussi à inclure le conteneur dans tes sauvegardes Proxmox (*Datacenter → Backup*).

---

## 8. Miroir du code sur Codeberg

Codeberg → **+** → *Nouvelle migration* → *GitHub* → URL `https://github.com/Berachem/bleu-blanc-cloud` → coche **« Ce dépôt sera un miroir »**. Codeberg se synchronise ensuite automatiquement.

Tant que le dépôt GitHub est privé, renseigne dans le formulaire de migration un jeton GitHub en lecture seule (champ du jeton d'accès), ou attends simplement le passage en public pour créer le miroir.

---

## 9. Avant d'ouvrir le site au public ✅

- [ ] **Mentions légales** : complète `site/src/config.ts` (adresse de l'éditeur ou recours à l'anonymat LCEN, adresse de contact) — l'adresse de l'hébergeur Codeberg e.V. est aussi à vérifier.
- [ ] **Adresse de contact** pour les retraits et corrections (`SITE.contact`, actuellement `contact@berachem.dev`).
- [ ] **Référentiels** : relire les faits marqués « à vérifier » (`uv run bbcloud referentiels verifier` liste les remarques), puis passer `a_verifier: false` fait par fait.
- [ ] **Campagne de test** (10 organisations) relue sur le site local.
- [ ] **Première campagne complète** lancée puis publiée.
- [ ] **Webhook Codeberg** repassé en `https://` après l'émission du certificat (étape 4.4).
- [ ] **Dogfooding** : `bbcloud scanner bleublanccloud.berachem.dev` donne A.
- [ ] **Dépôt GitHub passé en public** : le site renvoie vers le code source, la méthodologie et les référentiels.

Toute modification de ces fichiers se fait dans le dépôt GitHub : le conteneur récupère la nouvelle version dans l'heure (`bbcloud-maj-auto`), après passage des tests, et republie le site.

---

## 10. Opérations courantes

| Besoin | Action |
|---|---|
| Demande de **retrait** d'une organisation | ajouter le domaine dans `scanner/src/bleublanccloud/referentiels/retraits.yaml`, committer ; il n'est plus jamais analysé et sa fiche disparaît à la publication suivante |
| Ajouter un **hébergeur** non identifié | compléter `fournisseurs.yaml` (avec sources) à partir de `bbcloud referentiels inconnus` |
| Changer la **méthodologie** | nouvelle version dans `analyse/score.py` + entrée dans `docs/methodologie.md` |
| Changer les **consignes IA** | incrémenter `VERSION_INVITE` dans `ia/invites.py` (les rapports seront régénérés) |
| Mettre à jour le code tout de suite | `systemctl start bbcloud-maj-auto.service` (tests puis republication) |

---

## 11. Dépannage

| Symptôme | Piste |
|---|---|
| `referentiels maj` : « IPINFO_TOKEN absent » | normal sans jeton : le scanner interroge RIPEstat (plus lent). Ajoute `IPINFO_TOKEN` dans `.env`. |
| Hébergeurs souvent « inconnus » | lancer `referentiels maj` ; compléter `fournisseurs.yaml` avec `referentiels inconnus`. |
| `Permission denied (publickey)` sur **github.com** (dépôt privé) | la clé de déploiement n'est pas (ou plus) dans *Settings → Deploy keys* du dépôt. Clé à ajouter : `cat /home/bbcloud/.ssh/id_ed25519_github.pub`. Test : `su - bbcloud -c 'ssh -T git@github.com'` (réponse attendue : « successfully authenticated »). |
| L'installateur choisit le mauvais mode (public/privé) | relancer avec `DEPOT_PRIVE=1 bash installer.sh` ou `DEPOT_PRIVE=0 bash installer.sh`. |
| `Permission denied (publickey)` à la publication | la clé de déploiement Codeberg n'a pas l'accès en écriture, ou `DEPOT_PAGES` n'est pas en SSH. Test : `su - bbcloud -c 'ssh -T git@codeberg.org'`. |
| Message mentionnant l'**« old pages server »** | la requête arrive sur l'ancien serveur Pages v2, fermé aux nouveaux comptes. Causes possibles : CNAME encore à l'ancienne forme (`bleublanccloud-pages.<ton-pseudo>.codeberg.page.`) au lieu de `codeberg.page.` ; TXT `_git-pages-repository.bleublanccloud` absent ou différent de l'URL HTTPS exacte du dépôt (avec `.git`) ; aucun déploiement git-pages encore effectué (webhook absent, filtré sur une autre branche que `pages`, ou jamais déclenché). Corriger le DNS (`dig`, étape 4.2), vérifier le webhook, puis redéclencher un déploiement (étape 4.4). |
| **`tls: internal error`** (ou `tlsv1 alert internal error` avec curl, `SSL_ERROR_INTERNAL_ERROR_ALERT` dans Firefox) | le certificat HTTPS n'est pas (encore) émis. Il n'est demandé qu'après un **déploiement réussi par le webhook** : vérifier dans *Livraisons récentes* qu'une livraison a abouti (code 2xx) avec une URL cible en **`http://`** ; sinon corriger l'URL et relancer la livraison. Vérifier aussi : CNAME en « DNS only » chez Cloudflare, TXT présent, enregistrements CAA autorisant `letsencrypt.org`. Puis patienter quelques minutes. Outil officiel de diagnostic : `curl -fsSL https://troubleshoot.codeberg.page/verify.sh -o verify.sh`, relire le script, puis `bash verify.sh bleublanccloud.berachem.dev`. |
| Le site affiche encore une ancienne version | contrôler la branche `pages` du dépôt Codeberg et la dernière livraison du webhook (une URL cible restée en `http://` après l'émission du certificat peut faire échouer les livraisons : la passer en `https://`). |
| `npm run build` échoue par manque de mémoire | passer le conteneur à 3–4 Go de RAM. |
| Beaucoup de « robots.txt injoignable » | réseau sortant filtré ou sites en panne : le robot n'analyse alors aucune page, par respect de la RFC 9309. |
| `bbcloud-maj-auto` en échec : « Tests en échec » | le serveur est resté sur l'ancienne version. Lire `journalctl -u bbcloud-maj-auto -p warning`, corriger dans le dépôt et pousser : le nouveau commit est testé à l'heure suivante. |
| `bbcloud-maj-auto` : « Fusion en avance rapide impossible » | des fichiers ont été modifiés à la main sur le serveur : `su - bbcloud -c 'git -C /opt/bleu-blanc-cloud status'`, puis annuler ces modifications (le code se modifie dans le dépôt GitHub). |
| `bbcloud-maj-auto` : « mise à jour reportée » | normal pendant la campagne hebdomadaire (verrou partagé) : nouvel essai à l'heure suivante. |
| Rapports IA en erreur | `journalctl -u bbcloud-campagne` ; vérifier la clé et le quota Mistral ; les rapports en erreur sont retentés à la campagne suivante. |
