// Vérifie qu'aucune page du site construit (dist/) ne déclenche de requête externe
// ni ne dépose de cookie. Seule exception admise : le fond de plan IGN des cartes de
// situation (« Plan IGN » par défaut sur les fiches), qui ne doit contacter que
// data.geopf.fr et disparaît quand le visiteur choisit « Contours » (ADR-0005).
// Usage : npm run build && npm run verifier:externe [-- --captures dossier]
import { createReadStream, existsSync, readFileSync, readdirSync, statSync } from "node:fs";
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
  ".jpg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
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

// Tuiles simulées : la vérification ne dépend pas du réseau
const HOTE_FOND = "https://data.geopf.fr/";
const PNG_VIDE = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
  "base64",
);
const urlDe = (fichier) =>
  `${origine}/${path.relative(DIST, fichier).replace(/index\.html$/, "").replace(/\\/g, "/")}`;
const avecFond = (fichier) => readFileSync(fichier, "utf8").includes('name="fond-carte"');

const executable = CANDIDATS_CHROMIUM.find((c) => existsSync(c));
const navigateur = await chromium.launch({ executablePath: executable });
const externes = [];
let pagesVisitees = 0;
let fichesAvecFond = 0;
let tuilesParDefaut = 0;
for (const schema of ["light", "dark"]) {
  const contexte = await navigateur.newContext({ colorScheme: schema, viewport: { width: 390, height: 844 } });
  // Le thème du site est choisi par le bouton (mémorisé), pas par la préférence système
  await contexte.addInitScript((theme) => {
    try {
      localStorage.setItem("bbc-theme", theme);
    } catch {}
  }, schema);
  const onglet = await contexte.newPage();
  // Fond IGN admis seulement sur la page en cours si elle porte une carte de situation
  let fondAdmis = false;
  let tuilesPage = 0;
  await onglet.route(`${HOTE_FOND}**`, (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: PNG_VIDE }),
  );
  onglet.on("request", (requete) => {
    const url = requete.url();
    if (url.startsWith(origine) || url.startsWith("data:")) return;
    if (fondAdmis && url.startsWith(HOTE_FOND)) {
      tuilesPage += 1;
      return;
    }
    externes.push(`${url} (depuis ${onglet.url()})`);
  });
  for (const fichier of pagesHtml(DIST)) {
    const url = urlDe(fichier);
    fondAdmis = avecFond(fichier);
    tuilesPage = 0;
    await onglet.goto(url, { waitUntil: "networkidle" });
    if (fondAdmis) {
      fichesAvecFond += 1;
      tuilesParDefaut += tuilesPage;
      if (tuilesPage === 0) externes.push(`fond de plan IGN par défaut : aucune tuile demandée (${url})`);
    }
    // Déclenche la recherche instantanée (chargement différé de /recherche.json) : champ
    // visible de la page, sinon celui du panneau ouvert par la loupe de l'en-tête
    let champ = await onglet.$("input[type=search]:visible");
    const loupe = await onglet.$("[data-bouton-recherche]");
    if (!champ && loupe && (await loupe.isVisible())) {
      await loupe.click();
      champ = await onglet.$("#panneau-recherche input[type=search]:visible");
    }
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
// Choix « Contours » : plus aucune requête vers l'IGN, y compris après rechargement (choix
// mémorisé dans le navigateur)
const ficheAvecCarte = pagesHtml(DIST).find(
  (f) => f.includes(`${path.sep}organisation${path.sep}`) && avecFond(f),
);
let contoursMemorise = false;
if (ficheAvecCarte) {
  const contexte = await navigateur.newContext({ viewport: { width: 1280, height: 900 } });
  const onglet = await contexte.newPage();
  let tuilesApresChoix = 0;
  let choixFait = false;
  await onglet.route(`${HOTE_FOND}**`, (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: PNG_VIDE }),
  );
  onglet.on("request", (requete) => {
    const url = requete.url();
    if (url.startsWith(origine) || url.startsWith("data:")) return;
    if (url.startsWith(HOTE_FOND) && !choixFait) return;
    if (url.startsWith(HOTE_FOND)) tuilesApresChoix += 1;
    externes.push(`${url} (fond « Contours » choisi)`);
  });
  const url = urlDe(ficheAvecCarte);
  await onglet.goto(url, { waitUntil: "networkidle" });
  await onglet.check("input[name='fond-carte'][value='contours']");
  choixFait = true;
  await onglet.reload({ waitUntil: "networkidle" });
  await onglet.waitForTimeout(500);
  contoursMemorise = await onglet.isChecked("input[name='fond-carte'][value='contours']");
  if (!contoursMemorise) externes.push(`fond « Contours » non mémorisé après rechargement (${url})`);
  if (tuilesApresChoix > 0) externes.push(`fond « Contours » : ${tuilesApresChoix} tuile(s) IGN demandée(s)`);
  const cookies = await contexte.cookies();
  if (cookies.length > 0) externes.push(`cookies déposés (fond de plan) : ${cookies.map((c) => c.name).join(", ")}`);
  await contexte.close();
}
await navigateur.close();
serveur.close();

if (externes.length > 0) {
  console.error(`✗ ${externes.length} requête(s) externe(s) ou cookie(s) :`);
  for (const ligne of [...new Set(externes)]) console.error(`  - ${ligne}`);
  process.exit(1);
}
console.log(
  `✓ ${pagesVisitees} pages visitées (thèmes clair et sombre) : aucun cookie, aucune requête externe hors fond de plan IGN.`,
);
if (fichesAvecFond > 0) {
  console.log(
    `✓ Fond « Plan IGN » par défaut sur ${fichesAvecFond} visite(s) de fiche : ${tuilesParDefaut} tuile(s), uniquement vers data.geopf.fr.`,
  );
}
if (contoursMemorise) {
  console.log("✓ Fond « Contours » choisi : mémorisé, plus aucune requête externe après rechargement.");
}
