// Tests de la compaction des tracés : lancer « npm test » (exécuteur de tests de Node).
import assert from "node:assert/strict";
import { test } from "node:test";
import { compacter } from "./traces.ts";

/** Interprète un tracé SVG (M, m, L, l, z et paires implicites) en sous-tracés de points
 * absolus, exprimés en dixièmes entiers. */
function points(d: string): number[][][] {
  const jetons = d.match(/[MmLlZz]|-?(?:\d+\.?\d*|\.\d+)/g) ?? [];
  const sousTraces: number[][][] = [];
  let [x, y, debutX, debutY] = [0, 0, 0, 0];
  let commande = "";
  for (let i = 0; i < jetons.length; ) {
    const jeton = jetons[i];
    if (/[MmLlZz]/.test(jeton)) {
      commande = jeton;
      i++;
      if (jeton === "z" || jeton === "Z") [x, y] = [debutX, debutY];
      continue;
    }
    const [a, b] = [Number(jetons[i]), Number(jetons[i + 1])];
    i += 2;
    if (commande === "M" || commande === "m") {
      [x, y] = commande === "M" ? [a, b] : [x + a, y + b];
      [debutX, debutY] = [x, y];
      sousTraces.push([[x, y]]);
      commande = commande === "M" ? "L" : "l";
    } else {
      [x, y] = commande === "L" ? [a, b] : [x + a, y + b];
      sousTraces[sousTraces.length - 1].push([x, y]);
    }
  }
  return sousTraces.map((s) => s.map(([u, v]) => [Math.round(u * 10), Math.round(v * 10)]));
}

/** Même tracé, sans les points répétés (que la compaction retire). */
function sansDoublons(sousTraces: number[][][]): number[][][] {
  return sousTraces.map((s) =>
    s.filter((p, i) => i === 0 || p[0] !== s[i - 1][0] || p[1] !== s[i - 1][1]),
  );
}

const CAS = [
  "M155.9,127.5L153.5,129L152.4,130L152.4,133.1Z",
  "M10,10L20,10L20,20ZM30.5,30L40,30L40,40.2L30.5,30Z",
  "M0.5,0.5L0.4,0.3L-0.2,-0.7L5,5ZM100,100L101.1,99.9L100,100Z",
  "M1,1L2,2M5,5L6,7L6,7L8,9",
  "M300.1,12.3L0,0L319.9,239.9L-5.5,-0.1Z",
];

test("la compaction décrit exactement les mêmes points", () => {
  for (const d of CAS) {
    assert.deepEqual(points(compacter(d)), sansDoublons(points(d)), d);
  }
});

test("le premier point reste absolu, les suivants deviennent relatifs", () => {
  assert.equal(compacter("M10,10L20,10L20,20Z"), "M10,10l10,0 0,10z");
  assert.equal(compacter("M10,10L9.5,9.5Z"), "M10,10l-.5-.5z");
});

test("le tracé compacté est nettement plus court", () => {
  const d = "M155.9,127.5L153.5,129L152.4,130L152.4,133.1L150.4,135.2L147.9,133.7Z";
  assert.ok(compacter(d).length < d.length * 0.75);
});

test("précision paramétrable : centièmes sans perte ni cumul d'arrondis", () => {
  const d = "M12.34,6.79L12.35,6.78L12.4,6.7Z";
  assert.equal(compacter(d, 2), "M12.34,6.79l.01-.01 .05-.08z");
  assert.equal(compacter("M1.004,2L1.009,2Z", 2), "M1,2l.01,0z");
});
