import type { APIRoute } from "astro";
import { SITE } from "../config";

// robots.txt généré au build : l'adresse du plan du site suit le domaine publié (DOMAINE_SITE).
export const GET: APIRoute = () =>
  new Response(`User-agent: *\nAllow: /\n\nSitemap: ${new URL("/sitemap.xml", SITE.url).href}\n`, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
