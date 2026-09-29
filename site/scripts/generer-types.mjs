// Génère les types TypeScript du contrat de données à partir du schéma JSON exporté
// par le scanner (bbcloud schemas).
import { readFile, writeFile } from "node:fs/promises";
import { compile } from "json-schema-to-typescript";

const SCHEMA = new URL("../src/types/donnees.schema.json", import.meta.url);
const SORTIE = new URL("../src/types/donnees.d.ts", import.meta.url);

const schema = JSON.parse(await readFile(SCHEMA, "utf-8"));

// Les titres des propriétés (ajoutés par pydantic) produiraient un alias de type par champ :
// on ne conserve que les titres des modèles.
function retirerTitres(noeud, estModele) {
  if (Array.isArray(noeud)) return noeud.forEach((element) => retirerTitres(element, false));
  if (noeud === null || typeof noeud !== "object") return;
  if (!estModele) delete noeud.title;
  for (const [cle, valeur] of Object.entries(noeud)) {
    if (cle === "$defs") {
      for (const modele of Object.values(valeur)) retirerTitres(modele, true);
    } else {
      retirerTitres(valeur, false);
    }
  }
}
retirerTitres(schema, true);
const code = await compile(schema, "DonneesSite", {
  bannerComment:
    "/* Fichier généré par scripts/generer-types.mjs à partir de donnees.schema.json — ne pas modifier. */",
  additionalProperties: false,
  unreachableDefinitions: true,
  style: { singleQuote: false },
});
await writeFile(SORTIE, code);
console.log("Types écrits dans src/types/donnees.d.ts");
