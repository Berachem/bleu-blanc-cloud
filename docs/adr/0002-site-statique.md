# ADR-0002 — Site statique sans aucune ressource externe

- **Statut** : accepté
- **Date** : 2026-09-29

## Contexte

Le site doit être cohérent avec son sujet (aucune dépendance extra-européenne), accessible
(WCAG 2.1 AA / RGAA), léger (page d'accueil < 200 Ko, Lighthouse ≥ 95) et ne jamais ressembler
à un site officiel de l'État ou de l'Union européenne.

## Décision

- **Astro en sortie statique**, CSS maison à variables (`src/styles/theme.css`), aucun framework CSS.
- **Police Luciole auto-hébergée** (CC-BY 4.0), réduite à un sous-ensemble latin en WOFF2
  (~10 Ko par graisse) par `site/scripts/polices.py`.
- **Carte générée au build** : `scripts/preparer-carte.mjs` simplifie une fois les contours IGN
  (france-geojson) en TopoJSON versionné (~45 Ko) ; le composant `CarteFrance.astro` calcule
  les chemins SVG avec `d3-geo` au moment de la construction. Le navigateur ne charge aucune
  bibliothèque cartographique ni tuile. Les DROM sont présentés en encadrés.
- **JavaScript minimal et facultatif** : recherche instantanée (index `/recherche.json` chargé à
  la première saisie) et filtres/tri des classements. Sans JavaScript, toutes les données
  restent accessibles (liste complète, tableau des départements).
- **Contrat de données typé** : les types TypeScript sont générés depuis le schéma JSON
  exporté par pydantic (`bbcloud schemas` puis `npm run types`).
- **Données de démonstration fictives** (`src/donnees-demo`) utilisées tant qu'aucun export réel
  n'est présent dans `public/donnees` ; un bandeau l'indique sur chaque page.
- **Vérification automatique** : `npm run verifier:externe` visite toutes les pages (thèmes clair
  et sombre) dans Chromium et échoue à la moindre requête externe ou au moindre cookie.

## Conséquences

- Mesures du 2026-09-29 (données de démonstration) : Lighthouse 100/100 dans toutes les
  catégories (accueil, fiche organisation, classements, carte, méthodologie, alternatives,
  à propos) ; page d'accueil ≈ 117 Ko de HTML (≈ 35 Ko compressé) + 20 Ko de police.
- Pas d'en-tête CSP possible sur Codeberg Pages ; les petits scripts sont insérés dans la page
  par Astro. La garantie « aucune ressource externe » est vérifiée par le test automatique.
- La compression HTML d'Astro est désactivée : elle supprimait des espaces entre texte et liens.
