// Génère le PDF du kit « 5 questions à poser à votre prestataire » à partir de la page
// imprimable du site construit (dist/). Le kit ne contient aucun chiffre : le PDF est
// versionné et n'a besoin d'être régénéré que si son texte change (le serveur n'a pas
// besoin de Chromium). Usage : npm run build && npm run kit-pdf
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { chromium } from "playwright-core";

const DIST = path.resolve("dist");
const SORTIE = path.resolve("public/dossiers/kit-5-questions-prestataire.pdf");
const TYPES = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".woff2": "font/woff2", ".svg": "image/svg+xml" };
const CANDIDATS_CHROMIUM = [
  process.env.CHROMIUM_PATH,
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  "/usr/bin/chromium",
  "/usr/bin/google-chrome",
].filter(Boolean);

const serveur = createServer((requete, reponse) => {
  let chemin = decodeURIComponent(new URL(requete.url, "http://localhost").pathname);
  if (chemin.endsWith("/")) chemin += "index.html";
  const fichier = path.join(DIST, chemin);
  if (!fichier.startsWith(DIST) || !existsSync(fichier) || statSync(fichier).isDirectory()) {
    reponse.writeHead(404);
    reponse.end();
    return;
  }
  reponse.writeHead(200, { "Content-Type": TYPES[path.extname(fichier)] ?? "application/octet-stream" });
  createReadStream(fichier).pipe(reponse);
});
await new Promise((resoudre) => serveur.listen(0, "127.0.0.1", resoudre));
const executable = CANDIDATS_CHROMIUM.find((c) => existsSync(c));
if (!executable) {
  console.error("Chromium introuvable : définissez CHROMIUM_PATH.");
  process.exit(1);
}
const navigateur = await chromium.launch({ executablePath: executable });
const contexte = await navigateur.newContext();
// Thème clair pour l'impression
await contexte.addInitScript(() => localStorage.setItem("bbc-theme", "light"));
const page = await contexte.newPage();
await page.goto(`http://127.0.0.1:${serveur.address().port}/dossiers/souverainete-securite/kit/`, { waitUntil: "networkidle" });
await page.evaluate(() => document.fonts.ready);
await page.emulateMedia({ media: "print" });
await page.pdf({ path: SORTIE, format: "A4", printBackground: true, margin: { top: "18mm", bottom: "18mm", left: "16mm", right: "16mm" } });
await navigateur.close();
serveur.close();
console.log(`Kit PDF écrit : ${SORTIE}`);
