# ADR-0003 : photos des communes auto-hébergées depuis Wikimedia Commons

- **Statut** : acceptée
- **Date** : 2026-09-29

## Contexte

Les fiches des communes gagnent à montrer une photo du lieu. L'API Unsplash a été envisagée,
mais ses conditions imposent de charger les images directement depuis ses serveurs
(`images.unsplash.com`, « hotlinking » obligatoire, pour comptabiliser les vues). Chaque fiche
ferait alors une requête vers un service américain qui suit l'affichage, ce qui contredit trois
règles du projet : aucune ressource externe, zéro dépendance américaine dans le produit publié,
et la note A du site sur son propre scan. La recherche par nom de ville donne en outre des
résultats souvent hors sujet (homonymes).

## Décision

- La photo est l'**image principale Wikidata** (P18) de l'entité, trouvée par son **code
  officiel** (code INSEE de la commune P374, du département P2586 ou de la région P2585), les
  communes dissoutes étant exclues.
- Les métadonnées viennent de **Wikimedia Commons** ; seules les **licences libres** (CC0,
  domaine public, CC BY, CC BY-SA) sont acceptées.
- Le **serveur** télécharge une vignette (1 280 px, hôte `upload.wikimedia.org` uniquement,
  taille bornée) lors de la campagne (`bbcloud photos maj`), la met en cache dans
  `donnees/photos/` et la revérifie tous les 30 jours.
- L'export la copie à côté des données du site : le visiteur la reçoit **du site lui-même**,
  avec l'auteur et la licence affichés sous la photo. Sans photo, une illustration maison est
  affichée.

## Conséquences

- Aucune requête externe côté visiteur ; le site conserve sa note A.
- Le crédit de l'auteur et la licence sont obligatoires et toujours affichés.
- Le dépôt de publication grossit d'environ 100 à 300 Ko par photo (fichiers inchangés d'une
  publication à l'autre : pas de croissance de l'historique git tant que la photo ne change pas).
- Les fiches « sur demande » n'ont pas de photo (pas de code officiel).
