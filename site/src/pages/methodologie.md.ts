// Méthodologie en Markdown brut (même source que la page /methodologie/) : lue par le serveur
// MCP de Bleu Blanc Cloud et utilisable par tout outil qui préfère le texte au HTML.
import type { APIRoute } from "astro";
import { SITE } from "../config";
import brut from "../../../docs/methodologie.md?raw";

// En-tête YAML (titre, version, date) retiré : seul le texte de la méthodologie est servi
const texte = brut.replace(/^---\n[\s\S]*?\n---\n+/, "");

export const GET: APIRoute = () =>
  new Response(texte.replaceAll("https://bleublanccloud.fr/", `${SITE.url}/`), {
    headers: { "Content-Type": "text/markdown; charset=utf-8" },
  });
