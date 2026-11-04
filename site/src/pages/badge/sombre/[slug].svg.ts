// Badge (sombre) de chaque fiche : SVG autonome, généré au build. Il existe pour toutes les
// fiches (la note affichée est toujours l'actuelle, et une image intégrée ne casse jamais),
// mais il n'est proposé qu'aux organisations notées A.
import type { APIRoute, GetStaticPaths } from "astro";
import { svgBadge } from "../../../lib/badge";
import { donneesBadge } from "../../../lib/badge-donnees";
import { index } from "../../../lib/donnees";

export const getStaticPaths: GetStaticPaths = () =>
  index().map((entree) => ({ params: { slug: entree.slug }, props: { entree } }));

export const GET: APIRoute = ({ props }) =>
  new Response(svgBadge(donneesBadge(props.entree), "sombre"), {
    headers: { "Content-Type": "image/svg+xml; charset=utf-8" },
  });
