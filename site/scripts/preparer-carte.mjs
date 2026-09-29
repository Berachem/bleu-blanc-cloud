// Prépare le fond de carte des départements (à lancer une fois, résultat versionné).
//
// Source : france-geojson (Grégoire David), tracés IGN Admin Express COG, Licence Ouverte
// Etalab 2.0. Le GeoJSON est simplifié et quantifié en TopoJSON pour alléger le site.
//
// Usage : node scripts/preparer-carte.mjs [chemin/vers/departements-avec-outre-mer.geojson]
import { readFile, writeFile } from "node:fs/promises";
import { feature } from "topojson-client";
import { topology } from "topojson-server";
import { presimplify, quantile, simplify } from "topojson-simplify";

const URL_SOURCE =
  "https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements-avec-outre-mer.geojson";
const SORTIE = new URL("../src/donnees-carte/departements.topo.json", import.meta.url);
const PART_POINTS_CONSERVES = 0.025;

const cheminLocal = process.argv[2];
const geojson = cheminLocal
  ? JSON.parse(await readFile(cheminLocal, "utf-8"))
  : await (await fetch(URL_SOURCE)).json();

for (const entite of geojson.features) {
  entite.properties = { code: entite.properties.code, nom: entite.properties.nom };
}
const topo = presimplify(topology({ departements: geojson }, 1e5));
const simplifie = simplify(topo, quantile(topo, PART_POINTS_CONSERVES));
// Reconstruit une topologie compacte (sans les poids de simplification, coordonnées quantifiées)
const allege = topology({ departements: feature(simplifie, simplifie.objects.departements) }, 1e4);
const texte = JSON.stringify(allege);
await writeFile(SORTIE, texte);
const taille = Buffer.byteLength(texte);
console.log(`${geojson.features.length} départements → ${Math.round(taille / 1024)} Ko`);
