// Moteur du simulateur « Et si… ? » : règles d'impact d'une panne (ou coupure) d'un ensemble
// de fournisseurs sur chaque collectivité, et totaux agrégés (jamais de liste nominative).
// Utilisé au build (pages des préréglages) et dans le navigateur (simulateur libre).
//
// Mêmes règles que scanner/src/bleublanccloud/simulation.py (images de partage) : les deux
// versions sont vérifiées par les mêmes cas (scanner/tests/fixtures/simulation/cas.json).
// Données : simulations.json (dépendances déjà publiques sur les fiches, aucune faille).

export type StatutCategorie = "evalue" | "inconnu" | "indisponible" | "sans_objet";
export type CleCategorie = "hebergement" | "dns" | "messagerie" | "services_tiers" | "audience";
export type StatutFinal = "injoignable" | "hors_service" | "degrade" | "indetermine" | "non_touchee";

export interface LigneSimulation {
  id: string;
  nom: string;
  type: string;
  region: string | null;
  departement: string | null;
  population: number | null;
  tranche_population: string | null;
  fournisseurs: Record<CleCategorie | "cdn", string[]>;
  statuts: Record<CleCategorie, StatutCategorie>;
}

export interface FournisseurSimulation {
  id: string;
  nom: string;
  pays: string;
  niveau: string;
  soumis_cloud_act: boolean;
  statut_referentiel: "verifie" | "a_verifier";
  nombre_collectivites: number;
}

export interface ExportSimulations {
  meta: {
    date_donnees: string | null;
    version_methodo: string;
    nombre_collectivites: number;
    part_criteres_non_evalues: number;
    regions: Record<string, string>;
    tranches_population: Record<string, string>;
  };
  fournisseurs: Record<string, FournisseurSimulation>;
  collectivites: LigneSimulation[];
}

export interface Impact {
  statut: StatutFinal;
  dns: "coupe" | "resilient" | "ok" | "inconnu";
  site: "injoignable" | "hors_ligne" | "degrade" | "ok" | "inconnu";
  messagerie: "coupee" | "degradee" | "ok" | "sans_objet" | "inconnu";
}

export interface Groupe {
  total: number;
  touchees: number;
}

export interface Agregat {
  total: number;
  touchees: number;
  sites_hors_ligne: number;
  messageries_coupees: number;
  sites_degrades: number;
  injoignables: number;
  dns_resilients: number;
  habitants_touches: number;
  habitants_total: number;
  departements_touches: number;
  regions_touchees: number;
  par_statut: Record<StatutFinal, number>;
  par_region: Record<string, Groupe>;
  par_tranche: Record<string, Groupe>;
}

export type Scenario = "panne" | "cloud_act";

const STATUTS_TOUCHES: StatutFinal[] = ["injoignable", "hors_service", "degrade"];
export const estTouchee = (statut: StatutFinal): boolean => STATUTS_TOUCHES.includes(statut);

/** « coupe » si tous les fournisseurs de la liste sont tombés, « partiel » si une partie. Un
 * serveur non identifié (« ? ») n'est jamais considéré comme tombé. */
function etat(liste: string[], tombes: Set<string>): "coupe" | "partiel" | "ok" {
  const touches = liste.filter((f) => tombes.has(f)).length;
  if (touches > 0 && touches === liste.length) return "coupe";
  return touches > 0 ? "partiel" : "ok";
}

/** Impact sur une collectivité quand les fournisseurs `tombes` ne répondent plus. */
export function evaluer(ligne: LigneSimulation, tombes: Set<string>): Impact {
  const { fournisseurs, statuts } = ligne;

  let dns: Impact["dns"] = "inconnu";
  if (statuts.dns === "evalue") {
    dns = ({ coupe: "coupe", partiel: "resilient", ok: "ok" } as const)[etat(fournisseurs.dns, tombes)];
  }

  let site: Impact["site"];
  if (dns === "coupe") site = "injoignable";
  else if (fournisseurs.cdn.some((f) => tombes.has(f))) site = "hors_ligne";
  else if (statuts.hebergement === "evalue") {
    site = ({ coupe: "hors_ligne", partiel: "degrade", ok: "ok" } as const)[
      etat(fournisseurs.hebergement, tombes)
    ];
  } else site = "inconnu";
  const tiers = (["services_tiers", "audience"] as const).flatMap((cle) =>
    statuts[cle] === "evalue" ? fournisseurs[cle] : [],
  );
  if ((site === "ok" || site === "inconnu") && tiers.some((f) => tombes.has(f))) site = "degrade";

  let messagerie: Impact["messagerie"];
  if (statuts.messagerie === "sans_objet") messagerie = "sans_objet";
  else if (dns === "coupe") messagerie = "coupee";
  else if (statuts.messagerie === "evalue") {
    messagerie = ({ coupe: "coupee", partiel: "degradee", ok: "ok" } as const)[
      etat(fournisseurs.messagerie, tombes)
    ];
  } else messagerie = "inconnu";

  let statut: StatutFinal;
  if (dns === "coupe") statut = "injoignable";
  else if (site === "hors_ligne" || messagerie === "coupee") statut = "hors_service";
  else if (site === "degrade" || messagerie === "degradee") statut = "degrade";
  else if (dns === "inconnu" || site === "inconnu" || messagerie === "inconnu") statut = "indetermine";
  else statut = "non_touchee";
  return { statut, dns, site, messagerie };
}

/** Fournisseurs hors service : « panne » d'un fournisseur, ou « cloud_act » (tous les
 * fournisseurs soumis au Cloud Act). */
export function fournisseursTombes(
  donnees: Pick<ExportSimulations, "fournisseurs">,
  scenario: Scenario,
  fournisseur?: string | null,
): Set<string> {
  if (scenario === "cloud_act") {
    return new Set(
      Object.values(donnees.fournisseurs)
        .filter((f) => f.soumis_cloud_act)
        .map((f) => f.id),
    );
  }
  return new Set(fournisseur ? [fournisseur] : []);
}

/** Totaux d'une simulation. Habitants : communes seulement (départements et régions sont
 * comptés à part, pour éviter les doubles comptes). */
export function agreger(lignes: LigneSimulation[], tombes: Set<string>): Agregat {
  const resultat: Agregat = {
    total: lignes.length,
    touchees: 0,
    sites_hors_ligne: 0,
    messageries_coupees: 0,
    sites_degrades: 0,
    injoignables: 0,
    dns_resilients: 0,
    habitants_touches: 0,
    habitants_total: 0,
    departements_touches: 0,
    regions_touchees: 0,
    par_statut: { injoignable: 0, hors_service: 0, degrade: 0, indetermine: 0, non_touchee: 0 },
    par_region: {},
    par_tranche: {},
  };
  for (const ligne of lignes) {
    const impact = evaluer(ligne, tombes);
    const touchee = estTouchee(impact.statut);
    const n = touchee ? 1 : 0;
    resultat.par_statut[impact.statut] += 1;
    resultat.touchees += n;
    if (impact.site === "injoignable" || impact.site === "hors_ligne") resultat.sites_hors_ligne += 1;
    if (impact.messagerie === "coupee") resultat.messageries_coupees += 1;
    if (impact.site === "degrade") resultat.sites_degrades += 1;
    if (impact.statut === "injoignable") resultat.injoignables += 1;
    if (impact.dns === "resilient") resultat.dns_resilients += 1;
    if (ligne.type === "commune" && ligne.population) {
      resultat.habitants_total += ligne.population;
      if (touchee) resultat.habitants_touches += ligne.population;
    }
    if (touchee && ligne.type === "departement") resultat.departements_touches += 1;
    if (touchee && ligne.type === "region") resultat.regions_touchees += 1;
    for (const [cle, code] of [
      ["par_region", ligne.region],
      ["par_tranche", ligne.tranche_population],
    ] as const) {
      if (!code) continue;
      const groupe = (resultat[cle][code] ??= { total: 0, touchees: 0 });
      groupe.total += 1;
      groupe.touchees += n;
    }
  }
  return resultat;
}

/** Fournisseurs proposés dans le simulateur : vérifiés dans le référentiel, triés par nombre
 * de collectivités dépendantes. */
export function fournisseursProposes(donnees: Pick<ExportSimulations, "fournisseurs">): FournisseurSimulation[] {
  return Object.values(donnees.fournisseurs)
    .filter((f) => f.statut_referentiel === "verifie")
    .sort((a, b) => b.nombre_collectivites - a.nombre_collectivites || a.nom.localeCompare(b.nom, "fr"));
}

/** Fournisseur principal d'une collectivité (lien « Et si… ? » de sa fiche) : hébergeur,
 * sinon DNS, sinon messagerie, parmi les fournisseurs proposés. */
export function fournisseurPrincipal(ligne: LigneSimulation, proposes: Set<string>): string | null {
  for (const cle of ["hebergement", "cdn", "dns", "messagerie"] as const) {
    const trouve = ligne.fournisseurs[cle].find((f) => proposes.has(f));
    if (trouve) return trouve;
  }
  return null;
}
