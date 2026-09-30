# ADR-0004 : domaine bleublanccloud.fr et redirection des anciennes adresses

- **Statut** : acceptée
- **Date** : 2026-09-30

## Contexte

Le site était publié sur `bleublanccloud.berachem.dev` (sous-domaine du site personnel de
l'auteur, zone DNS chez Cloudflare). Le domaine `bleublanccloud.fr` a été acheté chez
OVHcloud (zone DNS chez OVHcloud, DNSSEC actif) pour devenir l'adresse principale.

Contraintes :

- **git-pages** (Codeberg Pages) sert chaque nom d'hôte comme un **site distinct** : un
  déploiement est déclenché par un webhook dont l'URL désigne le domaine, et autorisé par
  l'enregistrement `TXT _git-pages-repository.<domaine>` qui liste les dépôts admis. Le
  contenu vient de la branche `pages` du dépôt.
- git-pages lit un fichier `_redirects` au format Netlify, avec redirection vers une autre
  adresse autorisée pour les statuts 3xx. Des règles limitées à un nom d'hôte
  (`//hote/*`) existent dans une version dérivée du logiciel, mais ne sont pas documentées
  par le projet principal : une règle mal comprise redirigerait le domaine principal vers
  lui-même.
- Un apex ne peut pas porter de `CNAME` et OVHcloud ne propose pas d'enregistrement `ALIAS`.
- Le site doit rester en ligne pendant la bascule, piloté par le serveur (aucune action
  manuelle dans le code au moment du changement).

## Décision

1. **`bleublanccloud.fr` (apex)** : enregistrements `A 217.197.84.141` et
   `AAAA 2a0a:4580:103f:c0de::2` (adresses de `codeberg.page` données par la documentation
   de Codeberg), `TXT _git-pages-repository` vers le dépôt du site.
2. **`www.bleublanccloud.fr` et `bleublanccloud.berachem.dev`** : servis par un **dépôt de
   redirection dédié** (`bleublanccloud-redirection`, contenu dans `deploy/redirection/`)
   dont le `_redirects` contient la seule règle `/* https://bleublanccloud.fr/:splat 301!`.
   Chaque domaine redirigé a son `TXT` vers ce dépôt et son webhook.
3. **Le domaine est un paramètre** : `DOMAINE_SITE` (`.env` du serveur, défaut
   `bleublanccloud.fr`) fixe les URL du site au build (canoniques, plan du site,
   `robots.txt`), celles des réponses aux tickets, le fichier `.domains` et le User-Agent
   du robot (construit à partir du domaine si `USER_AGENT` n'est pas renseigné). La bascule
   se fait en modifiant le `.env`, au moment où le nouveau domaine répond.
4. **Référentiel** : les adresses de Codeberg Pages appartiennent au réseau de
   l'association IN-Berlin (AS29670), ajoutée à `fournisseurs.yaml` (à vérifier) pour que
   l'apex, sans `CNAME` vers `codeberg.page`, soit attribué (niveau A) sur le scan du site.

## Conséquences

- Redirections permanentes côté serveur, chemin et paramètres conservés : les anciens liens
  et le référencement sont préservés. Les URL canoniques pointent vers `bleublanccloud.fr`
  dès la bascule.
- Si Codeberg change les adresses de `codeberg.page`, les `A`/`AAAA` de l'apex sont à mettre
  à jour à la main (le `CNAME` de `www` suit tout seul).
- Un dépôt supplémentaire à conserver ; son contenu ne change pas.
- Les enregistrements de `berachem.dev` (`CNAME` et `TXT`) sont à garder au moins un an.
