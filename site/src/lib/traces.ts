// Compaction des tracés SVG produits par d3-geo (module pur, testé par traces.test.ts).

/** Réécrit un tracé d3 (« M12.3,45.6L13.1,46Z », coordonnées absolues au dixième) en
 * coordonnées relatives et nombres abrégés : environ 40 % de caractères en moins. Les calculs
 * se font en dixièmes entiers, sans cumul d'arrondis. */
export function compacter(d: string): string {
  const nombre = (dixiemes: number) => {
    const texte = String(dixiemes / 10);
    return texte.replace(/^(-?)0\./, "$1.");
  };
  const paire = (x: number, y: number) => {
    const b = nombre(y);
    return `${nombre(x)}${b.startsWith("-") ? "" : ","}${b}`;
  };
  let sortie = "";
  let [cx, cy, debutX, debutY] = [0, 0, 0, 0];
  let precedente = "";
  for (const [, commande, valeurs] of d.matchAll(/([MLZ])([^MLZ]*)/g)) {
    if (commande === "Z") {
      sortie += "z";
      [cx, cy] = [debutX, debutY];
      precedente = "z";
      continue;
    }
    const [x, y] = valeurs.split(",").map((v) => Math.round(Number(v) * 10));
    const [dx, dy] = [x - cx, y - cy];
    if (commande === "M") {
      // Premier point en absolu (« M »), les suivants en relatif (« m »)
      precedente = sortie ? "m" : "M";
      sortie += sortie ? `m${paire(dx, dy)}` : `M${paire(x, y)}`;
      [debutX, debutY] = [x, y];
    } else {
      if (dx === 0 && dy === 0) continue;
      const texte = paire(dx, dy);
      // « l » se répète implicitement, et les paires qui suivent « m » valent « l » ; après
      // « M » (absolu) ou « z », la commande « l » doit être écrite
      const separateur =
        precedente === "l" || precedente === "m" ? (texte.startsWith("-") ? "" : " ") : "l";
      sortie += separateur + texte;
      precedente = "l";
    }
    [cx, cy] = [x, y];
  }
  return sortie;
}
