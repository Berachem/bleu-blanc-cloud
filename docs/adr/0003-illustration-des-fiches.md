# ADR-0003 : illustration des fiches — des photos Wikimedia à la carte de situation

- **Statut** : acceptée (révisée : la carte de situation remplace les photos)
- **Date** : 2026-09-29 (photos) · révision 2026-09-29 (carte de situation)

## Contexte

Les fiches des organisations gagnent à montrer d'un coup d'œil de quel territoire il s'agit.

**Première décision : photos.** L'API Unsplash a été écartée : ses conditions imposent de
charger les images depuis ses serveurs (« hotlinking » obligatoire, pour comptabiliser les
vues). Chaque fiche aurait fait une requête vers un service américain qui suit l'affichage,
contre trois règles du projet : aucune ressource externe, zéro dépendance américaine dans le
produit publié, note A du site sur son propre scan. Nous avions donc retenu l'image principale
Wikidata (P18) de chaque commune, sous licence libre, téléchargée par le serveur depuis
Wikimedia Commons et servie par le site lui-même, avec l'auteur et la licence.

**Pourquoi revenir sur ce choix.** À l'usage, les photos présentaient plusieurs défauts :

- **poids** : 100 à 300 Ko par fiche, soit plusieurs centaines de Mo pour 1 200 fiches dans le
  dépôt de publication, et la première image de la page la plus lourde de loin ;
- **couverture inégale** : pas d'image principale ou licence non libre pour une partie des
  communes, d'où un mélange de photos et d'illustrations de repli ;
- **pertinence** : l'image choisie par Wikidata (vue aérienne, monument, blason…) n'apporte
  pas d'information utile au sujet de l'observatoire ;
- **maintenance** : une étape de campagne supplémentaire, trois services (Wikidata, Commons,
  serveur d'images) à joindre, des crédits et licences à suivre photo par photo.

## Décision

Chaque fiche affiche une **carte de situation** en SVG, calculée **au build** avec d3-geo :

- **commune** : contour du département en neutre, commune remplie avec la couleur de sa note
  (bordure au contraste du texte, visible en mode sombre comme en mode clair) ; un cercle de
  repérage entoure les communes trop petites pour être vues d'un coup d'œil ;
- **département** : sa silhouette dans sa région ;
- **région** : sa silhouette dans la France (encart pour l'outre-mer) ;
- **fiche sur demande** (sans territoire) ou contour manquant : illustration maison.

Sources des contours, toutes sous **Licence Ouverte Etalab 2.0** :

- communes : API Découpage administratif (`geo.api.gouv.fr`, tracés IGN), un contour demandé
  **par code INSEE lors de l'import des cibles**, simplifié (Douglas-Peucker, ≈ 100 m) et
  stocké en base ; seuls les contours manquants sont redemandés ;
- départements et régions : IGN Admin Express COG via france-geojson, la source déjà utilisée
  pour la carte de France ; fond préparé une fois (`npm run carte`), régions obtenues par
  fusion des départements (frontières identiques), simplification relative à la taille de
  chaque département.

Le SVG est `role="img"` avec un `aria-label` (« Localisation de Grenoble, Isère »), et la
mention des sources accompagne chaque carte.

## Conséquences

- Aucune requête externe côté visiteur, aucune bibliothèque cartographique chargée : le site
  conserve sa note A. Plus aucun appel à Wikidata ni à Wikimedia Commons.
- Poids mesuré sur 1 200 fiches (vrais contours IGN) : **3 Ko** de SVG en médiane pour une
  commune (1,3 Ko compressé), 8 Ko pour un département, 10 Ko pour une région. Le tracé est
  allégé au pixel près (points distants de moins de 0,75 px ignorés, coordonnées relatives).
- Build : 1 209 pages en **7,3 s** ; les fonds de carte ne sont lus qu'une fois par build.
- Toutes les fiches ont une illustration homogène et informative, y compris sans photo libre.
- Le fond des cartes de situation (≈ 250 Ko) est versionné mais n'est jamais envoyé aux
  visiteurs.
- Sur un serveur déjà installé, l'ancienne table `photos` et le dossier `donnees/photos/` ne
  servent plus et peuvent être supprimés (voir le guide de déploiement).
