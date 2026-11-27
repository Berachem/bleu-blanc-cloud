# ADR-0006 : universités et hôpitaux publics dans l'observatoire

- **Statut** : acceptée (universités et hôpitaux : mis en œuvre)
- **Date** : 2026-11-27

## Contexte

L'observatoire couvre les collectivités (communes de plus de 10 000 habitants, départements,
régions). La phase 8 prévoit d'autres catégories d'organisations, dont les **hôpitaux** et
les **universités**. Ces établissements gèrent des données sensibles (santé, recherche,
étudiants) et leur dépendance numérique relève, comme celle des collectivités, de l'intérêt
général.

Trois questions se posent : le périmètre (public ou privé), les précautions propres à la
santé, et la qualité de l'attribution (beaucoup de ces établissements sont hébergés par des
réseaux publics que le référentiel ne connaît pas encore).

## Décision

1. **Établissements publics uniquement.** Universités publiques, puis centres hospitaliers
   publics (CHU d'abord). Les écoles et cliniques privées sont exclues : ce sont des
   entreprises, et une note publique pourrait être vue comme du dénigrement commercial.
2. **Même cadre que pour les collectivités** : analyse strictement passive (aucune tentative
   d'accès, aucun formulaire, aucun test de vulnérabilité), règles de politesse du scanner,
   retraits respectés, aucune donnée personnelle, droit de réponse via `/retrait`.
3. **Sources ouvertes et sourcées** :
   - universités : jeu de données « Principaux établissements d'enseignement supérieur »
     du ministère de l'Enseignement supérieur (Licence Ouverte 2.0) ;
   - hôpitaux : liste tenue à la main `referentiels/hopitaux.yaml` des CHU et CHR (une
     trentaine), chaque entrée avec au moins une source (site officiel) et `a_verifier`
     tant qu'elle n'est pas relue. La base FINESS (milliers d'établissements, sans site
     web) reste une piste pour élargir aux autres centres hospitaliers. Premier élargissement
     (lot GHT) : les **établissements supports de GHT**, seulement quand la page GHT de l'ARS
     nomme l'établissement support et qu'une fiche publique (acceslibre, sante.fr ou ARS)
     donne son site web ; le reste est laissé de côté tant qu'il n'est pas vérifiable.
4. **Import en deux temps.** `bbcloud cibles universites` affiche d'abord un **aperçu**
   (rien n'est enregistré) ; `--enregistrer` ajoute les établissements à la base. La
   campagne hebdomadaire analysant toutes les organisations enregistrées, l'import est le
   point de contrôle : aucun établissement n'est analysé sans cette étape volontaire.
5. **Référentiel complété avant les campagnes** : RENATER (réseau national de
   l'enseignement et de la recherche, groupement d'intérêt public) est ajouté aux
   fournisseurs, pour éviter des notes provisoires en masse. Pour les hôpitaux, les
   groupements régionaux (GHT, GIP e-santé) seront identifiés de la même façon.
6. **Précautions propres à la santé** (au moment de l'ajout des hôpitaux) : un
   avertissement sur les fiches rappellera que seuls le site et la messagerie sont visibles
   de l'extérieur, que les systèmes de soins et les données des patients ne sont pas
   analysés, et que la note ne dit rien de la sécurité (« souveraineté ≠ sécurité »).
   Aucune information exploitable par un attaquant n'est publiée.
7. **Nouveau type d'organisation** « universite » (puis « hopital ») : la méthodologie et
   le calcul du score sont inchangés. Les chiffres de l'accueil incluront ces
   établissements après leur première analyse ; la prospection reste limitée aux communes.

## Conséquences

- Les universités apparaissent dans les classements et la recherche, avec leur type.
- Une première campagne limitée (`bbcloud campagne lancer --limite 10`) est conseillée après
  l'import, pour vérifier l'attribution (RENATER, hébergeurs régionaux) avant la campagne
  complète.
- Les hôpitaux (type « hopital ») s'importent avec `bbcloud cibles hopitaux` (aperçu, puis
  `--enregistrer`, migration 007) ; leurs fiches affichent l'avertissement santé du point 6.
