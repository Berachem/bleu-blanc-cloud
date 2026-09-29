// Libellés et mise en forme (français).
import type { Categorie } from "./types";

export const LIBELLES_CATEGORIES: Record<Categorie | "informatif", string> = {
  hebergement: "Hébergement du site",
  messagerie: "Messagerie",
  dns: "DNS",
  suites_saas: "Suites collaboratives et SaaS",
  services_tiers: "Services tiers chargés par le site",
  mesure_audience: "Mesure d'audience et cookies",
  informatif: "Informations complémentaires",
};

export const DESCRIPTIONS_NIVEAUX: Record<string, string> = {
  A: "Fournisseur européen (siège et maison mère dans l'UE)",
  B: "Fournisseur hors UE, non soumis au Cloud Act",
  C: "CDN extra-européen masquant l'hébergeur réel",
  D: "Fournisseur soumis au Cloud Act ou à une loi équivalente",
  inconnu: "Fournisseur non identifié",
};

export const LIBELLES_TYPES: Record<string, string> = {
  commune: "Commune",
  departement: "Département",
  region: "Région",
  autre: "Autre organisation",
};

export const LIBELLES_TYPES_SERVICE: Record<string, string> = {
  hebergement_web: "Hébergement web",
  cloud: "Cloud",
  serveurs: "Serveurs",
  cdn: "Réseau de diffusion (CDN)",
  site_statique: "Site statique",
  messagerie: "Messagerie",
  bureautique: "Bureautique",
  dns: "DNS",
  stockage: "Stockage de fichiers",
  visioconference: "Visioconférence",
  gestion_projet: "Gestion de projet",
  messagerie_instantanee: "Messagerie instantanée",
  signature_electronique: "Signature électronique",
  envoi_emails: "Envoi d'e-mails",
  crm: "Relation usagers (CRM)",
  polices: "Polices de caractères",
  videos: "Vidéos",
  cartes: "Cartes",
  captcha: "CAPTCHA",
  discussion: "Discussion en ligne",
  bandeau_cookies: "Gestion du consentement",
  formulaires: "Formulaires",
  publications: "Publications",
  accessibilite: "Accessibilité",
  analytique: "Mesure d'audience",
  tests_ab: "Tests A/B",
};

const formatDate = new Intl.DateTimeFormat("fr-FR", { dateStyle: "long", timeZone: "Europe/Paris" });
const noms_pays = new Intl.DisplayNames(["fr"], { type: "region" });

export function date(iso: string): string {
  return formatDate.format(new Date(iso));
}

export function pays(code: string): string {
  if (code === "EU") return "Union européenne";
  try {
    return noms_pays.of(code) ?? code;
  } catch {
    return code;
  }
}

export function nombre(valeur: number, decimales = 0): string {
  return valeur.toLocaleString("fr-FR", {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  });
}

export function pourcentage(part: number, total: number): string {
  if (total === 0) return "—";
  return `${nombre((part / total) * 100)} %`;
}

export function descriptionNote(note: string): string {
  return `Note ${note} sur une échelle de A (meilleure) à E`;
}
