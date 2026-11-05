// Évolution du score d'une organisation : résumé en une phrase et géométrie de la courbe
// (SVG dessiné au build, aucune bibliothèque). Les points viennent de l'export : un par jour,
// recalculés avec la méthodologie et les référentiels actuels, le dernier est l'analyse
// affichée sur la fiche.

export type NoteEvolution = "A" | "B" | "C" | "D" | "E";

export interface PointEvolution {
  date: string;
  score: number;
  note: NoteEvolution;
  provisoire?: boolean;
}

export interface ResumeEvolution {
  sens: "hausse" | "baisse" | "stable";
  variation: number;
  premier: PointEvolution;
  dernier: PointEvolution;
  analyses: number;
  texte: string;
}

export interface GeometrieCourbe {
  largeur: number;
  hauteur: number;
  chemin: string;
  points: (PointEvolution & { x: number; y: number })[];
  bandes: { note: NoteEvolution; y: number; hauteur: number; seuil: number }[];
  graduations: { x: number; libelle: string }[];
  zone: { gauche: number; droite: number; haut: number; bas: number };
}

// Seuils des notes (méthodologie, section 9) : A ≥ 85 · B ≥ 70 · C ≥ 50 · D ≥ 30 · E < 30
const SEUILS: [NoteEvolution, number, number][] = [
  ["A", 85, 100],
  ["B", 70, 85],
  ["C", 50, 70],
  ["D", 30, 50],
  ["E", 0, 30],
];

const dateLongue = new Intl.DateTimeFormat("fr-FR", { dateStyle: "long", timeZone: "Europe/Paris" });
const moisCourt = new Intl.DateTimeFormat("fr-FR", { month: "short", year: "2-digit", timeZone: "Europe/Paris" });

export function dateEvolution(iso: string): string {
  return dateLongue.format(new Date(iso));
}

/** Points triés par date ; null s'il n'y a pas au moins deux analyses (pas d'évolution). */
export function pointsTries(points: readonly PointEvolution[] | undefined | null): PointEvolution[] | null {
  const tries = [...(points ?? [])].sort((a, b) => Date.parse(a.date) - Date.parse(b.date));
  return tries.length >= 2 ? tries : null;
}

/** « Score en hausse : 62 (C) le 5 juillet 2026 → 100 (A) le 27 septembre 2026, soit +38 points. » */
export function resumerEvolution(points: readonly PointEvolution[] | undefined | null): ResumeEvolution | null {
  const tries = pointsTries(points);
  if (!tries) return null;
  const premier = tries[0];
  const dernier = tries[tries.length - 1];
  const variation = dernier.score - premier.score;
  const sens = variation > 0 ? "hausse" : variation < 0 ? "baisse" : "stable";
  const ecart = Math.abs(variation);
  const pluriel = ecart > 1 ? "s" : "";
  const debut = `${premier.score} (${premier.note}) le ${dateEvolution(premier.date)}`;
  const fin = `${dernier.score} (${dernier.note}) le ${dateEvolution(dernier.date)}`;
  const texte =
    sens === "stable"
      ? `Score stable à ${dernier.score}/100 (note ${dernier.note}) depuis le ${dateEvolution(premier.date)}.`
      : `Score en ${sens} : ${debut} → ${fin}, soit ${variation > 0 ? "+" : "−"}${ecart} point${pluriel}.`;
  return { sens, variation, premier, dernier, analyses: tries.length, texte };
}

/** Géométrie de la courbe : abscisse proportionnelle au temps, ordonnée de 0 à 100. */
export function geometrieCourbe(
  points: readonly PointEvolution[],
  largeur = 420,
  hauteur = 200,
): GeometrieCourbe | null {
  const tries = pointsTries(points);
  if (!tries) return null;
  const zone = { gauche: 34, droite: largeur - 14, haut: 12, bas: hauteur - 28 };
  const debut = Date.parse(tries[0].date);
  const fin = Date.parse(tries[tries.length - 1].date);
  const duree = Math.max(fin - debut, 1);
  const x = (iso: string) => zone.gauche + ((Date.parse(iso) - debut) / duree) * (zone.droite - zone.gauche);
  const y = (score: number) => zone.bas - (Math.max(0, Math.min(100, score)) / 100) * (zone.bas - zone.haut);
  const arrondi = (v: number) => Math.round(v * 10) / 10;
  const places = tries.map((p) => ({ ...p, x: arrondi(x(p.date)), y: arrondi(y(p.score)) }));
  const chemin = places.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join(" ");
  const bandes = SEUILS.map(([note, bas, haut]) => ({
    note,
    seuil: bas,
    y: arrondi(y(haut)),
    hauteur: arrondi(y(bas) - y(haut)),
  }));
  // Graduations : premier jour de chaque mois couvert, au plus 6 (les autres sont sautées)
  const mois: { x: number; libelle: string }[] = [];
  const curseur = new Date(debut);
  curseur.setUTCDate(1);
  curseur.setUTCHours(0, 0, 0, 0);
  curseur.setUTCMonth(curseur.getUTCMonth() + 1);
  while (curseur.getTime() <= fin) {
    mois.push({ x: arrondi(x(curseur.toISOString())), libelle: moisCourt.format(curseur) });
    curseur.setUTCMonth(curseur.getUTCMonth() + 1);
  }
  const pas = Math.ceil(mois.length / 6) || 1;
  const graduations = mois.filter((_, i) => i % pas === 0);
  return { largeur, hauteur, chemin, points: places, bandes, graduations, zone };
}
