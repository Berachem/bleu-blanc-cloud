// Tests du moteur du simulateur : mêmes cas que le moteur Python du scanner.
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import {
  agreger,
  evaluer,
  fournisseurPrincipal,
  fournisseursProposes,
  fournisseursTombes,
  type LigneSimulation,
} from "./simulation.ts";

const cas = JSON.parse(
  fs.readFileSync(new URL("../../../scanner/tests/fixtures/simulation/cas.json", import.meta.url), "utf-8"),
) as {
  lignes: LigneSimulation[];
  scenarios: { nom: string; tombes: string[]; impacts: Record<string, unknown>; agregat: unknown }[];
};

for (const scenario of cas.scenarios) {
  test(`cas commun « ${scenario.nom} » identique au moteur Python`, () => {
    const tombes = new Set(scenario.tombes);
    for (const ligne of cas.lignes) {
      assert.deepEqual(evaluer(ligne, tombes), scenario.impacts[ligne.id], ligne.id);
    }
    assert.deepEqual(agreger(cas.lignes, tombes), scenario.agregat);
  });
}

test("DNS chez un seul opérateur : effet domino ; NS répartis : résilient", () => {
  const parId = new Map(cas.lignes.map((l) => [l.id, l]));
  assert.equal(evaluer(parId.get("tout-chez-ovh")!, new Set(["ovhcloud"])).statut, "injoignable");
  const impact = evaluer(parId.get("dns-reparti")!, new Set(["ovhcloud"]));
  assert.deepEqual([impact.dns, impact.site, impact.messagerie], ["resilient", "hors_ligne", "ok"]);
});

test("scénarios, fournisseurs proposés et fournisseur principal", () => {
  const donnees = {
    fournisseurs: {
      microsoft: { id: "microsoft", nom: "Microsoft", pays: "US", niveau: "D", soumis_cloud_act: true, statut_referentiel: "verifie" as const, nombre_collectivites: 5 },
      ovhcloud: { id: "ovhcloud", nom: "OVHcloud", pays: "FR", niveau: "A", soumis_cloud_act: false, statut_referentiel: "verifie" as const, nombre_collectivites: 9 },
      "ip-max": { id: "ip-max", nom: "IP-Max", pays: "CH", niveau: "B", soumis_cloud_act: false, statut_referentiel: "a_verifier" as const, nombre_collectivites: 30 },
    },
  };
  assert.deepEqual([...fournisseursTombes(donnees, "cloud_act")], ["microsoft"]);
  assert.deepEqual([...fournisseursTombes(donnees, "panne", "ovhcloud")], ["ovhcloud"]);
  assert.deepEqual(fournisseursProposes(donnees).map((f) => f.id), ["ovhcloud", "microsoft"]);
  const ligne = cas.lignes.find((l) => l.id === "derriere-cloudflare")!;
  assert.equal(fournisseurPrincipal(ligne, new Set(["cloudflare", "google"])), "cloudflare");
  assert.equal(fournisseurPrincipal(ligne, new Set(["ovhcloud"])), null);
});
