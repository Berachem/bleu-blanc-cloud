import type { APIRoute } from "astro";
import { SITE } from "../config";
import { meta, observatoire } from "../lib/donnees";

// Plan du site pour les moteurs de recherche (protocole sitemaps.org), généré au build sans
// dépendance. Seules les fiches de l'observatoire y figurent : les fiches d'analyses sur
// demande restent consultables par leur lien mais ne sont pas signalées aux moteurs.
const PAGES_FIXES: { chemin: string; campagne?: boolean }[] = [
  { chemin: "/", campagne: true },
  { chemin: "/carte/", campagne: true },
  { chemin: "/classements/", campagne: true },
  { chemin: "/alternatives/" },
  { chemin: "/methodologie/" },
  { chemin: "/a-propos/" },
  { chemin: "/retrait/" },
  { chemin: "/mentions-legales/" },
];

const echapper = (texte: string): string =>
  texte.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const jour = (dateIso: string): string => dateIso.slice(0, 10);

const url = (chemin: string, modifieLe?: string): string =>
  `  <url><loc>${echapper(new URL(chemin, SITE.url).href)}</loc>${modifieLe ? `<lastmod>${jour(modifieLe)}</lastmod>` : ""}</url>`;

export const GET: APIRoute = () => {
  const { date_campagne } = meta();
  const lignes = [
    ...PAGES_FIXES.map(({ chemin, campagne }) => url(chemin, campagne ? date_campagne : undefined)),
    ...[...observatoire()]
      .sort((a, b) => a.slug.localeCompare(b.slug))
      .map((e) => url(`/organisation/${encodeURIComponent(e.slug)}/`, e.date_scan)),
  ];
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${lignes.join("\n")}
</urlset>
`;
  return new Response(xml, { headers: { "Content-Type": "application/xml; charset=utf-8" } });
};
