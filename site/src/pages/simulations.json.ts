// Données du simulateur libre (dépendances par collectivité), chargées par le navigateur à
// la première interaction : réelles (bbcloud exporter) ou de démonstration.
import type { APIRoute } from "astro";
import { simulations } from "../lib/donnees";

export const GET: APIRoute = () =>
  new Response(JSON.stringify(simulations()), {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
