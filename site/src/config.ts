// Configuration éditoriale du site.
// ⚠️ Les informations marquées « À COMPLÉTER » doivent être fournies par l'éditeur
// avant la mise en ligne (mentions légales, loi LCEN).

export const SITE = {
  nom: "Bleu Blanc Cloud",
  url: "https://bleublanccloud.berachem.dev",
  description:
    "Observatoire indépendant et open source de la souveraineté numérique des organisations publiques françaises.",
  depot: "https://github.com/Berachem/bleu-blanc-cloud",
  miroir: "https://codeberg.org/berachem/bleu-blanc-cloud",
  auteur: "Berachem Markria",
  siteAuteur: "https://berachem.dev",
  // Adresse de contact pour les demandes de retrait, corrections et droits de réponse.
  contact: "contact@berachem.dev", // À CONFIRMER
  licenceCode: "EUPL-1.2",
} as const;

// « Analyser mon site » : un ticket est ouvert sur Codeberg ; le serveur le lit via l'API
// (aucun port entrant) et y répond. Le modèle de ticket est publié avec le site (branche
// « pages », qui doit être la branche par défaut du dépôt).
export const DEMANDES = {
  forge: "https://codeberg.org",
  depot: "berachem/bleublanccloud-pages",
  modele: ".forgejo/issue_template/analyse.yaml",
  limiteJour: 10,
} as const;

export const MENTIONS_LEGALES = {
  editeur: {
    nom: "Berachem Markria",
    statut: "Particulier, projet personnel non commercial",
    adresse: "À COMPLÉTER (ou recours à l'anonymat prévu par l'article 6-III-2 de la LCEN)",
    contact: SITE.contact,
  },
  directeurPublication: "Berachem Markria",
  hebergeur: {
    nom: "Codeberg e.V.",
    adresse: "Arminiusstraße 2-4, 10551 Berlin, Allemagne (à vérifier)",
    site: "https://codeberg.org",
  },
} as const;

export const NAVIGATION = [
  { href: "/", libelle: "Accueil" },
  { href: "/carte/", libelle: "Carte" },
  { href: "/classements/", libelle: "Classements" },
  { href: "/alternatives/", libelle: "Alternatives" },
  { href: "/methodologie/", libelle: "Méthodologie" },
  { href: "/a-propos/", libelle: "À propos" },
] as const;
