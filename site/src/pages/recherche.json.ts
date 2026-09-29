// Index léger pour la recherche instantanée, chargé à la demande par le navigateur.
import type { APIRoute } from "astro";
import { index } from "../lib/donnees";

export const GET: APIRoute = () =>
  new Response(
    JSON.stringify(
      index().map((e) => [
        e.slug,
        e.nom,
        e.departement_nom ?? "",
        e.note,
        e.score,
        e.domaine,
        e.note_provisoire ? 1 : 0,
      ]),
    ),
    { headers: { "Content-Type": "application/json; charset=utf-8" } },
  );
