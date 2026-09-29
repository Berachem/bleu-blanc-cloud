# Bleu Blanc Cloud 🇫🇷🇪🇺

> Observatoire indépendant et open source de la souveraineté numérique des organisations françaises.
> <https://bleublanccloud.berachem.dev>

**Bleu Blanc Cloud** mesure la dépendance numérique des organisations publiques françaises (communes, départements, régions…) vis-à-vis des fournisseurs extra-européens, en particulier ceux soumis au **Cloud Act** américain.

Pour chaque organisation, à partir de son nom de domaine, le projet :

1. réalise une **analyse strictement passive** de son empreinte numérique externe : hébergement du site, messagerie, DNS, suites SaaS, services tiers chargés par le site, mesure d'audience ;
2. calcule un **score de 0 à 100** et une **note de A à E** selon une [méthodologie publique et versionnée](docs/methodologie.md), chaque point retiré étant justifié par une preuve ;
3. fait rédiger par **Mistral** un rapport lisible par un décideur et un **plan de migration** limité aux [alternatives françaises et européennes du référentiel](scanner/src/bleublanccloud/referentiels/alternatives.yaml) ;
4. publie le tout sur un **site 100 % statique** (carte de France, classements, une page par organisation), sans cookie, sans traceur et sans aucune ressource externe.

> ⚠️ Le score ne reflète que l'empreinte **externe et visible publiquement**, pas les outils internes. Il est **indicatif**. Projet personnel, **sans aucun lien avec l'État ni avec l'Union européenne**.

## Architecture

```
scanner/  CLI Python « bbcloud »
  cibles/      import : API Annuaire de l'administration + geo.api.gouv.fr
  sondes/      DNS, IP/ASN, HTTP (poli), TLS, RDAP — analyse passive
  analyse/     attribution → niveau A/B/C/D, détection des services (116 règles), score
  ia/          rapports Mistral (consignes versionnées, validation, cache, budget)
  stockage/    SQLite + migrations SQL numérotées
  export/      JSON statiques + schéma JSON du contrat de données
site/     Astro (sortie statique) : thème France/UE, carte SVG calculée au build
deploy/   systemd (campagne hebdomadaire, sauvegarde), publication Codeberg Pages, installateur
docs/     méthodologie publique, décisions d'architecture (ADR)
```

Voir [ADR-0001](docs/adr/0001-architecture.md) et [ADR-0002](docs/adr/0002-site-statique.md).

## Démarrage rapide (développement)

Prérequis : [uv](https://docs.astral.sh/uv/) et Node.js ≥ 22.12.

```bash
cp .env.example .env

# Scanner
cd scanner
uv sync
uv run pytest                 # tests sans réseau (réponses enregistrées, respx)
uv run bbcloud --help

# Site (avec les données de démonstration fictives)
cd ../site
npm install
npm run dev                   # http://localhost:4321
```

## Commandes `bbcloud`

| Commande | Rôle |
|---|---|
| `bbcloud referentiels maj` | plages IP des clouds, base ASN (IPinfo Lite), amorçage RDAP, contrôle SecNumCloud |
| `bbcloud referentiels verifier` | valide les YAML et liste les faits « à vérifier » |
| `bbcloud referentiels inconnus` | hébergeurs, MX et DNS non identifiés les plus fréquents (réseaux de transit listés à part) |
| `bbcloud scores recalculer [--dry-run] [--tous]` | réattribue les constats enregistrés et recalcule les scores après une mise à jour du référentiel, sans rescanner |
| `bbcloud scores couverture` | part du poids encore inconnue sur l'ensemble de l'observatoire, par catégorie |
| `bbcloud scanner berachem.dev [--json] [--enregistrer]` | scan unitaire et score |
| `bbcloud cibles importer --population-min 10000` | communes, départements, régions |
| `bbcloud cibles lister` · `bbcloud cibles ajouter` | liste, ajout manuel |
| `bbcloud campagne lancer [--limite N] [--dry-run] [--oui]` | campagne de scan (confirmation demandée) |
| `bbcloud rapports generer [--max N] [--dry-run]` | rapports IA avec estimation du coût |
| `bbcloud exporter --vers ../site/public/donnees` | fichiers JSON du site |
| `bbcloud schemas` | schéma JSON du contrat de données (types TypeScript : `npm run types`) |
| `bbcloud demo` | données de démonstration fictives |
| `bbcloud photos maj [--forcer] [--limite N]` | photos des communes (Wikidata → Wikimedia Commons, licences libres), auto-hébergées |
| `bbcloud publier` | export + build + publication sur Codeberg Pages |
| `bbcloud demandes traiter` · `bbcloud demandes lister` | analyses sur demande (tickets « Analyser mon site » sur Codeberg) |

## Qualité

| Vérification | Commande |
|---|---|
| Lint et format Python | `uv run ruff check . && uv run ruff format --check .` |
| Typage (strict sur `analyse/`) | `uv run mypy` |
| Tests et couverture | `uv run pytest --cov` (≈ 730 tests) |
| Types du site | `npm run verifier` |
| Aucune requête externe, aucun cookie | `npm run build && npm run verifier:externe` |

Le workflow [`qualite.yml`](.github/workflows/qualite.yml) lance l'ensemble à chaque push.

## Éthique

- Analyse passive uniquement : aucune soumission de formulaire, aucune authentification, aucun test de vulnérabilité.
- Robot identifié, 5 pages maximum par site, 1 requête par seconde et par domaine, respect de `robots.txt`.
- Liste de **retraits** vérifiée avant toute requête ; droit de réponse sous 30 jours.
- Aucune donnée personnelle collectée ni publiée ; l'IA ne reçoit que des constats techniques (adresses e-mail masquées).
- Pendant le développement, seuls `berachem.dev`, `example.org` et `example.com` sont scannés.

## Mise en production

👉 [Guide pas à pas sur Proxmox (LXC Debian 12) et Codeberg Pages](deploy/README.md)

## Licence et crédits

- Code : [EUPL-1.2](LICENSE) — © Berachem Markria ([berachem.dev](https://berachem.dev)).
- Police [Luciole](https://www.luciole-vision.com/) © Laurent Bourcellier & Jonathan Perez — CC-BY 4.0.
- Contours des départements : IGN Admin Express COG (Licence Ouverte Etalab 2.0), via [france-geojson](https://github.com/gregoiredavid/france-geojson).
- Données des organisations : API Annuaire de l'administration (DILA) et API Découpage administratif, Licence Ouverte.
