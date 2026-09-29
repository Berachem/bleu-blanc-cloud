// Prépare les fonds de carte (à lancer une fois, résultats versionnés dans src/donnees-carte) :
//
// - departements.topo.json : carte de France de l'accueil, très simplifiée ;
// - situation.topo.json : départements plus détaillés, avec le code de leur région, et
//   régions obtenues par fusion des départements (frontières identiques) ; sert aux cartes
//   de situation des fiches. Ces fichiers ne sont lus qu'au build : seul le tracé utile à
//   chaque fiche est inséré dans sa page.
//
// Source : france-geojson (Grégoire David), tracés IGN Admin Express COG, Licence Ouverte
// Etalab 2.0. Le rattachement département → région est déduit des géométries des régions
// (même source) et vérifié.
//
// Usage : node scripts/preparer-carte.mjs [departements.geojson] [regions.geojson]
import { readFile, writeFile } from "node:fs/promises";
import { feature, mergeArcs } from "topojson-client";
import { topology } from "topojson-server";
import { presimplify, quantile, simplify } from "topojson-simplify";

const DEPOT = "https://raw.githubusercontent.com/gregoiredavid/france-geojson/master";
const SORTIE_FRANCE = new URL("../src/donnees-carte/departements.topo.json", import.meta.url);
const SORTIE_SITUATION = new URL("../src/donnees-carte/situation.topo.json", import.meta.url);
const PART_POINTS_FRANCE = 0.025;
const PART_POINTS_SITUATION = 0.2;

async function charger(cheminLocal, fichier) {
  if (cheminLocal) return JSON.parse(await readFile(cheminLocal, "utf-8"));
  return (await fetch(`${DEPOT}/${fichier}`)).json();
}

function polygones(geometrie) {
  return geometrie.type === "MultiPolygon" ? geometrie.coordinates : [geometrie.coordinates];
}

// Test planaire du point dans le polygone (longitude, latitude), insensible au sens des anneaux
function dansAnneau([x, y], anneau) {
  let dedans = false;
  for (let i = 0, j = anneau.length - 1; i < anneau.length; j = i++) {
    const [xi, yi] = anneau[i];
    const [xj, yj] = anneau[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) dedans = !dedans;
  }
  return dedans;
}
const dansGeometrie = (point, geometrie) =>
  polygones(geometrie).some(
    ([exterieur, ...trous]) => dansAnneau(point, exterieur) && !trous.some((t) => dansAnneau(point, t)),
  );

function aire(anneau) {
  let somme = 0;
  for (let i = 0; i < anneau.length - 1; i++) {
    somme += anneau[i][0] * anneau[i + 1][1] - anneau[i + 1][0] * anneau[i][1];
  }
  return Math.abs(somme) / 2;
}

// Point intérieur du plus grand polygone : milieu du plus large segment intérieur d'une
// ligne horizontale (le centroïde peut tomber dehors, ex. Hauts-de-Seine en croissant)
function pointInterieur(geometrie) {
  const polygone = polygones(geometrie).reduce((a, b) => (aire(b[0]) > aire(a[0]) ? b : a));
  const latitudes = polygone[0].map(([, y]) => y);
  const [yMin, yMax] = [Math.min(...latitudes), Math.max(...latitudes)];
  let meilleur = null;
  for (const t of [0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8]) {
    const y = yMin + t * (yMax - yMin);
    const abscisses = [];
    for (const anneau of polygone) {
      for (let i = 0; i < anneau.length - 1; i++) {
        const [x1, y1] = anneau[i];
        const [x2, y2] = anneau[i + 1];
        if (y1 > y !== y2 > y) abscisses.push(x1 + ((y - y1) * (x2 - x1)) / (y2 - y1));
      }
    }
    abscisses.sort((a, b) => a - b);
    for (let i = 0; i + 1 < abscisses.length; i += 2) {
      const largeur = abscisses[i + 1] - abscisses[i];
      if (!meilleur || largeur > meilleur.largeur) {
        meilleur = { largeur, point: [(abscisses[i] + abscisses[i + 1]) / 2, y] };
      }
    }
  }
  return meilleur.point;
}

const [cheminDepartements, cheminRegions] = process.argv.slice(2);
const departements = await charger(cheminDepartements, "departements-avec-outre-mer.geojson");
const regions = await charger(cheminRegions, "regions-avec-outre-mer.geojson");

// 1. Carte de France (accueil)
const entitesFrance = departements.features.map((f) => ({
  ...f,
  properties: { code: f.properties.code, nom: f.properties.nom },
}));
const topoFrance = presimplify(topology({ departements: { type: "FeatureCollection", features: entitesFrance } }, 1e5));
const simplifieFrance = simplify(topoFrance, quantile(topoFrance, PART_POINTS_FRANCE));
const allegeFrance = topology(
  { departements: feature(simplifieFrance, simplifieFrance.objects.departements) },
  1e4,
);

// 2. Cartes de situation : départements avec leur région
const nomsRegions = new Map(regions.features.map((r) => [r.properties.code, r.properties.nom]));
const entitesSituation = departements.features.map((f) => {
  const point = pointInterieur(f.geometry);
  if (!dansGeometrie(point, f.geometry)) {
    throw new Error(`Point intérieur hors du département ${f.properties.code}`);
  }
  const trouvees = regions.features.filter((r) => dansGeometrie(point, r.geometry));
  if (trouvees.length !== 1) {
    throw new Error(`Département ${f.properties.code} : ${trouvees.length} région(s) trouvée(s)`);
  }
  return {
    ...f,
    properties: { code: f.properties.code, nom: f.properties.nom, region: trouvees[0].properties.code },
  };
});
// Simplification RELATIVE : la carte de situation d'une commune affiche son département sur
// toute la largeur, quelle que soit sa taille. Le poids de chaque point (aire du triangle
// qu'il forme) est donc divisé par l'aire du plus petit département qui borde son arc : les
// petits départements (Hauts-de-Seine…) gardent leurs détails, les grands perdent le superflu.
const topoSituation = presimplify(
  topology({ departements: { type: "FeatureCollection", features: entitesSituation } }, 1e6),
);
const aireMinParArc = new Map();
for (const [rang, geometrie] of topoSituation.objects.departements.geometries.entries()) {
  const aireDepartement = polygones(entitesSituation[rang].geometry).reduce(
    (somme, [exterieur]) => somme + aire(exterieur),
    0,
  );
  const arcs = geometrie.type === "Polygon" ? [geometrie.arcs] : geometrie.arcs;
  for (const indice of arcs.flat(2)) {
    const arc = indice < 0 ? ~indice : indice;
    aireMinParArc.set(arc, Math.min(aireMinParArc.get(arc) ?? Infinity, aireDepartement));
  }
}
for (const [arc, points] of topoSituation.arcs.entries()) {
  const facteur = aireMinParArc.get(arc) ?? 1;
  for (const point of points) if (Number.isFinite(point[2])) point[2] /= facteur;
}
const simplifieSituation = simplify(topoSituation, quantile(topoSituation, PART_POINTS_SITUATION));
const allegeSituation = topology(
  { departements: feature(simplifieSituation, simplifieSituation.objects.departements) },
  1e6,
);
// Régions : fusion des départements dans la même topologie (arcs partagés)
const parRegion = new Map();
for (const geometrie of allegeSituation.objects.departements.geometries) {
  const code = geometrie.properties.region;
  parRegion.set(code, [...(parRegion.get(code) ?? []), geometrie]);
}
for (const code of nomsRegions.keys()) {
  if (!parRegion.has(code)) throw new Error(`Région ${code} sans département`);
}
allegeSituation.objects.regions = {
  type: "GeometryCollection",
  geometries: [...parRegion.entries()].map(([code, geometries]) => ({
    ...mergeArcs(allegeSituation, geometries),
    properties: { code, nom: nomsRegions.get(code) },
  })),
};

for (const [sortie, topo, libelle] of [
  [SORTIE_FRANCE, allegeFrance, "carte de France"],
  [SORTIE_SITUATION, allegeSituation, "cartes de situation"],
]) {
  const texte = JSON.stringify(topo);
  await writeFile(sortie, texte);
  console.log(`${libelle} : ${Math.round(Buffer.byteLength(texte) / 1024)} Ko`);
}
console.log(`${entitesSituation.length} départements, ${parRegion.size} régions`);
