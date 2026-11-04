# Modèle de message : proposer le badge « Note A » à une collectivité

À envoyer par l'auteur, à l'adresse de contact publique de la collectivité (service
communication ou service numérique). Les adresses de l'annuaire ne sont ni stockées dans la
base ni publiées par Bleu Blanc Cloud : la liste d'envoi est un classeur privé, généré à la
main sur le serveur (`uv run --with openpyxl bbcloud prospection badge`, voir
`deploy/README.md`), à supprimer une fois la campagne terminée.

---

**Objet** : 🏅 [Commune] obtient la note A en souveraineté numérique

Bonjour,

Je m'appelle Berachem Markria et je développe **Bleu Blanc Cloud** (https://bleublanccloud.fr),
un observatoire indépendant et open source. Il mesure, commune par commune, si les services
numériques visibles publiquement (hébergement du site, messagerie, DNS, services tiers) reposent
sur des fournisseurs européens ou sur des acteurs soumis à des lois étrangères comme le Cloud Act
américain.

🎉 J'ai le plaisir de vous annoncer que **[Commune] obtient la note A** (score de [score]/100) !
Sur les [nombre_analysees] collectivités analysées en France, seules **[nombre_A] atteignent ce
niveau** : [Commune] fait partie de ces collectivités exemplaires qui ont fait le choix d'un
numérique européen. Bravo à vos équipes ! 👏

Le détail est sur votre fiche : https://bleublanccloud.fr/organisation/[slug]/

Si vous souhaitez le faire savoir, un **badge** est à votre disposition sur cette page, en version
claire ou sombre : il suffit de copier un petit code dans votre site, ou de télécharger l'image.
Il ne contient ni cookie ni traceur, bien sûr.

Deux précisions, par transparence :
- Bleu Blanc Cloud est un projet personnel, sans lien avec l'État ni avec un fournisseur.
- La note ne porte que sur ce qui est visible de l'extérieur : elle ne juge ni vos outils internes
  ni la sécurité de vos sites.

Une question ou une correction ? Il suffit de répondre à ce mail. Et si vous préférez ne plus
recevoir de message de ma part, dites-le-moi simplement.

Belle journée,

Berachem Markria
Bleu Blanc Cloud · https://bleublanccloud.fr

---

Envoi programmé : `bbcloud prospection envoyer` (modèles dans
`scanner/src/bleublanccloud/courriels/`, relance unique incluse ; voir `deploy/README.md`).

Version HTML : logo `https://bleublanccloud.fr/courriel/logo-bleu-blanc-cloud.png` (PNG, car
Gmail et Outlook n'affichent pas le SVG ; image statique du site, sans paramètre de suivi).
Champs à remplacer depuis le classeur : [Commune] (colonne Commune), [score] (Score), [slug] (Slug).
[nombre_A] et [nombre_analysees] : chiffres du jour de l'envoi (page /classements/ ou
`bbcloud stats`), notes provisoires comprises, pour rester cohérent avec le site. Au
4 novembre 2026 : 486 notées A sur 1 162 collectivités analysées.
