// Génère l'image de partage (Open Graph / Twitter) : public/partage.png, 1200 × 630.
// Rendu par Chromium (playwright-core, déjà en dépendance de développement) à partir d'un
// gabarit HTML aux couleurs du site : police Luciole auto-hébergée, logo et motif maison.
// L'image est versionnée : le serveur n'a pas besoin de Chromium. À relancer seulement si
// le design change : npm run image-partage
import { existsSync, readFileSync } from "node:fs";
import { chromium } from "playwright-core";

const RACINE = new URL("../", import.meta.url);
const SORTIE = new URL("public/partage.png", RACINE);
const LARGEUR = 1200;
const HAUTEUR = 630;
const CANDIDATS_CHROMIUM = [
  process.env.CHROMIUM_PATH,
  "/opt/pw-browsers/chromium",
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
].filter(Boolean);

const police = (fichier) =>
  `data:font/woff2;base64,${readFileSync(new URL(`public/polices/${fichier}`, RACINE)).toString("base64")}`;

// Logo : mêmes tracés que src/composants/Logo.astro
const NUAGE = "M16 44a15 15 0 0 1-2.2-29.8A19 19 0 0 1 50.5 12 16 16 0 0 1 48 44Z";
const logo = `
<svg width="92" height="66" viewBox="-0.5 -2.8 67.5 48.6" aria-hidden="true">
  <defs><clipPath id="n"><path d="${NUAGE}"/></clipPath></defs>
  <g clip-path="url(#n)">
    <rect x="-1" y="-3" width="23" height="49" fill="#002395"/>
    <rect x="22" y="-3" width="20" height="49" fill="#ffffff"/>
    <rect x="42" y="-3" width="26" height="49" fill="#ED2939"/>
  </g>
  <path d="${NUAGE}" fill="none" stroke="#f2f4ff" stroke-width="2" stroke-linejoin="round"/>
</svg>`;

// Motif des 12 étoiles en cercle (même dessin que src/composants/EtoilesEurope.astro),
// sans fond bleu : ce n'est pas le drapeau européen.
const branche = (cx, cy, r) =>
  Array.from({ length: 10 }, (_, k) => {
    const rayon = k % 2 === 0 ? r : r * 0.4;
    const a = (k * Math.PI) / 5 - Math.PI / 2;
    return `${(cx + rayon * Math.cos(a)).toFixed(1)},${(cy + rayon * Math.sin(a)).toFixed(1)}`;
  }).join(" ");
const etoiles = Array.from({ length: 12 }, (_, i) => {
  const angle = (i * Math.PI) / 6 - Math.PI / 2;
  return `<polygon points="${branche(100 + 70 * Math.cos(angle), 100 + 70 * Math.sin(angle), 11)}" fill="#FFCC00"/>`;
}).join("");

const NOTES = [
  ["A", "#2f5fd8", "#fff"],
  ["B", "#3a6bd6", "#fff"],
  ["C", "#ffcc00", "#1b1f3b"],
  ["D", "#f08a24", "#1b1f3b"],
  ["E", "#c41e3a", "#fff"],
];

const html = `<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><style>
@font-face { font-family: Luciole; font-weight: 400; src: url(${police("Luciole-Regular.woff2")}) format("woff2"); }
@font-face { font-family: Luciole; font-weight: 700; src: url(${police("Luciole-Bold.woff2")}) format("woff2"); }
* { box-sizing: border-box; }
html, body { margin: 0; }
body {
  position: relative; width: ${LARGEUR}px; height: ${HAUTEUR}px; overflow: hidden;
  font-family: Luciole, sans-serif; color: #f2f4ff;
  background:
    radial-gradient(900px 560px at -10% 0%, rgb(0 35 149 / 70%), transparent 62%),
    radial-gradient(760px 520px at 112% 100%, rgb(237 41 57 / 38%), transparent 62%),
    #0a0f24;
}
.bande { position: absolute; inset: 0 0 auto; height: 12px;
  background: linear-gradient(90deg, #002395 33.33%, #ffffff 33.33% 66.66%, #ed2939 66.66%); }
.etoiles { position: absolute; right: -160px; top: 50%; width: 520px; height: 520px;
  transform: translateY(-56%); opacity: 0.38; }
.contenu { position: relative; display: flex; flex-direction: column; height: 100%;
  padding: 62px 72px 56px; }
.marque { display: flex; align-items: center; gap: 22px; font-size: 40px; font-weight: 700;
  letter-spacing: -0.01em; }
.surtitre { margin-top: 38px; font-size: 21px; font-weight: 700; letter-spacing: 0.14em;
  text-transform: uppercase; color: #b0b8dc; }
h1 { margin: 16px 0 0; max-width: 820px; font-size: 70px; line-height: 1.02;
  letter-spacing: -0.04em; font-weight: 700; }
.degrade { background: linear-gradient(100deg, #7c9bff 0%, #f2f4ff 45%, #f2f4ff 55%, #ff7a86 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.bas { margin-top: auto; display: flex; align-items: center; justify-content: space-between; }
.notes { display: flex; gap: 12px; }
.note { display: grid; place-items: center; width: 58px; height: 58px; border-radius: 14px;
  font-size: 30px; font-weight: 700; box-shadow: 0 10px 24px -12px rgb(0 0 0 / 70%); }
.url { font-size: 26px; font-weight: 700; color: #b0b8dc; letter-spacing: -0.01em; }
</style></head>
<body>
  <div class="bande"></div>
  <svg class="etoiles" viewBox="0 0 200 200" aria-hidden="true">${etoiles}</svg>
  <main class="contenu">
    <div class="marque">${logo}<span>Bleu Blanc Cloud</span></div>
    <div class="surtitre">Observatoire indépendant · open source</div>
    <h1>Nos services publics dépendent-ils du <span class="degrade">cloud américain</span>&nbsp;?</h1>
    <div class="bas">
      <div class="notes">${NOTES.map(([n, fond, texte]) => `<span class="note" style="background:${fond};color:${texte}">${n}</span>`).join("")}</div>
      <div class="url">bleublanccloud.berachem.dev</div>
    </div>
  </main>
</body></html>`;

const executable = CANDIDATS_CHROMIUM.find((chemin) => existsSync(chemin));
if (!executable) {
  console.error("Chromium introuvable : définissez CHROMIUM_PATH.");
  process.exit(1);
}
const navigateur = await chromium.launch({ executablePath: executable });
const page = await navigateur.newPage({ viewport: { width: LARGEUR, height: HAUTEUR } });
await page.setContent(html, { waitUntil: "load" });
await page.evaluate(() => document.fonts.ready);
await page.screenshot({ path: SORTIE.pathname, type: "png" });
await navigateur.close();
console.log(`Image de partage écrite : ${SORTIE.pathname}`);
