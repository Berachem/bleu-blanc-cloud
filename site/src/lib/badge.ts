// Badge à intégrer sur le site d'une collectivité : SVG autonome (aucune police ni image
// externe), généré au build pour chaque fiche, en version claire et sombre. Il affiche
// toujours la note actuelle : s'il est intégré par lien, il suit les analyses suivantes.

export interface DonneesBadge {
  nom: string;
  note: string;
  score: number;
  dateScan: string;
  provisoire: boolean;
  domaine: string;
}

export type ThemeBadge = "clair" | "sombre";

export const LARGEUR_BADGE = 380;
export const HAUTEUR_BADGE = 108;

const COULEURS_NOTES: Record<string, { fond: string; texte: string }> = {
  A: { fond: "#003399", texte: "#ffffff" },
  B: { fond: "#3a6bd6", texte: "#ffffff" },
  C: { fond: "#ffcc00", texte: "#1b1f3b" },
  D: { fond: "#f08a24", texte: "#1b1f3b" },
  E: { fond: "#c41e3a", texte: "#ffffff" },
};

const THEMES: Record<ThemeBadge, { fond: string; bordure: string; texte: string; secondaire: string; contourNuage: string }> = {
  clair: { fond: "#ffffff", bordure: "#d9deee", texte: "#1b1f3b", secondaire: "#4a5070", contourNuage: "#1b1f3b" },
  sombre: { fond: "#0a0f24", bordure: "#2a3466", texte: "#f2f4ff", secondaire: "#b0b8dc", contourNuage: "#f2f4ff" },
};

const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

export function echapper(texte: string): string {
  return texte
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

/** « 2026-09-27T03:00:00Z » → « 27 sept. 2026 » */
export function dateCourte(iso: string): string {
  const d = new Date(iso);
  return `${d.getUTCDate()} ${MOIS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

/** Coupe un nom trop long pour la largeur du badge (≈ 24 caractères, même avec une police
 * de repli plus large que Luciole). */
export function nomCourt(nom: string, maximum = 24): string {
  return nom.length <= maximum ? nom : `${nom.slice(0, maximum - 1).trimEnd()}…`;
}

export function texteAlternatif(donnees: DonneesBadge): string {
  return `Bleu Blanc Cloud : ${donnees.nom} obtient la note ${donnees.note}${donnees.provisoire ? " (provisoire)" : ""} en souveraineté numérique (${donnees.score}/100, analyse du ${dateCourte(donnees.dateScan)})`;
}

export function svgBadge(donnees: DonneesBadge, theme: ThemeBadge = "clair"): string {
  const t = THEMES[theme];
  const note = COULEURS_NOTES[donnees.note] ?? COULEURS_NOTES.E;
  // Sur fond sombre, le bleu de la note A est éclairci (même teinte que le site en sombre)
  const fondNote = theme === "sombre" && donnees.note === "A" ? "#2f5fd8" : note.fond;
  const police = "Luciole, system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif";
  const nuage = "M16 44a15 15 0 0 1-2.2-29.8A19 19 0 0 1 50.5 12 16 16 0 0 1 48 44Z";
  const sousTitre = donnees.provisoire ? "Note provisoire" : "Souveraineté numérique";
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${LARGEUR_BADGE}" height="${HAUTEUR_BADGE}" viewBox="0 0 ${LARGEUR_BADGE} ${HAUTEUR_BADGE}" role="img" aria-label="${echapper(texteAlternatif(donnees))}">
<title>${echapper(texteAlternatif(donnees))}</title>
<defs><clipPath id="n"><path d="${nuage}"/></clipPath><clipPath id="c"><rect width="${LARGEUR_BADGE}" height="${HAUTEUR_BADGE}" rx="16"/></clipPath></defs>
<g clip-path="url(#c)">
<rect width="${LARGEUR_BADGE}" height="${HAUTEUR_BADGE}" fill="${t.fond}"/>
<rect width="${LARGEUR_BADGE / 3}" height="5" fill="#002395"/><rect x="${LARGEUR_BADGE / 3}" width="${LARGEUR_BADGE / 3}" height="5" fill="#ffffff"/><rect x="${(2 * LARGEUR_BADGE) / 3}" width="${LARGEUR_BADGE / 3}" height="5" fill="#ed2939"/>
</g>
<rect x="0.5" y="0.5" width="${LARGEUR_BADGE - 1}" height="${HAUTEUR_BADGE - 1}" rx="15.5" fill="none" stroke="${t.bordure}"/>
<g transform="translate(16 30) scale(0.62)"><g clip-path="url(#n)"><rect x="-1" y="-3" width="23" height="49" fill="#002395"/><rect x="22" y="-3" width="20" height="49" fill="#ffffff"/><rect x="42" y="-3" width="26" height="49" fill="#ed2939"/></g><path d="${nuage}" fill="none" stroke="${t.contourNuage}" stroke-width="2.4" stroke-linejoin="round"/></g>
<g font-family="${police}">
<text x="66" y="34" font-size="11" font-weight="700" letter-spacing="1.2" fill="${t.secondaire}">BLEU BLANC CLOUD</text>
<text x="66" y="55" font-size="16" font-weight="700" fill="${t.texte}">${echapper(nomCourt(donnees.nom))}</text>
<text x="66" y="75" font-size="12" fill="${t.secondaire}">${sousTitre} · ${donnees.score}/100</text>
<text x="66" y="93" font-size="11" fill="${t.secondaire}">Analyse du ${dateCourte(donnees.dateScan)}</text>
<rect x="${LARGEUR_BADGE - 80}" y="22" width="64" height="64" rx="14" fill="${fondNote}"/>
<text x="${LARGEUR_BADGE - 48}" y="68" font-size="38" font-weight="700" text-anchor="middle" fill="${note.texte}">${echapper(donnees.note)}</text>
</g>
</svg>
`;
}

/** Code HTML à coller sur le site de la collectivité (badge suivi : il se met à jour). */
export function codeIntegration(urlSite: string, slug: string, donnees: DonneesBadge, theme: ThemeBadge): string {
  const image = new URL(`/badge/${theme === "sombre" ? "sombre/" : ""}${slug}.svg`, urlSite).href;
  const fiche = new URL(`/organisation/${slug}/`, urlSite).href;
  return `<a href="${fiche}"><img src="${image}" width="${LARGEUR_BADGE}" height="${HAUTEUR_BADGE}" alt="${echapper(texteAlternatif(donnees))}" loading="lazy"></a>`;
}
