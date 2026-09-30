# Politique de sécurité

## Signaler une vulnérabilité

Merci de **ne pas ouvrir de ticket public** pour une vulnérabilité. Deux canaux privés sont possibles :

1. le formulaire de signalement privé de GitHub : onglet *Security* du dépôt, puis *Report a vulnerability* ;
2. un e-mail à **contact@berachem.dev**, avec « Sécurité » dans l'objet.

Indiquer autant que possible : la partie concernée (scanner, site, scripts de déploiement), la version (commit ou version du site affichée en pied de page), les étapes pour reproduire le problème et son impact estimé.

## Engagements

- Accusé de réception sous 7 jours.
- Évaluation et, le cas échéant, plan de correction communiqués sous 30 jours.
- Publication d'un correctif, puis d'une note décrivant le problème une fois corrigé, en citant l'auteur du signalement s'il le souhaite.

Le projet est maintenu bénévolement : aucune récompense financière n'est proposée.

## Périmètre

Dans le périmètre :

- le scanner `bbcloud` (`scanner/`) : par exemple, contournement de la garde réseau permettant d'atteindre une adresse privée ou locale, traitement dangereux du contenu d'un ticket ou d'une page analysée, fuite d'un secret dans les journaux ;
- le site statique (`site/`) : injection de contenu, ressource externe ou traceur involontaire ;
- les scripts de déploiement (`deploy/`) : droits excessifs, exposition de secrets.

Hors périmètre :

- l'infrastructure de Codeberg (Codeberg Pages, forge), à signaler directement à Codeberg e.V. ;
- les sites des organisations analysées : Bleu Blanc Cloud ne réalise aucun test de vulnérabilité et ne relaie pas ce type de signalement ;
- les constats d'un score (fournisseur mal attribué, fiche erronée), qui relèvent d'une correction : [bleublanccloud.fr/retrait](https://bleublanccloud.fr/retrait/) ou ticket public.

## Règles pour les recherches

- Ne pas mener de test intrusif, de déni de service ou de scan automatisé contre `bleublanccloud.fr` ; le site est statique et son code est public : les recherches peuvent se faire sur une instance locale.
- Ne pas accéder à des données qui ne vous appartiennent pas et ne pas les conserver.
- Laisser un délai raisonnable de correction avant toute divulgation publique.

## Versions prises en charge

Seule la dernière version de la branche `main` est maintenue ; le site publié est reconstruit à partir de cette branche.
