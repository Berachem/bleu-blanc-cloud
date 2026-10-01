# ADR-0005 : zoom et fond de plan IGN sur la carte de situation

- **Statut** : acceptée (révisée : « Plan IGN » devient le fond par défaut, voir l'historique)
- **Date** : 2026-10-01
- **Complète** : [ADR-0003](0003-illustration-des-fiches.md) (carte de situation des fiches)

## Contexte

La carte de situation d'une fiche (ADR-0003) est un SVG calculé au build : contour du
département et commune colorée selon sa note. Elle situe bien le territoire, mais :

- elle ne permet pas de **zoomer** : une petite commune n'occupe que quelques pixels ;
- son contour, simplifié à ≈ 100 m, devient grossier dès qu'on l'agrandit ;
- elle n'offre **aucun repère réel** (routes, bâti, relief) pour qui veut aller plus loin.

Un fond de plan « réaliste » suppose de charger des images (tuiles) depuis un service
cartographique, ce qui heurte trois règles du projet : aucune ressource externe, zéro
dépendance américaine dans le produit publié, note A du site sur son propre scan.

Options étudiées :

| Option | Écartée parce que |
|---|---|
| Tuiles OpenStreetMap, Carto, Mapbox, Google | Serveurs hors de France ou soumis au Cloud Act, conditions d'usage restrictives (OSM interdit l'usage intensif de ses serveurs de tuiles) |
| Tuiles hébergées par le site (export d'images) | Plusieurs centaines de Mo à plusieurs Go pour la France entière jusqu'au niveau de la rue, intenable sur Codeberg Pages |
| Bibliothèque cartographique (Leaflet, MapLibre, OpenLayers) | 40 à 250 Ko de JavaScript pour un besoin limité ; le tracé existant est déjà en SVG |

## Décision

1. **Zoom et déplacement maison**, sans bibliothèque : le script `lib/carte-situation.ts`
   modifie la `viewBox` du SVG (le tracé reste net, `vector-effect: non-scaling-stroke` garde
   l'épaisseur des traits). Commandes : boutons (zoomer, dézoomer, centrer sur l'organisation,
   vue d'ensemble), Ctrl ou ⌘ + molette (la molette seule fait défiler la page, une aide
   s'affiche), pincement, double-clic, glisser une fois la carte agrandie. Zoom maximal × 64.
   Sans JavaScript, la carte reste le SVG statique.
2. **Contour plus fin** : tolérance de simplification des communes abaissée à 0,0002°
   (≈ 15 à 22 m) côté scanner, tracé de la commune au centième d'unité SVG (les fonds de
   département et de région gardent la précision au pixel).
3. **Projection Mercator** pour toutes les cartes de situation (au lieu de la conique conforme
   de Lambert), pour que les tracés se superposent exactement aux tuiles Web Mercator. Les
   paramètres de la projection (`k`, `tx`, `ty`) sont exportés dans `data-projection` ; le
   script en déduit les tuiles à afficher. À l'échelle d'un département ou d'une région, la
   différence de forme avec Lambert est imperceptible.
4. **Fond de plan IGN, « Plan IGN » par défaut** : un sélecteur « Fond de carte » propose
   *Plan IGN* (par défaut), *Photo aérienne* et *Contours*. Les deux premiers chargent les
   tuiles WMTS de la **Géoplateforme de l'IGN** (`data.geopf.fr`, couches
   `GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2` et `ORTHOIMAGERY.ORTHOPHOTOS`, sans clé, Licence
   Ouverte Etalab 2.0, attribution « IGN – Géoplateforme » affichée sous la carte).
   *Contours* n'appelle aucun service extérieur. Un choix différent du défaut est mémorisé
   dans le stockage local (`bbc-fond-carte`) ; jamais de cookie. Sans JavaScript, la carte
   reste le SVG des contours et aucune tuile n'est demandée.
5. **Liens sortants** « Voir sur Géoportail (IGN) · OpenStreetMap », centrés sur le territoire,
   pour une exploration complète hors du site.
6. Cartes de région d'outre-mer présentées en encart (projection propre) : sans projection
   exploitable, elles gardent le zoom mais pas de fond de plan.

## Conséquences

- **Exception assumée et documentée** à la règle « aucune ressource externe » : sur les
  fiches dotées d'une carte de situation, le navigateur du visiteur transmet par défaut son
  adresse IP et la zone affichée à l'IGN, établissement public français. Les mentions
  légales le précisent (tableau des traitements et section « Cookies et stockage local ») ;
  la règle correspondante de `docs/CLAUDE.md` est nuancée en conséquence. Toutes les autres
  pages restent sans aucune requête externe.
- **Contrôle automatique** : `verifier-requetes.mjs` (tuiles simulées, sans réseau) vérifie
  qu'aucune page ne contacte de tiers, à l'exception des fiches avec carte qui ne doivent
  appeler que `data.geopf.fr` ; puis que le choix « Contours » est mémorisé et supprime
  toute requête externe après rechargement. Jamais de cookie.
- **Dogfooding** : le scan du site par Bleu Blanc Cloud analyse le HTML publié, qui ne
  contient aucune URL de tuile ; et même détecté, l'IGN est un fournisseur de niveau A. La
  note A du site n'est pas affectée.
- **Poids** : le script client pèse ≈ 7 Ko (3 Ko compressé, aucune dépendance) ; le contour plus fin
  alourdit les fiches communales de quelques Ko, à remesurer sur la campagne complète.
- **Mise à jour des contours** : la nouvelle tolérance ne s'applique qu'aux contours
  téléchargés après ce changement. Sur un serveur déjà installé, lancer une fois
  `uv run bbcloud cibles contours --forcer` puis republier (voir le guide de déploiement).
- **Disponibilité** : si la Géoplateforme ne répond pas (panne, bloqueur, réseau filtré), un
  message discret s'affiche et les contours restent lisibles ; le site ne dépend pas de l'IGN
  pour fonctionner.

## Historique

- **2026-10-01, première version** : *Contours* par défaut, fond IGN chargé seulement sur
  choix explicite du visiteur, pour qu'aucune page ne contacte de tiers sans action de sa
  part.
- **2026-10-01, révision** : *Plan IGN* par défaut, placé en premier dans le sélecteur, à la
  demande de l'auteur : le plan rend la carte nettement plus lisible et informative, et
  l'IGN est un opérateur public français, sans traceur ni cookie. Le choix *Contours* reste
  proposé et mémorisé pour qui ne veut aucune requête externe.
