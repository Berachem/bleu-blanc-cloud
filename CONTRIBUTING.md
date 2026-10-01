# Contribuer à Bleu Blanc Cloud

Merci de l'intérêt porté au projet. Les contributions sont bienvenues, en particulier :

- **les référentiels** : fournisseurs, règles de détection de services, alternatives européennes, réseaux de transit ;
- **les corrections** : erreur d'attribution, bogue du scanner, problème d'affichage ou d'accessibilité sur le site ;
- **la documentation** : méthodologie, runbook, décisions d'architecture.

Pour une question sur la fiche d'une organisation (correction, droit de réponse, retrait), utiliser la page [bleublanccloud.fr/retrait](https://bleublanccloud.fr/retrait/) plutôt qu'un ticket. Pour une vulnérabilité, suivre la [politique de sécurité](SECURITY.md) et ne pas ouvrir de ticket public.

## Avant de commencer

Pour tout changement important (nouvelle catégorie de score, nouvelle sonde, changement d'architecture), ouvrir d'abord un ticket pour en discuter. Les choix structurants sont consignés dans les [ADR](docs/adr/) ; la spécification complète du projet se trouve dans [`docs/CLAUDE.md`](docs/CLAUDE.md).

## Environnement de développement

Prérequis : [uv](https://docs.astral.sh/uv/) et Node.js 22.12 ou plus récent.

```bash
git clone https://github.com/Berachem/bleu-blanc-cloud.git
cd bleu-blanc-cloud
cp .env.example .env

cd scanner && uv sync && uv run pytest
cd ../site && npm install && npm run dev
```

Le site fonctionne avec des données de démonstration fictives : aucune clé n'est nécessaire pour développer.

## Règles du projet

### Langue et nommage

- Tout est rédigé en **français** : interface, documentation, commentaires, docstrings, messages d'erreur et de commit.
- Les noms de variables, fonctions, classes, modules et fichiers sont en français, **sans accents** : `nom_domaine`, `calculer_score()`, `class FournisseurCloud`. Exceptions : mots-clés du langage, API de bibliothèques tierces et sigles techniques consacrés (`dns`, `ip`, `url`, `http`, `mx`, `asn`, `tls`, `json`).

### Éthique et réseau

- Le scanner reste **strictement passif** : aucune soumission de formulaire, aucune authentification, aucun test de vulnérabilité sur les sites analysés.
- Pendant le développement, seuls `berachem.dev`, `example.org` et `example.com` peuvent être analysés. **Aucun scan en masse** sur de vrais domaines.
- Les tests n'utilisent **jamais le réseau** : réponses enregistrées, fixtures et simulations (`respx`).
- Aucun secret dans le dépôt (`.env`, clés, jetons). Les données personnelles ne sont ni collectées ni publiées.

### Référentiels

Chaque fait ajouté à un fichier de `scanner/src/bleublanccloud/referentiels/` (pays du siège, maison mère, exposition au Cloud Act, offre SecNumCloud, numéro de système autonome…) doit être accompagné d'**au moins une URL source**. Un fait non vérifié est marqué `a_verifier: true`. Aucun fait ne doit être supposé ou inventé.

```yaml
- id: exemple
  nom: Exemple SAS
  pays_siege: FR
  soumis_cloud_act: false
  asn: [64500]
  motifs_domaines: ["exemple-hebergeur.fr"]
  categories: [hebergement]
  sources:
    - "https://…"
  a_verifier: true
```

Chaque règle de détection doit être couverte par au moins un test. Un réseau de transit (opérateur qui achemine le trafic d'autres réseaux) se déclare dans `transitaires.yaml`, jamais comme fournisseur.

### Méthodologie

Toute modification des règles de calcul du score crée une **nouvelle version** de la méthodologie (`VERSION_METHODO` dans `analyse/score.py`) et une entrée dans l'historique de [`docs/methodologie.md`](docs/methodologie.md). Une modification des consignes de l'IA incrémente `VERSION_INVITE` dans `ia/invites.py`.

### Site

- **Aucune ressource externe** (police, script, image, carte), aucun cookie, aucun traceur. Seule exception, décrite dans l'[ADR-0005](docs/adr/0005-zoom-et-fond-de-plan-ign.md) : le fond de plan IGN des cartes de situation, chargé uniquement si le visiteur le choisit.
- Pas de DSFR, de police ou de logo Marianne, ni de « gouv » dans les noms : le site ne doit jamais ressembler à un site officiel de l'État ou de l'Union européenne.
- Accessibilité visée : RGAA / WCAG 2.1 AA (contrastes, focus visible, textes alternatifs).
- Ton factuel : le score décrit une dépendance, pas une faute.

## Vérifications avant une demande de fusion

```bash
# Scanner (dossier scanner/)
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest

# Site (dossier site/)
npm run verifier
npm test
npm run build && npm run verifier:externe
```

Le workflow [`qualite.yml`](.github/workflows/qualite.yml) exécute les mêmes vérifications sur chaque demande de fusion.

## Commits et demandes de fusion

- Messages au format [Conventional Commits](https://www.conventionalcommits.org/fr/), en français : `feat(sondes): ajout de la sonde MX`, `fix(site): contraste du bouton de recherche`.
- Une demande de fusion par sujet, avec une description de ce qui change, pourquoi, et comment le vérifier.
- Code typé et testé ; documentation mise à jour si nécessaire (README, méthodologie, ADR).

## Licence

Le projet est publié sous licence [EUPL-1.2](LICENSE). En proposant une contribution, vous acceptez qu'elle soit diffusée sous cette licence.

## Conduite

Les échanges restent courtois, factuels et bienveillants, avec les contributeurs comme avec les organisations analysées. Les propos insultants, discriminatoires ou harcelants ne sont pas acceptés.
