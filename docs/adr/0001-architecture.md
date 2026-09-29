# ADR-0001 — Architecture générale

- **Statut** : accepté
- **Date** : 2026-09-29

## Contexte

Bleu Blanc Cloud mesure la dépendance numérique des organisations publiques françaises vis-à-vis de fournisseurs extra-européens. Le projet est personnel, bénévole et open source. Il doit :

- analyser des milliers de domaines de façon **passive** et **polie** ;
- publier des résultats **vérifiables** (chaque point retiré est justifié par une preuve) ;
- être lui-même **cohérent avec son sujet** : aucune dépendance américaine dans le produit publié ;
- coûter presque rien à héberger, sans exposer de serveur depuis le domicile de l'auteur.

## Décision

1. **Deux briques séparées dans un même dépôt** :
   - `scanner/` : un outil Python 3.12 (CLI `bbcloud`) qui importe les cibles, lance les sondes (DNS, IP/ASN, HTTP, TLS, RDAP), attribue chaque preuve à un fournisseur, calcule le score, génère les rapports IA (Mistral) et exporte des fichiers JSON ;
   - `site/` : un site **100 % statique** (Astro) construit à partir de ces JSON.
2. **Contrat de données explicite** : les modèles pydantic (`modeles.py`) sont la source de vérité. Ils sont exportés en schémas JSON puis convertis en types TypeScript pour le site.
3. **Stockage SQLite** avec migrations SQL numérotées : un seul fichier, facile à sauvegarder (`sqlite3 .backup`), largement suffisant pour quelques milliers d'organisations et l'historique des scans.
4. **Référentiels YAML versionnés** (fournisseurs, règles de détection, alternatives, retraits) : lisibles, relus en revue de code, chaque fait est sourcé.
5. **Exécution planifiée sur un conteneur LXC Debian 12** (Proxmox, domicile) via un timer systemd hebdomadaire. Seuls les fichiers générés sont publiés, par `git push`, sur **Codeberg Pages** (Allemagne).
6. **Analyse strictement passive** : aucune soumission de formulaire, aucune authentification, aucun test de vulnérabilité. Politesse imposée par le code (User-Agent explicite, 1 requête/s/domaine, 5 pages max, `robots.txt`, liste de retraits vérifiée avant toute requête).
7. **L'IA ne calcule jamais le score** : elle reformule des constats déjà calculés et propose un plan de migration limité aux alternatives du référentiel.

## Conséquences

- **+** Aucun serveur exposé, surface d'attaque minimale, hébergement gratuit.
- **+** Les résultats sont reproductibles : même méthodologie, mêmes référentiels, mêmes constats.
- **+** Le site peut être construit sans le scanner (données de démonstration fictives).
- **−** Pas de scan à la demande en v1 (prévu en phase 8, optionnelle).
- **−** La fraîcheur des données dépend de la fréquence des campagnes (hebdomadaire).
- **−** Seule l'empreinte **externe et visible publiquement** est mesurable ; les outils internes des organisations échappent à l'analyse. Cette limite est affichée partout.
