# Données ouvertes (data.gouv.fr)

Les résultats de l'observatoire sont publiés à chaque campagne en **CSV**, sous
**Licence Ouverte 2.0** (Etalab), en plus des fichiers JSON utilisés par le site.
Seules les collectivités de l'observatoire sont incluses (communes de plus de 10 000
habitants, départements, régions) : les analyses sur demande en sont exclues.

| Fichier | Adresse (mise à jour à chaque publication) |
|---|---|
| Collectivités | https://bleublanccloud.fr/donnees/organisations.csv |
| Départements | https://bleublanccloud.fr/donnees/departements.csv |
| Carte des départements (PNG 1080 × 1080) | https://bleublanccloud.fr/donnees/carte-departements.png |
| Détail complet (constats, preuves) | https://bleublanccloud.fr/donnees/organisations/<slug>.json |

Format : UTF-8, séparateur virgule, une ligne d'en-tête ; listes séparées par « | » ; dates
en ISO 8601 (UTC) ; cellule vide = valeur inconnue ou non évaluable. Aucune donnée
personnelle : ni e-mail, ni téléphone, ni nom de personne.

Les colonnes sont définies dans `scanner/src/bleublanccloud/export/donnees_ouvertes.py`
(un test vérifie que ce document les décrit toutes).

## `organisations.csv`

| Colonne | Description |
|---|---|
| `slug` | Identifiant de la fiche sur le site (stable d'une campagne à l'autre). |
| `nom` | Nom de la collectivité. |
| `type` | commune, departement ou region. |
| `code_insee` | Code officiel géographique de la commune (vide pour les autres types). |
| `code_departement` | Code du département. |
| `departement` | Nom du département. |
| `code_region` | Code de la région. |
| `region` | Nom de la région. |
| `population` | Population municipale (geo.api.gouv.fr), vide si inconnue. |
| `domaine` | Nom de domaine analysé (site web officiel). |
| `score` | Score global de 0 à 100 (100 : uniquement des fournisseurs européens). |
| `note` | Note de A à E (A ≥ 85, B ≥ 70, C ≥ 50, D ≥ 30, E < 30). |
| `note_provisoire` | true si plus de 30 % du poids applicable n'a pas pu être évalué (fournisseurs non identifiés) : note à interpréter avec prudence. |
| `couverture` | Part du poids applicable effectivement évaluée, en %. |
| `score_hebergement` | Score de la catégorie « hebergement » sur 100 (vide si non évaluable). |
| `score_messagerie` | Score de la catégorie « messagerie » sur 100 (vide si non évaluable). |
| `score_dns` | Score de la catégorie « dns » sur 100 (vide si non évaluable). |
| `score_suites_saas` | Score de la catégorie « suites_saas » sur 100 (vide si non évaluable). |
| `score_services_tiers` | Score de la catégorie « services_tiers » sur 100 (vide si non évaluable). |
| `score_mesure_audience` | Score de la catégorie « mesure_audience » sur 100 (vide si non évaluable). |
| `fournisseurs_hebergement` | Fournisseur(s) identifié(s) pour la catégorie « hebergement », séparés par « | ». |
| `fournisseurs_messagerie` | Fournisseur(s) identifié(s) pour la catégorie « messagerie », séparés par « | ». |
| `fournisseurs_dns` | Fournisseur(s) identifié(s) pour la catégorie « dns », séparés par « | ». |
| `services_hors_ue` | Suites collaboratives, services tiers et mesure d'audience de fournisseurs soumis au Cloud Act ou à une loi équivalente (niveau D), séparés par « | ». |
| `date_analyse` | Date et heure de l'analyse (UTC, ISO 8601). |
| `version_methodologie` | Version de la méthodologie de calcul. |
| `url_fiche` | Page détaillée sur le site, avec les constats et leurs preuves. |

## `departements.csv`

| Colonne | Description |
|---|---|
| `code` | Code du département. |
| `nom` | Nom du département. |
| `code_region` | Code de la région. |
| `nombre_organisations` | Nombre de collectivités analysées dans le département. |
| `score_moyen` | Score moyen de ces collectivités (0 à 100). |
| `note_moyenne` | Note correspondant au score moyen. |
| `nombre_note_A` | Nombre de collectivités notées A. |
| `nombre_note_B` | Nombre de collectivités notées B. |
| `nombre_note_C` | Nombre de collectivités notées C. |
| `nombre_note_D` | Nombre de collectivités notées D. |
| `nombre_note_E` | Nombre de collectivités notées E. |

## Limites

- Le score ne reflète que l'empreinte **externe et visible publiquement** (site web, DNS,
  messagerie), pas les outils internes. Il est **indicatif**.
- Un fournisseur non identifié est exclu du calcul ; au-delà de 30 % du poids non évalué,
  la note est marquée **provisoire** (`note_provisoire`).
- Méthodologie complète et historique des versions : https://bleublanccloud.fr/methodologie/

---

## Fiche data.gouv.fr (textes à copier-coller)

### Organisation

| Champ | Valeur |
|---|---|
| Nom | Bleu Blanc Cloud |
| Sigle | *(laisser vide)* |
| Description | voir ci-dessous |
| Site internet | https://bleublanccloud.fr |
| Logo | logo carré PNG (nuage tricolore) |
| SIRET | *(laisser vide : projet personnel, non commercial, sans structure juridique)* |

Description de l'organisation :

> Bleu Blanc Cloud est un observatoire **indépendant et open source** de la souveraineté
> numérique des collectivités françaises. Projet personnel et non commercial de Berachem
> Markria, **sans lien avec l'État, une administration ou l'Union européenne**, et sans
> financement de fournisseurs. Code source (EUPL-1.2) : https://github.com/Berachem/bleu-blanc-cloud

### Jeu de données

| Champ | Valeur |
|---|---|
| Titre | Souveraineté numérique des collectivités françaises (Bleu Blanc Cloud) |
| Sigle | *(laisser vide)* |
| Producteur | l'organisation Bleu Blanc Cloud |
| Description courte | Dépendance des communes de plus de 10 000 habitants, départements et régions aux fournisseurs numériques extra-européens : score de 0 à 100 et note de A à E, mis à jour chaque semaine. |
| Licence | Licence Ouverte / Open Licence version 2.0 |
| Fréquence de mise à jour | Hebdomadaire |
| Couverture spatiale | France |
| Granularité spatiale | Commune |
| Couverture temporelle | de la date de la première campagne publiée à aujourd'hui (laisser la fin ouverte si possible) |
| Mots-clés | souveraineté numérique, cloud, cloud act, collectivités territoriales, communes, hébergement, messagerie, dns, rgpd, open source |

Description du jeu de données :

> Pour chaque collectivité (communes de plus de 10 000 habitants, départements, régions),
> Bleu Blanc Cloud analyse **de façon passive** l'empreinte numérique visible publiquement
> depuis son nom de domaine : hébergement du site, messagerie, DNS, suites collaboratives,
> services tiers chargés par le site et mesure d'audience. Chaque fournisseur est rattaché
> à une juridiction (Union européenne, hors UE, soumis au Cloud Act américain…).
>
> Le jeu de données donne, par collectivité, un **score de 0 à 100** et une **note de A à
> E** (A : fournisseurs européens), le détail par catégorie et les fournisseurs identifiés.
> La méthodologie est publique et versionnée : https://bleublanccloud.fr/methodologie/ ;
> chaque point retiré est justifié par une preuve sur la fiche de la collectivité.
>
> **Limites** : le score ne reflète que l'empreinte externe et visible publiquement, pas
> les outils internes ; il est indicatif. Les notes « provisoires » (plus de 30 % du poids
> non évalué) sont à interpréter avec prudence.
>
> **Indépendance** : projet personnel, open source et non commercial, **sans lien avec
> l'État ni avec l'Union européenne**. Sa publication sur data.gouv.fr ne vaut pas
> validation par l'administration.
>
> Correction, droit de réponse ou retrait : https://bleublanccloud.fr/retrait/

### Ressources (type « Lien vers un fichier distant », pour une mise à jour automatique)

| Titre | Adresse | Format | Type | Description |
|---|---|---|---|---|
| Collectivités (dernière campagne) | https://bleublanccloud.fr/donnees/organisations.csv | csv | Fichier principal | Une ligne par collectivité : score, note, détail par catégorie, fournisseurs identifiés. Colonnes décrites dans la documentation. |
| Moyennes par département | https://bleublanccloud.fr/donnees/departements.csv | csv | Fichier principal | Score moyen, note moyenne et répartition des notes par département. |
| Description des colonnes | https://github.com/Berachem/bleu-blanc-cloud/blob/main/docs/donnees-ouvertes.md | html | Documentation | Signification de chaque colonne, format et limites. |
| Carte des départements | https://bleublanccloud.fr/donnees/carte-departements.png | png | Autre | Carte de France de la note moyenne par département (part des notes provisoires indiquée), régénérée à chaque campagne hebdomadaire, prête à réutiliser dans un article ou une présentation. |
| Méthodologie | https://bleublanccloud.fr/methodologie/ | html | Documentation | Calcul du score, niveaux de juridiction, pondération, historique des versions. |
