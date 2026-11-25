# Modèle de message : proposer le badge « Note A » à une collectivité

À envoyer par l'auteur, à l'adresse de contact publique de la collectivité (service
communication ou service numérique). Les adresses de l'annuaire ne sont ni stockées dans la
base ni publiées par Bleu Blanc Cloud : la liste d'envoi est un classeur privé, généré à la
main sur le serveur (`uv run --with openpyxl bbcloud prospection badge`, voir
`deploy/README.md`), à supprimer une fois la campagne terminée.

---

**Objet** : [Commune] obtient la note A en souveraineté numérique

Bonjour,

Je m'appelle Berachem Markria et je développe Bleu Blanc Cloud, un observatoire indépendant et
open source qui mesure si les services numériques visibles des collectivités (site, messagerie,
DNS, services tiers) reposent sur des fournisseurs européens.

Bonne nouvelle : [Commune] obtient la note A, avec un score de [score]/100. Bravo à vos équipes
pour ce choix d'un numérique européen.

Le détail est sur votre fiche : https://bleublanccloud.fr/organisation/[slug]/

[Demande : voir ci-dessous]

Bleu Blanc Cloud est un projet personnel, sans lien avec l'État ni avec un fournisseur, et la note
ne porte que sur ce qui est visible de l'extérieur. Si vous préférez ne plus recevoir de message
de ma part, dites-le-moi simplement.

Belle journée,
Berachem Markria
Bleu Blanc Cloud · bleublanccloud.fr

---

**Demande**, selon le destinataire :
- adresse générique de la mairie : « Pourriez-vous transmettre ce message à la personne en charge
  du numérique ou de la communication ? Je peux lui envoyer le badge « Note A » à afficher sur
  votre site (une simple image, sans cookie ni traceur). »
- contact nominatif (DSI, élu au numérique, communication) : « Si cela vous intéresse, je peux
  vous envoyer le badge « Note A » à afficher sur votre site (une simple image, sans cookie ni
  traceur) : un « oui » en réponse suffit. »

Pourquoi ce format : les adresses génériques des mairies alimentent des outils de suivi des
demandes des habitants. Un objet avec emoji et une mise en page HTML font classer le message en
« lettre d'information », qui n'est presque jamais lue. Le mail part donc en **texte simple**,
sans emoji, image ni lien de suivi, avec une seule demande claire.

---

Envoi programmé : `bbcloud prospection envoyer` (modèles dans
`scanner/src/bleublanccloud/courriels/`, voir `deploy/README.md`). Le mail part en priorité au
**contact nominatif** saisi à la main dans le classeur (colonne « Contact nominatif »), sinon à
l'adresse générique de la mairie ; l'adresse effectivement utilisée est notée (colonne « Adresse
utilisée »). La relance unique, 14 jours après, n'est envoyée qu'aux contacts nominatifs : relancer
l'accueil d'une mairie ne ferait qu'ouvrir un nouveau dossier.
Une commune passée en A depuis moins de 90 jours (historique des scores) reçoit à la place le
mail de félicitations (`felicitations.txt`) : « Bravo : [Commune] vient d'obtenir la note A…
Lors de notre analyse du [date], elle était notée [note]. »
Champs à remplacer depuis le classeur : [Commune] (colonne Commune), [score] (Score), [slug] (Slug).
