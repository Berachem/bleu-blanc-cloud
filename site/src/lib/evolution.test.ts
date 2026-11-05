// Tests de l'évolution du score (résumé et courbe).
import assert from "node:assert/strict";
import { test } from "node:test";
import { geometrieCourbe, pointsTries, resumerEvolution, type PointEvolution } from "./evolution.ts";

const hausse: PointEvolution[] = [
  { date: "2026-09-27T03:00:00Z", score: 100, note: "A" },
  { date: "2026-07-05T03:00:00Z", score: 62, note: "C" },
  { date: "2026-08-16T03:00:00Z", score: 74, note: "B" },
];

test("moins de deux analyses : pas d'évolution", () => {
  assert.equal(resumerEvolution([]), null);
  assert.equal(resumerEvolution(undefined), null);
  assert.equal(resumerEvolution([hausse[0]]), null);
  assert.equal(geometrieCourbe([hausse[0]]), null);
});

test("hausse, baisse et stabilité en une phrase", () => {
  const r = resumerEvolution(hausse);
  assert.ok(r);
  assert.equal(r.sens, "hausse");
  assert.equal(r.variation, 38);
  assert.equal(r.analyses, 3);
  assert.equal(r.texte, "Score en hausse : 62 (C) le 5 juillet 2026 → 100 (A) le 27 septembre 2026, soit +38 points.");

  const baisse = resumerEvolution([
    { date: "2026-08-01T03:00:00Z", score: 81, note: "B" },
    { date: "2026-09-12T03:00:00Z", score: 80, note: "B" },
  ]);
  assert.equal(baisse?.texte, "Score en baisse : 81 (B) le 1 août 2026 → 80 (B) le 12 septembre 2026, soit −1 point.");

  const stable = resumerEvolution([
    { date: "2026-08-01T03:00:00Z", score: 100, note: "A" },
    { date: "2026-09-12T03:00:00Z", score: 100, note: "A" },
  ]);
  assert.equal(stable?.sens, "stable");
  assert.equal(stable?.texte, "Score stable à 100/100 (note A) depuis le 1 août 2026.");
});

test("courbe : points dans la zone, ordre chronologique, bandes des notes", () => {
  const g = geometrieCourbe(hausse, 420, 200);
  assert.ok(g);
  assert.deepEqual(pointsTries(hausse)?.map((p) => p.score), [62, 74, 100]);
  assert.equal(g.points[0].x, g.zone.gauche);
  assert.equal(g.points[2].x, g.zone.droite);
  assert.equal(g.points[2].y, g.zone.haut); // 100 tout en haut
  assert.ok(g.points.every((p) => p.y >= g.zone.haut && p.y <= g.zone.bas));
  assert.match(g.chemin, /^M34 [\d.]+ L[\d.]+ [\d.]+ L406 12$/);
  assert.deepEqual(g.bandes.map((b) => b.note), ["A", "B", "C", "D", "E"]);
  assert.deepEqual(g.graduations.map((m) => m.libelle), ["août 26", "sept. 26"]);
});
