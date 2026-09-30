# Redirection de Bleu Blanc Cloud

Ce dépôt sert uniquement à rediriger les anciennes adresses et `www` vers
**<https://bleublanccloud.fr>** (redirection permanente 301, chemin conservé), via
Codeberg Pages (git-pages).

- `_redirects` : `/* https://bleublanccloud.fr/:splat 301!` (le `!` force la redirection
  même pour `index.html`).
- `index.html` : secours sans redirection serveur (lien, balise canonique, rafraîchissement).

Source et mode d'emploi : dossier `deploy/redirection/` du
[dépôt du projet](https://github.com/Berachem/bleu-blanc-cloud) et section « Migration de
domaine » de `deploy/README.md`.
