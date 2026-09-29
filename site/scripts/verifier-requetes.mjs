// Vérifie qu'aucune page du site construit (dist/) ne déclenche de requête externe
// ni ne dépose de cookie. Usage : npm run build && npm run verifier:externe [-- --captures dossier]
import { createReadStream, existsSync, readdirSync, statSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import { chromium } from "playwright-core";

const DIST = path.resolve("dist");
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css",
  ".js": "text/javascript",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".txt": "text/plain",
};
const CANDIDATS_CHROMIUM = [
  process.env.CHROMIUM_PATH,
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
].filter(Boolean);

function pagesHtml(dossier) {
  return readdirSync(dossier).flatMap((nom) => {
    const chemin = path.join(dossier, nom);
    if (statSync(chemin).isDirectory()) return pagesHtml(chemin);
    return nom.endsWith(".html") ? [chemin] : [];
  });
}

const serveur = createServer((requete, reponse) => {
  let chemin = decodeURIComponent(new URL(requete.url, "http://localhost").pathname);
  if (chemin.endsWith("/")) chemin += "index.html";
  let fichier = path.join(DIST, chemin);
  if (!existsSync(fichier) && existsSync(`${fichier}.html`)) fichier = `${fichier}.html`;
  if (!fichier.startsWith(DIST) || !existsSync(fichier) || statSync(fichier).isDirectory()) {
    reponse.writeHead(404, { "Content-Type": TYPES[".html"] });
    createReadStream(path.join(DIST, "404.html")).pipe(reponse);
    return;
  }
  reponse.writeHead(200, { "Content-Type": TYPES[path.extname(fichier)] ?? "application/octet-stream" });
  createReadStream(fichier).pipe(reponse);
});
await new Promise((resoudre) => serveur.listen(0, "127.0.0.1", resoudre));
const origine = `http://127.0.0.1:${serveur.address().port}`;

const indexCaptures = process.argv.indexOf("--captures");
const dossierCaptures = indexCaptures > 0 ? path.resolve(process.argv[indexCaptures + 1]) : null;
if (dossierCaptures) await mkdir(dossierCaptures, { recursive: true });

const executable = CANDIDATS_CHROMIUM.find((c) => existsSync(c));
const navigateur = await chromium.launch({ executablePath: executable });
const externes = [];
let pagesVisitees = 0;
for (const schema of ["light", "dark"]) {
  const contexte = await navigateur.newContext({ colorScheme: schema, viewport: { width: 390, height: 844 } });
  const onglet = await contexte.newPage();
  onglet.on("request", (requete) => {
    if (!requete.url().startsWith(origine) && !requete.url().startsWith("data:")) {
      externes.push(`${requete.url()} (depuis ${onglet.url()})`);
    }
  });
  for (const fichier of pagesHtml(DIST)) {
    const url = `${origine}/${path.relative(DIST, fichier).replace(/index\.html$/, "").replace(/\\/g, "/")}`;
    await onglet.goto(url, { waitUntil: "networkidle" });
    // Déclenche la recherche instantanée (chargement différé de /recherche.json)
    const champ = await onglet.$("input[type=search]");
    if (champ) {
      await champ.fill("ex");
      await onglet.waitForTimeout(150);
    }
    pagesVisitees += 1;
    if (dossierCaptures && ["index.html", "carte/index.html"].includes(path.relative(DIST, fichier))) {
      const nom = path.relative(DIST, fichier).replace(/\/?index\.html$/, "") || "accueil";
      await onglet.screenshot({ path: path.join(dossierCaptures, `${nom}-${schema}.png`), fullPage: true });
    }
  }
  const cookies = await contexte.cookies();
  if (cookies.length > 0) externes.push(`cookies déposés : ${cookies.map((c) => c.name).join(", ")}`);
  await contexte.close();
}
await navigateur.close();
serveur.close();

if (externes.length > 0) {
  console.error(`✗ ${externes.length} requête(s) externe(s) ou cookie(s) :`);
  for (const ligne of [...new Set(externes)]) console.error(`  - ${ligne}`);
  process.exit(1);
}
console.log(`✓ ${pagesVisitees} pages visitées (thèmes clair et sombre) : aucune requête externe, aucun cookie.`);
