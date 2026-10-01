# ADR-0005 : zoom et fond de plan IGN à la demande sur la carte de situation

- **Statut** : acceptée
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
| Fond IGN chargé dès l'affichage | Requête vers un tiers pour chaque visiteur, sans qu'il l'ait demandé |

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
4. **Fond de plan IGN à la demande** : un sélecteur « Fond de carte » propose *Contours*
   (par défaut), *Plan IGN* et *Photo aérienne*. Les deux derniers chargent les tuiles WMTS de
   la **Géoplateforme de l'IGN** (`data.geopf.fr`, couches `GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2`
   et `ORTHOIMAGERY.ORTHOPHOTOS`, sans clé, Licence Ouverte Etalab 2.0, attribution
   « IGN – Géoplateforme » affichée sous la carte). **Aucune tuile n'est demandée tant que le
   visiteur n'a pas fait ce choix.** Le choix est mémorisé dans le stockage local
   (`bbc-fond-carte`), effacé au retour sur *Contours* ; jamais de cookie.
5. **Liens sortants** « Voir sur Géoportail (IGN) · OpenStreetMap », centrés sur le territoire,
   pour une exploration complète hors du site.
6. Cartes de région d'outre-mer présentées en encart (projection propre) : sans projection
   exploitable, elles gardent le zoom mais pas de fond de plan.

## Conséquences

- **Par défaut, rien ne change pour le visiteur** : aucune requête externe, aucun cookie.
  Le script `verifier-requetes.mjs` le contrôle sur toutes les pages, puis active le fond
  « Plan IGN » sur une fiche (tuiles simulées) et vérifie que seules des requêtes vers
  `data.geopf.fr` partent, sans cookie.
- **Exception assumée et documentée** à la règle « aucune ressource externe » : le visiteur
  qui active le fond de plan transmet son adresse IP et la zone affichée à l'IGN,
  établissement public français. Les mentions légales le précisent (tableau des traitements
  et section « Cookies et stockage local ») ; la règle correspondante de `docs/CLAUDE.md` est
  nuancée en conséquence.
- **Dogfooding** : le scan du site par Bleu Blanc Cloud analyse le HTML publié, qui ne
  contient aucune URL de tuile ; et même détecté, l'IGN est un fournisseur de niveau A. La
  note A du site n'est pas affectée.
- **Poids** : le script client pèse ≈ 7 Ko (3 Ko compressé, aucune dépendance) ; le contour plus fin
  alourdit les fiches communales de quelques Ko, à remesurer sur la campagne complète.
- **Mise à jour des contours** : la nouvelle tolérance ne s'applique qu'aux contours
  téléchargés après ce changement. Sur un serveur déjà installé, lancer une fois
  `uv run bbcloud cibles contours --forcer` puis republier (voir le guide de déploiement).
- **Disponibilité** : si la Géoplateforme ne répond pas, un message discret s'affiche et les
  contours restent lisibles ; le site ne dépend pas de l'IGN pour fonctionner.
