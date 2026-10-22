// Textes et chiffres affichés par le simulateur, partagés entre le build (pages des
// préréglages) et le navigateur (simulateur libre) : une seule formulation. Français simple,
// nombres au format français (« 1 162 », « 27,1 % »).
import type { Agregat, Impact } from "./simulation.ts";

export function nombre(valeur: number): string {
  return valeur.toLocaleString("fr-FR");
}

/** Part en pourcentage avec une décimale (« 27,1 % »), « — » si le total est nul. */
export function part(valeur: number, total: number): string {
  if (!total) return "—";
  return `${((100 * valeur) / total).toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`;
}

export function pluriel(valeur: number, singulier: string, plurielTexte: string): string {
  return `${nombre(valeur)} ${valeur > 1 ? plurielTexte : singulier}`;
}

/** Valeurs textuelles des champs `data-champ` des résultats. */
export function champsResultats(agregat: Agregat): Record<string, string> {
  const territoires: string[] = [];
  if (agregat.departements_touches) {
    territoires.push(pluriel(agregat.departements_touches, "département", "départements"));
  }
  if (agregat.regions_touchees) {
    territoires.push(pluriel(agregat.regions_touchees, "région", "régions"));
  }
  return {
    touchees: nombre(agregat.touchees),
    total: nombre(agregat.total),
    part_touchees: part(agregat.touchees, agregat.total),
    libelle_touchees: agregat.touchees > 1 ? "collectivités touchées" : "collectivité touchée",
    habitants_touches: nombre(agregat.habitants_touches),
    part_habitants: part(agregat.habitants_touches, agregat.habitants_total),
    dont_territoires: territoires.length
      ? `Les départements et régions sont comptés à part : ${territoires.join(" et ")} touché${agregat.departements_touches + agregat.regions_touchees > 1 ? "s" : ""}.`
      : "Aucun département ni aucune région touché.",
    sites_hors_ligne: nombre(agregat.sites_hors_ligne),
    messageries_coupees: nombre(agregat.messageries_coupees),
    sites_degrades: nombre(agregat.sites_degrades),
    injoignables: nombre(agregat.injoignables),
    dns_resilients: nombre(agregat.dns_resilients),
    indeterminees: nombre(agregat.par_statut.indetermine),
  };
}

/** Texte prêt à partager. */
export function phrasePartage(titre: string, agregat: Agregat, url: string): string {
  const touchees = agregat.touchees > 1 ? "collectivités seraient touchées" : "collectivité serait touchée";
  const sites =
    agregat.sites_hors_ligne > 0
      ? `, dont ${pluriel(agregat.sites_hors_ligne, "site hors ligne", "sites hors ligne")}`
      : "";
  return `${titre} Selon la simulation de Bleu Blanc Cloud, ${nombre(agregat.touchees)} ${touchees} sur ${nombre(agregat.total)}${sites}. Et la vôtre ? ${url}`;
}

/** Réponse de « Ma commune serait-elle touchée ? » pour une seule collectivité. */
export function descriptionImpact(impact: Impact): { titre: string; details: string[] } {
  const titres: Record<Impact["statut"], string> = {
    injoignable: "Touchée : site et messagerie injoignables",
    hors_service: "Touchée : au moins un service coupé",
    degrade: "Touchée : services dégradés",
    indetermine: "Impossible de conclure",
    non_touchee: "Non touchée dans ce scénario",
  };
  const details: string[] = [];
  const dns: Record<Impact["dns"], string> = {
    coupe: "DNS : tous les serveurs tombent, le nom de domaine ne répond plus (effet domino sur le site et la messagerie).",
    resilient: "DNS : résilient, les serveurs sont répartis chez plusieurs opérateurs.",
    ok: "DNS : non touché.",
    inconnu: "DNS : non évalué.",
  };
  const site: Record<Impact["site"], string> = {
    injoignable: "Site : injoignable (DNS).",
    hors_ligne: "Site : hors ligne.",
    degrade: "Site : dégradé (une partie de l'hébergement ou des services tiers ne répond plus).",
    ok: "Site : non touché.",
    inconnu: "Site : hébergeur non identifié, non évalué.",
  };
  const messagerie: Record<Impact["messagerie"], string> = {
    coupee: "Messagerie : coupée. Les serveurs expéditeurs réessaient en général pendant quelques jours, mais l'accès aux boîtes et les envois sont coupés.",
    degradee: "Messagerie : dégradée (une partie des serveurs ne répond plus).",
    ok: "Messagerie : non touchée.",
    sans_objet: "Messagerie : aucune messagerie détectée sur ce domaine.",
    inconnu: "Messagerie : non évaluée.",
  };
  details.push(dns[impact.dns], site[impact.site], messagerie[impact.messagerie]);
  return { titre: titres[impact.statut], details };
}

/** Titre d'un scénario du simulateur libre. */
export function titreScenario(scenario: "panne" | "cloud_act", nomFournisseur?: string): string {
  if (scenario === "cloud_act") return "Et si les acteurs soumis au Cloud Act coupaient l'accès ?";
  // « Microsoft (Azure, Microsoft 365) » → « Microsoft »
  const nom = nomFournisseur?.split(" (")[0] ?? "ce fournisseur";
  return `Et si ${nom} tombait ?`;
}
