// Tableaux issus du Markdown (méthodologie) : recopie, au build, l'intitulé de chaque colonne
// dans l'attribut data-libelle des cellules du corps. Sur petit écran, le thème affiche alors
// chaque ligne en bloc, chaque valeur précédée de son libellé (theme.css, « Tableaux
// éditoriaux »), sans défilement horizontal. Travaille sur le HTML produit par le moteur
// Markdown d'Astro (structure simple et régulière), sans dépendance.

const RE_TABLEAU = /<table\b[^>]*>[\s\S]*?<\/table>/g;
const RE_ENTETE = /<thead\b[^>]*>([\s\S]*?)<\/thead>/;
const RE_TH = /<th\b[^>]*>([\s\S]*?)<\/th>/g;
const RE_CORPS = /<tbody\b[^>]*>[\s\S]*?<\/tbody>/;
const RE_LIGNE = /<tr\b[^>]*>[\s\S]*?<\/tr>/g;
const RE_CELLULE = /<(td|th)\b([^>]*)>/g;

/** Texte d'une cellule d'en-tête, prêt pour un attribut (entités HTML conservées). */
const libelle = (contenu: string): string =>
  contenu
    .replace(/<[^>]+>/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/"/g, "&quot;");

export function annoterTableaux(html: string): string {
  return html.replace(RE_TABLEAU, (tableau) => {
    const entete = RE_ENTETE.exec(tableau);
    if (!entete) return tableau;
    const libelles = [...entete[1].matchAll(RE_TH)].map(([, contenu]) => libelle(contenu));
    return tableau.replace(RE_CORPS, (corps) =>
      corps.replace(RE_LIGNE, (ligne) => {
        let rang = 0;
        return ligne.replace(RE_CELLULE, (balise, nom: string, attributs: string) => {
          const texte = libelles[rang++];
          if (!texte || /\sdata-libelle=/.test(attributs)) return balise;
          return `<${nom}${attributs} data-libelle="${texte}">`;
        });
      }),
    );
  });
}
