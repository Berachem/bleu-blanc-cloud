// Animations et bascule de thème (JavaScript vanilla, aucune dépendance).
// Relancé à chaque page grâce à l'évènement « astro:page-load » des View Transitions.
// Sans JavaScript ou avec prefers-reduced-motion, tout le contenu est affiché directement.

const CLE_THEME = "bbc-theme";
function mouvementReduit(): boolean {
  return matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function lireTheme(): "light" | "dark" {
  try {
    return localStorage.getItem(CLE_THEME) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function appliquerTheme(theme: "light" | "dark"): void {
  document.documentElement.dataset.theme = theme;
  for (const bouton of document.querySelectorAll<HTMLButtonElement>("[data-bascule-theme]")) {
    bouton.setAttribute("aria-pressed", String(theme === "light"));
    bouton.setAttribute("aria-label", theme === "dark" ? "Passer en thème clair" : "Passer en thème sombre");
  }
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", theme === "dark" ? "#0a0f24" : "#fafafd");
}

function brancherBascule(): void {
  appliquerTheme(lireTheme());
  for (const bouton of document.querySelectorAll<HTMLButtonElement>("[data-bascule-theme]")) {
    bouton.addEventListener("click", () => {
      const suivant = document.documentElement.dataset.theme === "light" ? "dark" : "light";
      appliquerTheme(suivant);
      try {
        localStorage.setItem(CLE_THEME, suivant);
      } catch {
        // stockage indisponible (navigation privée) : le choix vaut pour la page seulement
      }
    });
  }
}

// Menu mobile (hamburger) : le bouton déplie la navigation en panneau par-dessus la page.
// Fermeture : lien choisi, clic à l'extérieur, touche Échap ou passage en grand écran. Les
// écouteurs sont retirés à chaque changement de page (View Transitions).
function brancherMenu(): void {
  const bouton = document.querySelector<HTMLButtonElement>("[data-bouton-menu]");
  const navigation = document.getElementById("navigation-principale");
  if (!bouton || !navigation) return;
  const ouvert = () => bouton.getAttribute("aria-expanded") === "true";
  const basculer = (etat: boolean) => {
    bouton.setAttribute("aria-expanded", String(etat));
    bouton.setAttribute("aria-label", etat ? "Fermer le menu" : "Ouvrir le menu");
    navigation.classList.toggle("navigation--ouverte", etat);
  };
  const arret = new AbortController();
  const { signal } = arret;
  bouton.addEventListener("click", () => basculer(!ouvert()), { signal });
  navigation.addEventListener(
    "click",
    (evenement) => {
      if ((evenement.target as HTMLElement).closest("a")) basculer(false);
    },
    { signal },
  );
  document.addEventListener(
    "click",
    (evenement) => {
      const cible = evenement.target as Node;
      if (ouvert() && !navigation.contains(cible) && !bouton.contains(cible)) basculer(false);
    },
    { signal },
  );
  document.addEventListener(
    "keydown",
    (evenement) => {
      if (evenement.key === "Escape" && ouvert()) {
        basculer(false);
        bouton.focus();
      }
    },
    { signal },
  );
  matchMedia("(min-width: 1120px)").addEventListener(
    "change",
    (evenement) => {
      if (evenement.matches) basculer(false);
    },
    { signal },
  );
  document.addEventListener("astro:before-swap", () => arret.abort(), { once: true });
}

// Loupe de l'en-tête : ouvre le panneau de recherche et place le curseur dans le champ.
// Fermeture : clic à l'extérieur, touche Échap (retour sur la loupe) ou lien choisi. La
// touche « / » l'ouvre depuis n'importe quelle page (hors saisie en cours).
function brancherRecherche(): void {
  const bouton = document.querySelector<HTMLButtonElement>("[data-bouton-recherche]");
  const panneau = document.getElementById("panneau-recherche");
  if (!bouton || !panneau) return;
  const champ = panneau.querySelector<HTMLInputElement>('input[type="search"]');
  const ouvert = () => !panneau.hidden;
  const basculer = (etat: boolean, rendreFocus = false) => {
    panneau.hidden = !etat;
    bouton.setAttribute("aria-expanded", String(etat));
    bouton.setAttribute("aria-label", etat ? "Fermer la recherche" : "Rechercher une organisation");
    if (etat) champ?.focus();
    else if (rendreFocus) bouton.focus();
  };
  const arret = new AbortController();
  const { signal } = arret;
  bouton.addEventListener("click", () => basculer(!ouvert()), { signal });
  panneau.addEventListener(
    "click",
    (evenement) => {
      if ((evenement.target as HTMLElement).closest("a")) basculer(false);
    },
    { signal },
  );
  document.addEventListener(
    "click",
    (evenement) => {
      const cible = evenement.target as Node;
      if (ouvert() && !panneau.contains(cible) && !bouton.contains(cible)) basculer(false);
    },
    { signal },
  );
  document.addEventListener(
    "keydown",
    (evenement) => {
      if (evenement.key === "Escape" && ouvert()) {
        basculer(false, true);
        return;
      }
      const cible = evenement.target as HTMLElement;
      const enSaisie = cible.closest("input, textarea, select, [contenteditable]") !== null;
      const modificateur = evenement.ctrlKey || evenement.metaKey || evenement.altKey;
      if (evenement.key === "/" && !ouvert() && !enSaisie && !modificateur) {
        evenement.preventDefault();
        basculer(true);
      }
    },
    { signal },
  );
  document.addEventListener("astro:before-swap", () => arret.abort(), { once: true });
}

// Fenêtre « Analyser mon site » : tout élément [data-ouvrir-analyse] (boutons, lien de la
// recherche) l'ouvre. Un clic sur le fond la ferme. Sans <dialog> ni JavaScript, le lien
// mène directement au formulaire Codeberg.
function brancherFenetreAnalyse(): void {
  const fenetre = document.getElementById("fenetre-analyse");
  if (!(fenetre instanceof HTMLDialogElement) || typeof fenetre.showModal !== "function") return;
  const arret = new AbortController();
  const { signal } = arret;
  document.addEventListener(
    "click",
    (evenement) => {
      const declencheur = (evenement.target as HTMLElement).closest("[data-ouvrir-analyse]");
      if (!declencheur) return;
      evenement.preventDefault();
      fenetre.showModal();
    },
    { signal },
  );
  fenetre.addEventListener(
    "click",
    (evenement) => {
      if (evenement.target === fenetre) fenetre.close();
    },
    { signal },
  );
  document.addEventListener(
    "astro:before-swap",
    () => {
      arret.abort();
      if (fenetre.open) fenetre.close();
    },
    { once: true },
  );
}

// Badge « Rapport IA disponible » (en-tête de fiche) : défile jusqu'à la synthèse, y place
// le focus et la met brièvement en évidence. Sans JavaScript, l'ancre suffit.
function brancherLienRapport(): void {
  const lien = document.querySelector<HTMLAnchorElement>("[data-lien-rapport]");
  const section = document.getElementById("rapport-ia");
  if (!lien || !section) return;
  lien.addEventListener("click", (evenement) => {
    evenement.preventDefault();
    section.classList.add("apparition--visible");
    section.scrollIntoView({ behavior: mouvementReduit() ? "auto" : "smooth", block: "start" });
    history.replaceState(history.state, "", "#rapport-ia");
    section.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
    section.classList.remove("rapport-signale");
    void section.offsetWidth; // relance l'animation à chaque clic
    section.classList.add("rapport-signale");
  });
}

function animerCompteur(element: HTMLElement): void {
  const cible = Number(element.dataset.compteur);
  const decimales = Number(element.dataset.decimales ?? 0);
  const suffixe = element.dataset.suffixe ?? "";
  const ecrire = (valeur: number) => {
    element.textContent =
      new Intl.NumberFormat("fr-FR", {
        minimumFractionDigits: decimales,
        maximumFractionDigits: decimales,
      }).format(valeur) + suffixe;
  };
  if (!Number.isFinite(cible) || mouvementReduit()) {
    return;
  }
  const duree = 1400;
  const debut = performance.now();
  const pas = (maintenant: number) => {
    const t = Math.min(1, (maintenant - debut) / duree);
    ecrire(cible * (1 - Math.pow(1 - t, 3)));
    if (t < 1) requestAnimationFrame(pas);
  };
  ecrire(0);
  requestAnimationFrame(pas);
}

function colorerCarte(carte: SVGSVGElement): void {
  const zones = [...carte.querySelectorAll<SVGPathElement>("path")];
  zones
    .map((zone) => ({ zone, x: zone.getBBox().x }))
    .sort((a, b) => a.x - b.x)
    .forEach(({ zone }, rang) => {
      zone.style.transitionDelay = `${Math.min(rang * 12, 1400)}ms`;
    });
  requestAnimationFrame(() => carte.classList.add("carte--coloree"));
}

type Action = [selecteur: string, action: (element: Element) => void];
const ACTIONS: Action[] = [
  ["[data-compteur]", (e) => animerCompteur(e as HTMLElement)],
  ["[data-carte]", (e) => colorerCarte(e as SVGSVGElement)],
  [".jauge, .barre", (e) => e.classList.add("jauge--remplie")],
  [".apparition", (e) => e.classList.add("apparition--visible")],
];

function lancerAnimations(): void {
  const racine = document.documentElement;
  if (mouvementReduit() || !("IntersectionObserver" in window)) {
    racine.classList.remove("js-animations");
    return;
  }
  racine.classList.add("js-animations");
  const observateur = new IntersectionObserver(
    (entrees) => {
      for (const entree of entrees) {
        if (!entree.isIntersecting) continue;
        for (const [selecteur, action] of ACTIONS) {
          if (entree.target.matches(selecteur)) action(entree.target);
        }
        observateur.unobserve(entree.target);
      }
    },
    { threshold: 0.15, rootMargin: "0px 0px -6% 0px" },
  );
  for (const [selecteur] of ACTIONS) {
    document.querySelectorAll(selecteur).forEach((element) => observateur.observe(element));
  }
  document.addEventListener("astro:before-swap", () => observateur.disconnect(), { once: true });
}

document.addEventListener("astro:page-load", () => {
  brancherBascule();
  brancherMenu();
  brancherRecherche();
  brancherFenetreAnalyse();
  brancherLienRapport();
  lancerAnimations();
});

export {};
