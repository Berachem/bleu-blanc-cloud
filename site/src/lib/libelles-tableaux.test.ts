// Tests de l'annotation des tableaux Markdown : lancer « npm test ».
import assert from "node:assert/strict";
import { test } from "node:test";
import { annoterTableaux } from "./libelles-tableaux.ts";

test("chaque cellule du corps reçoit l'intitulé de sa colonne", () => {
  const html =
    "<p>Avant</p><table><thead><tr><th>Catégorie</th><th align=\"right\"><strong> Poids </strong></th></tr></thead>" +
    "<tbody><tr><td>Messagerie</td><td align=\"right\">25</td></tr><tr><td>DNS</td><td>10</td></tr></tbody></table>";
  assert.equal(
    annoterTableaux(html),
    "<p>Avant</p><table><thead><tr><th>Catégorie</th><th align=\"right\"><strong> Poids </strong></th></tr></thead>" +
      '<tbody><tr><td data-libelle="Catégorie">Messagerie</td><td align="right" data-libelle="Poids">25</td></tr>' +
      '<tr><td data-libelle="Catégorie">DNS</td><td data-libelle="Poids">10</td></tr></tbody></table>',
  );
});

test("les guillemets de l'intitulé sont échappés et les entités conservées", () => {
  const html =
    '<table><thead><tr><th>Ce qui est « collecté » &amp; "noté"</th></tr></thead><tbody><tr><td>x</td></tr></tbody></table>';
  assert.match(annoterTableaux(html), /<td data-libelle="Ce qui est « collecté » &amp; &quot;noté&quot;">x<\/td>/);
});

test("chaque tableau utilise ses propres intitulés ; un tableau sans en-tête est laissé tel quel", () => {
  const sansEntete = "<table><tbody><tr><td>seul</td></tr></tbody></table>";
  const html =
    "<table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>" +
    sansEntete +
    "<table><thead><tr><th>B</th></tr></thead><tbody><tr><td>2</td></tr></tbody></table>";
  const resultat = annoterTableaux(html);
  assert.ok(resultat.includes('<td data-libelle="A">1</td>'));
  assert.ok(resultat.includes(sansEntete));
  assert.ok(resultat.includes('<td data-libelle="B">2</td>'));
});
