// Configuration éditoriale du site.

// Domaine du site publié, lu au build dans DOMAINE_SITE (transmis par deploy/publier.sh
// depuis le .env du serveur) : URL canoniques, plan du site, robots.txt, partage.
const DOMAINE_PAR_DEFAUT = "bleublanccloud.fr";
const RE_NOM_HOTE = /^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;

function lireDomaine(): string {
  const brut = typeof process !== "undefined" ? process.env.DOMAINE_SITE : undefined;
  const domaine = (brut ?? "").trim().toLowerCase().replace(/\.$/, "") || DOMAINE_PAR_DEFAUT;
  if (!RE_NOM_HOTE.test(domaine)) {
    throw new Error(`DOMAINE_SITE invalide : « ${brut} » (nom de domaine seul attendu)`);
  }
  return domaine;
}

export const DOMAINE_SITE = lireDomaine();

export const SITE = {
  nom: "Bleu Blanc Cloud",
  url: `https://${DOMAINE_SITE}`,
  description:
    "Observatoire indépendant et open source de la souveraineté numérique des organisations publiques françaises.",
  depot: "https://github.com/Berachem/bleu-blanc-cloud",
  miroir: "https://codeberg.org/berachem/bleu-blanc-cloud",
  auteur: "Berachem Markria",
  siteAuteur: "https://berachem.dev",
  // Adresse de contact pour les demandes de retrait, corrections et droits de réponse.
  contact: "contact@berachem.dev",
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
  // Compte Codeberg des demandeurs effacé de la base au-delà de cette durée
  // (CONSERVATION_AUTEUR dans scanner/src/bleublanccloud/demandes/traitement.py)
  conservationCompteJours: 30,
} as const;

// Mentions légales (LCEN, art. 1-1 depuis la loi SREN du 21 mai 2024). L'éditeur publie à
// titre non professionnel : son adresse n'est pas publiée (art. 1-1 II), ses éléments
// d'identification ayant été communiqués à l'hébergeur.
export const MENTIONS_LEGALES = {
  editeur: {
    nom: "Berachem Markria",
    statut: "Particulier, projet personnel non professionnel et non commercial",
    contact: SITE.contact,
  },
  directeurPublication: "Berachem Markria",
  hebergeur: {
    nom: "Codeberg e.V.",
    forme: "Association enregistrée de droit allemand, à but non lucratif",
    registre: "Amtsgericht Charlottenburg, VR 36929 B",
    adresse: "Arminiusstraße 2-4, 10551 Berlin, Allemagne",
    contact: "contact@codeberg.org",
    site: "https://codeberg.org",
    // Codeberg ne publie pas de numéro de téléphone : contact par e-mail uniquement
    mentions: "https://codeberg.org/Codeberg/org/src/branch/main/Imprint.md",
    confidentialite: "https://codeberg.org/Codeberg/org/src/branch/main/PrivacyPolicy.md",
  },
  licenceDonnees: {
    nom: "Licence Ouverte 2.0 (Etalab)",
    url: "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
  },
  // Fond de plan des cartes de situation, chargé uniquement à la demande (ADR-0005)
  fondDePlan: {
    nom: "IGN – Géoplateforme",
    operateur: "Institut national de l'information géographique et forestière (IGN), établissement public français",
    site: "https://geoservices.ign.fr/",
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
