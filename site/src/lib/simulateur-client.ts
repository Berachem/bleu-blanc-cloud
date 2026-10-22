// Simulateur « Et si… ? » dans le navigateur : mode libre (scénario et fournisseur lus et
// écrits dans l'URL), « Ma commune serait-elle touchée ? » et copie du lien. Les données
// (/simulations.json, servi par le site lui-même) ne sont chargées qu'à la première
// interaction. Sans JavaScript, les résultats calculés au build restent affichés.
import { agreger, evaluer, fournisseursTombes, type ExportSimulations, type Scenario } from "./simulation.ts";
import { champsResultats, descriptionImpact, nombre, part, phrasePartage, titreScenario } from "./simulation-texte.ts";

let donnees: Promise<ExportSimulations> | null = null;
const charger = (): Promise<ExportSimulations> =>
  (donnees ??= fetch("/simulations.json").then((reponse) => reponse.json() as Promise<ExportSimulations>));

function scenarioCourant(racine: HTMLElement): { scenario: Scenario; fournisseur: string | null } {
  return {
    scenario: (racine.dataset.scenario as Scenario) ?? "panne",
    fournisseur: racine.dataset.fournisseur || null,
  };
}

function afficherResultats(racine: HTMLElement, export_: ExportSimulations): void {
  const { scenario, fournisseur } = scenarioCourant(racine);
  const agregat = agreger(export_.collectivites, fournisseursTombes(export_, scenario, fournisseur));
  const champs = champsResultats(agregat);
  const nom = fournisseur ? export_.fournisseurs[fournisseur]?.nom : undefined;
  const titre = titreScenario(scenario, nom);
  champs.titre = titre;
  champs.phrase = phrasePartage(titre, agregat, location.href);
  for (const element of racine.querySelectorAll<HTMLElement>("[data-champ]")) {
    const valeur = champs[element.dataset.champ ?? ""];
    if (valeur !== undefined) element.textContent = valeur;
  }
  for (const element of racine.querySelectorAll<HTMLElement>("[data-barre]")) {
    const [cle, code] = (element.dataset.barre ?? "").split(":") as ["par_region" | "par_tranche", string];
    const groupe = agregat[cle][code] ?? { total: 0, touchees: 0 };
    const largeur = groupe.total ? Math.round((1000 * groupe.touchees) / groupe.total) / 10 : 0;
    element.querySelector<HTMLElement>(".barres-simulation__barre")?.style.setProperty("--part", `${largeur}%`);
    const texte = element.querySelector<HTMLElement>("[data-valeur]");
    if (texte) texte.textContent = `${nombre(groupe.touchees)} / ${nombre(groupe.total)} (${part(groupe.touchees, groupe.total)})`;
  }
  racine.querySelector<HTMLAnchorElement>("[data-lien-fiche-scenario]")?.setAttribute("href", location.href);
}

function brancherFormulaire(racine: HTMLElement, arret: AbortSignal): void {
  const formulaire = racine.querySelector<HTMLFormElement>("[data-simulateur]");
  if (!formulaire) return;
  const choixFournisseur = formulaire.querySelector<HTMLSelectElement>("select[name='fournisseur']");
  const parametres = new URLSearchParams(location.search);
  const scenarioUrl = parametres.get("scenario") === "cloud_act" ? "cloud_act" : "panne";
  const fournisseurUrl = parametres.get("fournisseur");
  if (choixFournisseur && fournisseurUrl && [...choixFournisseur.options].some((o) => o.value === fournisseurUrl)) {
    choixFournisseur.value = fournisseurUrl;
  }
  const radio = formulaire.querySelector<HTMLInputElement>(`input[name='scenario'][value='${scenarioUrl}']`);
  if (radio) radio.checked = true;

  const appliquer = async (ecrireUrl: boolean) => {
    const scenario = (new FormData(formulaire).get("scenario") as Scenario) ?? "panne";
    racine.dataset.scenario = scenario;
    racine.dataset.fournisseur = scenario === "panne" ? (choixFournisseur?.value ?? "") : "";
    if (choixFournisseur) choixFournisseur.disabled = scenario !== "panne";
    if (ecrireUrl) {
      const url = new URL(location.href);
      url.search = "";
      url.searchParams.set("scenario", scenario);
      if (scenario === "panne" && choixFournisseur?.value) url.searchParams.set("fournisseur", choixFournisseur.value);
      history.replaceState(history.state, "", url);
    }
    afficherResultats(racine, await charger());
    racine.dispatchEvent(new CustomEvent("simulation:changement"));
  };
  formulaire.addEventListener("change", () => void appliquer(true), { signal: arret });
  formulaire.addEventListener("submit", (evenement) => {
    evenement.preventDefault();
    void appliquer(true);
  }, { signal: arret });
  if (parametres.has("scenario") || parametres.has("fournisseur")) void appliquer(false);
  else if (choixFournisseur) choixFournisseur.disabled = scenarioUrl !== "panne";
}

function brancherMaCommune(racine: HTMLElement, arret: AbortSignal): void {
  const boite = racine.querySelector<HTMLElement>("[data-ma-commune]");
  const champ = boite?.querySelector<HTMLInputElement>("input");
  const liste = boite?.querySelector<HTMLDataListElement>("datalist");
  const reponse = boite?.querySelector<HTMLElement>("[data-reponse]");
  if (!boite || !champ || !liste || !reponse) return;
  let rempli = false;
  const remplir = async () => {
    if (rempli) return;
    rempli = true;
    const export_ = await charger();
    liste.replaceChildren(
      ...export_.collectivites
        .map((ligne) => ligne.nom)
        .sort((a, b) => a.localeCompare(b, "fr"))
        .map((nom) => Object.assign(document.createElement("option"), { value: nom })),
    );
  };
  const repondre = async () => {
    const export_ = await charger();
    const ligne = export_.collectivites.find((l) => l.nom.toLowerCase() === champ.value.trim().toLowerCase());
    if (!ligne) {
      reponse.replaceChildren();
      return;
    }
    const { scenario, fournisseur } = scenarioCourant(racine);
    const { titre, details } = descriptionImpact(evaluer(ligne, fournisseursTombes(export_, scenario, fournisseur)));
    const titreElement = Object.assign(document.createElement("p"), { className: "simulation-commune__titre" });
    titreElement.append(Object.assign(document.createElement("strong"), { textContent: `${ligne.nom} : ${titre}` }));
    const elements = Object.assign(document.createElement("ul"), {});
    elements.append(...details.map((texte) => Object.assign(document.createElement("li"), { textContent: texte })));
    const lien = Object.assign(document.createElement("a"), {
      href: `/organisation/${encodeURIComponent(ligne.id)}/`,
      textContent: "Voir la fiche de cette collectivité",
    });
    reponse.replaceChildren(titreElement, elements, lien);
  };
  champ.addEventListener("focus", () => void remplir(), { signal: arret });
  champ.addEventListener("input", () => void repondre(), { signal: arret });
  racine.addEventListener("simulation:changement", () => void repondre(), { signal: arret });
}

function brancherCopie(racine: HTMLElement, arret: AbortSignal): void {
  for (const bouton of racine.querySelectorAll<HTMLButtonElement>("[data-copier]")) {
    bouton.addEventListener("click", async () => {
      const cible = bouton.dataset.copier === "phrase"
        ? racine.querySelector<HTMLElement>("[data-champ='phrase']")?.textContent ?? ""
        : location.href;
      const etat = racine.querySelector<HTMLElement>("[data-etat-copie]");
      try {
        await navigator.clipboard.writeText(cible);
        if (etat) etat.textContent = bouton.dataset.copier === "phrase" ? "Texte copié." : "Lien copié.";
      } catch {
        if (etat) etat.textContent = "Copie impossible : sélectionnez le texte à la main.";
      }
    }, { signal: arret });
  }
}

document.addEventListener("astro:page-load", () => {
  const racine = document.querySelector<HTMLElement>("[data-simulation]");
  if (!racine) return;
  const arret = new AbortController();
  brancherFormulaire(racine, arret.signal);
  brancherMaCommune(racine, arret.signal);
  brancherCopie(racine, arret.signal);
  document.addEventListener("astro:before-swap", () => arret.abort(), { once: true });
});
