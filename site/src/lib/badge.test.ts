// Tests du badge à intégrer.
import assert from "node:assert/strict";
import { test } from "node:test";
import { codeIntegration, dateCourte, echapper, nomCourt, svgBadge, texteAlternatif, type DonneesBadge } from "./badge.ts";

const exemple: DonneesBadge = {
  nom: "Commune d'Exempleville",
  note: "A",
  score: 96,
  dateScan: "2026-09-27T03:00:00Z",
  provisoire: false,
  domaine: "exempleville.example",
};

test("SVG autonome : note, score, date, aucune ressource externe", () => {
  const svg = svgBadge(exemple);
  assert.match(svg, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg"/);
  assert.match(svg, />A<\/text>/);
  assert.match(svg, /96\/100/);
  assert.match(svg, /27 sept\. 2026/);
  assert.doesNotMatch(svg, /href=|url\(http|@import|<image/);
  assert.match(svg, /Commune d&apos;Exempleville/);
});

test("versions claire et sombre, note provisoire signalée", () => {
  assert.match(svgBadge(exemple, "clair"), /#ffffff/);
  assert.match(svgBadge(exemple, "sombre"), /#0a0f24/);
  const provisoire = svgBadge({ ...exemple, provisoire: true });
  assert.match(provisoire, /Note provisoire/);
  assert.match(texteAlternatif({ ...exemple, provisoire: true }), /\(provisoire\)/);
});

test("échappement, noms longs et date", () => {
  assert.equal(echapper(`<a & "b">`), "&lt;a &amp; &quot;b&quot;&gt;");
  assert.equal(nomCourt("Communauté d'agglomération du Grand Exempleville-sur-Mer").length, 24);
  assert.equal(dateCourte("2026-01-05T10:00:00Z"), "5 janv. 2026");
});

test("code d'intégration : lien vers la fiche et image du site", () => {
  const code = codeIntegration("https://bleublanccloud.fr", "exempleville-demo", exemple, "sombre");
  assert.match(code, /href="https:\/\/bleublanccloud\.fr\/organisation\/exempleville-demo\/"/);
  assert.match(code, /src="https:\/\/bleublanccloud\.fr\/badge\/sombre\/exempleville-demo\.svg"/);
  assert.match(code, /alt="Bleu Blanc Cloud : Commune d&apos;Exempleville obtient la note A/);
});
