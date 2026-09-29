# Bleu Blanc Cloud 🇫🇷🇪🇺

> Observatoire indépendant et open source de la souveraineté numérique des organisations françaises.

**Bleu Blanc Cloud** mesure la dépendance numérique des organisations publiques françaises (communes, départements, régions…) vis-à-vis des fournisseurs extra-européens, en particulier ceux soumis au **Cloud Act** américain.

Pour chaque organisation, à partir de son nom de domaine, le projet :

1. réalise une **analyse passive** de son empreinte numérique externe (hébergement, messagerie, DNS, suites SaaS, services tiers, mesure d'audience) ;
2. calcule un **score de 0 à 100** et une **note de A à E** selon une [méthodologie publique et versionnée](docs/methodologie.md) ;
3. génère avec **Mistral** un rapport lisible par un décideur et un **plan de migration** vers des alternatives françaises ou européennes ;
4. publie le tout sur un **site statique** : <https://bleublanccloud.berachem.dev>.

> ⚠️ Le score ne reflète que l'empreinte **externe et visible publiquement**, pas les outils internes. Il est **indicatif**. Projet personnel, **sans aucun lien avec l'État ni avec l'Union européenne**.

## Structure du dépôt

| Dossier | Contenu |
|---|---|
| `scanner/` | CLI Python `bbcloud` : import des cibles, sondes passives, attribution, score, rapports IA, export |
| `site/` | Site Astro 100 % statique |
| `docs/` | Méthodologie, décisions d'architecture (ADR) |
| `deploy/` | Fichiers systemd et script de publication |

## Démarrage rapide (développement)

Prérequis : [uv](https://docs.astral.sh/uv/) et Node.js ≥ 22.12.

```bash
cp .env.example .env

# Scanner
cd scanner
uv sync
uv run pytest
uv run bbcloud --help

# Site
cd ../site
npm install
npm run build
```

## Licence

[EUPL-1.2](LICENSE) — © Berachem Markria ([berachem.dev](https://berachem.dev)).
