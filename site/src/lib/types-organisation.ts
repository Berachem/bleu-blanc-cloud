// Direction artistique des types d'organisation : un pictogramme maison et une couleur par
// type (variables CSS --type-<id>, versions claire et sombre dans theme.css). Les couleurs
// évitent le bleu clair, le jaune, l'orange et le rouge vif, réservés aux notes A à E :
// un type ne doit jamais se lire comme une note. La couleur n'est jamais seule : toujours
// accompagnée de l'icône et du libellé (daltonisme, RGAA).

export interface TypeOrganisation {
  id: string;
  /** Libellé au singulier (étiquette d'une fiche, cellule de tableau). */
  libelle: string;
  /** Libellé au pluriel (filtres, titre de l'accueil). */
  pluriel: string;
  /** Accord du pronom dans « Nos … dépendent-ils / -elles ». */
  accord: "ils" | "elles";
  /** Tracés SVG (grille 24 × 24, trait), vide pour un type sans pictogramme. */
  icone: string;
}

const COLONNES = '<path d="M3 9 12 4l9 5M5 9v9M9.5 9v9M14.5 9v9M19 9v9M3 20h18"/>';

export const TYPES_ORGANISATION: Record<string, TypeOrganisation> = {
  commune: { id: "commune", libelle: "Ville", pluriel: "Villes", accord: "elles", icone: COLONNES },
  departement: {
    id: "departement",
    libelle: "Département",
    pluriel: "Départements",
    accord: "ils",
    icone:
      '<path d="m3 6.5 5.5-2 7 2 5.5-2v13l-5.5 2-7-2-5.5 2zM8.5 4.5v13M15.5 6.5v6"/><path d="M15.5 21s3-2.6 3-5a3 3 0 0 0-6 0c0 2.4 3 5 3 5z"/>',
  },
  region: {
    id: "region",
    libelle: "Région",
    pluriel: "Régions",
    accord: "elles",
    icone: '<path d="M12 2.5 20.5 7.5v9L12 21.5 3.5 16.5v-9z"/><path d="M12 2.5V12l8.5 4.5M12 12l-8.5 4.5"/>',
  },
  hopital: {
    id: "hopital",
    libelle: "Hôpital",
    pluriel: "Hôpitaux",
    accord: "ils",
    // Pas de croix rouge (emblème protégé) : croix rose sur un bâtiment, esprit panneau « H »
    icone: '<path d="M5 21V8.5L12 4l7 4.5V21M3 21h18M12 8.5v6M9 11.5h6M10 21v-3.5h4V21"/>',
  },
  universite: {
    id: "universite",
    libelle: "Université",
    pluriel: "Universités",
    accord: "elles",
    icone: '<path d="M2 9l10-5 10 5-10 5zM6 11v5c0 1.5 3 3 6 3s6-1.5 6-3v-5M22 9v6"/>',
  },
  autre: {
    id: "autre",
    libelle: "Autre organisation",
    pluriel: "Autres organisations",
    accord: "elles",
    icone: '<circle cx="12" cy="12" r="8.5"/><path d="M8 12h.01M12 12h.01M16 12h.01"/>',
  },
  sur_demande: {
    id: "sur_demande",
    libelle: "Analyse sur demande",
    pluriel: "Analyses sur demande",
    accord: "elles",
    icone: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/>',
  },
};

/** Ordre d'affichage des types (filtres, tableaux, titre de l'accueil). */
export const ORDRE_TYPES = ["commune", "departement", "region", "hopital", "universite", "autre", "sur_demande"];

export const typeOrganisation = (id: string): TypeOrganisation =>
  TYPES_ORGANISATION[id] ?? { ...TYPES_ORGANISATION.autre, id, libelle: id, pluriel: id };

export const trierTypes = (ids: Iterable<string>): string[] =>
  [...new Set(ids)].sort(
    (a, b) => (ORDRE_TYPES.indexOf(a) + 1 || 99) - (ORDRE_TYPES.indexOf(b) + 1 || 99),
  );

/** SVG du pictogramme (chaîne), décoratif : le libellé est toujours affiché à côté. */
export const svgType = (id: string, epaisseur = 1.8): string => {
  const type = typeOrganisation(id);
  if (!type.icone) return "";
  return `<svg class="icone-type" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${epaisseur}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${type.icone}</svg>`;
};
