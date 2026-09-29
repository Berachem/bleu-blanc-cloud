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
  lancerAnimations();
});

export {};
