// Carte de situation des fiches : zoom, déplacement et fond de plan IGN à la demande.
// JavaScript maison, sans bibliothèque ; sans JavaScript, la carte reste le SVG statique.
//
// - Zoom : boutons, Ctrl (ou ⌘) + molette, pincement, double-clic ; déplacement au glisser
//   une fois la carte agrandie. Le zoom modifie la « viewBox » du SVG : le tracé reste net.
// - Fond de plan : aucune tuile n'est chargée tant que le visiteur n'a pas choisi « Plan IGN »
//   ou « Photo aérienne ». Les tuiles WMTS de la Géoplateforme de l'IGN (projection Web
//   Mercator) sont alors placées sous les tracés, projetés eux aussi en Mercator au build
//   (paramètres k, tx, ty dans data-projection). Choix mémorisé dans le navigateur.

const ESPACE_SVG = "http://www.w3.org/2000/svg";
const CLE_FOND = "bbc-fond-carte";
const URL_WMTS = "https://data.geopf.fr/wmts";
const TAILLE_TUILE = 256;
/** Au-delà de ce nombre d'images, les tuiles d'un autre niveau sont retirées sans attendre. */
const TUILES_MAX = 160;

type Fond = "contours" | "plan" | "photo";
const COUCHES: Record<Exclude<Fond, "contours">, { couche: string; format: string; zoomMax: number }> = {
  plan: { couche: "GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", format: "image/png", zoomMax: 18 },
  photo: { couche: "ORTHOIMAGERY.ORTHOPHOTOS", format: "image/jpeg", zoomMax: 19 },
};

interface Vue {
  x: number;
  y: number;
  l: number;
  h: number;
}

function lireFond(): Fond {
  try {
    const valeur = localStorage.getItem(CLE_FOND);
    return valeur === "plan" || valeur === "photo" ? valeur : "contours";
  } catch {
    return "contours";
  }
}

function ecrireFond(fond: Fond): void {
  try {
    if (fond === "contours") localStorage.removeItem(CLE_FOND);
    else localStorage.setItem(CLE_FOND, fond);
  } catch {
    // Stockage indisponible (navigation privée…) : le choix vaut pour la page seulement
  }
}

function urlTuile(fond: Exclude<Fond, "contours">, z: number, colonne: number, ligne: number): string {
  const { couche, format } = COUCHES[fond];
  const parametres = new URLSearchParams({
    SERVICE: "WMTS",
    REQUEST: "GetTile",
    VERSION: "1.0.0",
    LAYER: couche,
    STYLE: "normal",
    TILEMATRIXSET: "PM",
    TILEMATRIX: String(z),
    TILEROW: String(ligne),
    TILECOL: String(colonne),
    FORMAT: format,
  });
  return `${URL_WMTS}?${parametres}`;
}

const mouvementReduit = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const borner = (valeur: number, min: number, max: number) => Math.min(max, Math.max(min, valeur));

function brancher(figure: HTMLElement, arret: AbortSignal): void {
  const svg = figure.querySelector<SVGSVGElement>("svg[data-carte]");
  if (!svg) return;
  const [bx, by, bl, bh] = (svg.getAttribute("viewBox") ?? "0 0 320 240").split(" ").map(Number);
  const base: Vue = { x: bx, y: by, l: bl, h: bh };
  const zoomMax = Number(svg.dataset.zoomMax) || 64;
  const projection = svg.dataset.projection?.split(" ").map(Number) ?? null;
  const cadreCible = svg.dataset.cadreCible?.split(" ").map(Number) ?? null;
  const aide = figure.querySelector<HTMLElement>("[data-aide-zoom]");
  const boutons = new Map(
    [...figure.querySelectorAll<HTMLButtonElement>("[data-zoom]")].map((b) => [b.dataset.zoom, b]),
  );
  let vue: Vue = { ...base };
  let fond: Fond = projection ? lireFond() : "contours";

  // ------------------------------------------------------------------ Vue et rendu

  const echelle = () => base.l / vue.l;
  /** Vue bornée : agrandissement entre 1 et zoomMax, centre toujours dans le cadre initial. */
  const contraindre = (v: Vue): Vue => {
    const l = borner(v.l, base.l / zoomMax, base.l);
    const h = (l * base.h) / base.l;
    const cx = borner(v.x + v.l / 2, base.x, base.x + base.l);
    const cy = borner(v.y + v.h / 2, base.y, base.y + base.h);
    return { x: cx - l / 2, y: cy - h / 2, l, h };
  };

  let rendu = 0;
  const planifier = () => {
    if (!rendu) rendu = requestAnimationFrame(dessiner);
  };
  function dessiner(): void {
    rendu = 0;
    svg!.setAttribute("viewBox", `${vue.x} ${vue.y} ${vue.l} ${vue.h}`);
    const e = echelle();
    figure.classList.toggle("carte-situation--zoomee", e > 1.01);
    figure.classList.toggle("carte-situation--zoom-fort", e >= 4);
    const moins = boutons.get("moins");
    const plus = boutons.get("plus");
    if (moins) moins.disabled = e <= 1.01;
    if (plus) plus.disabled = e >= zoomMax - 0.01;
    majTuiles();
  }

  /** Coordonnées SVG d'un point de l'écran. */
  const versSvg = (x: number, y: number) => {
    const matrice = svg.getScreenCTM();
    return matrice ? new DOMPoint(x, y).matrixTransform(matrice.inverse()) : new DOMPoint(0, 0);
  };

  /** Agrandit (facteur > 1) ou réduit la vue en gardant fixe le point (px, py). */
  function zoomer(facteur: number, px = vue.x + vue.l / 2, py = vue.y + vue.h / 2): void {
    const l = borner(vue.l / facteur, base.l / zoomMax, base.l);
    const rapport = l / vue.l;
    vue = contraindre({
      x: px - (px - vue.x) * rapport,
      y: py - (py - vue.y) * rapport,
      l,
      h: (l * base.h) / base.l,
    });
    planifier();
  }

  let animation = 0;
  /** Transition douce vers une vue (interpolation logarithmique de l'échelle). */
  function animerVers(cible: Vue): void {
    cancelAnimationFrame(animation);
    const depart = { ...vue };
    const fin = contraindre(cible);
    if (mouvementReduit()) {
      vue = fin;
      planifier();
      return;
    }
    const debut = performance.now();
    const duree = 320;
    const pas = (maintenant: number) => {
      const t = Math.min(1, (maintenant - debut) / duree);
      const u = 1 - Math.pow(1 - t, 3);
      const l = Math.exp(Math.log(depart.l) + (Math.log(fin.l) - Math.log(depart.l)) * u);
      const cx = depart.x + depart.l / 2 + (fin.x + fin.l / 2 - (depart.x + depart.l / 2)) * u;
      const cy = depart.y + depart.h / 2 + (fin.y + fin.h / 2 - (depart.y + depart.h / 2)) * u;
      const h = (l * base.h) / base.l;
      vue = { x: cx - l / 2, y: cy - h / 2, l, h };
      dessiner();
      if (t < 1) animation = requestAnimationFrame(pas);
    };
    animation = requestAnimationFrame(pas);
  }

  const vueZoomee = (facteur: number): Vue => {
    const l = vue.l / facteur;
    const h = (l * base.h) / base.l;
    return { x: vue.x + vue.l / 2 - l / 2, y: vue.y + vue.h / 2 - h / 2, l, h };
  };
  const vueCible = (): Vue => {
    if (!cadreCible) return base;
    const [x, y, l, h] = cadreCible;
    const e = Math.min(base.l / l, base.h / h);
    const largeur = base.l / e;
    const hauteur = base.h / e;
    return { x: x + l / 2 - largeur / 2, y: y + h / 2 - hauteur / 2, l: largeur, h: hauteur };
  };

  // ------------------------------------------------------------------ Commandes

  const actions: Record<string, () => void> = {
    plus: () => animerVers(vueZoomee(2)),
    moins: () => animerVers(vueZoomee(0.5)),
    cible: () => animerVers(vueCible()),
    ensemble: () => animerVers(base),
  };
  for (const [nom, bouton] of boutons) {
    bouton.addEventListener("click", () => actions[nom ?? ""]?.(), { signal: arret });
  }

  let minuterieAide = 0;
  svg.addEventListener(
    "wheel",
    (evenement) => {
      if (!evenement.ctrlKey && !evenement.metaKey) {
        // La molette seule fait défiler la page ; indication discrète pour zoomer
        aide?.classList.add("carte-situation__aide--visible");
        clearTimeout(minuterieAide);
        minuterieAide = window.setTimeout(
          () => aide?.classList.remove("carte-situation__aide--visible"),
          1400,
        );
        return;
      }
      evenement.preventDefault();
      cancelAnimationFrame(animation);
      const point = versSvg(evenement.clientX, evenement.clientY);
      const vitesse = evenement.deltaMode === 1 ? 0.05 : 0.0025;
      zoomer(Math.exp(-evenement.deltaY * vitesse), point.x, point.y);
    },
    { passive: false, signal: arret },
  );

  svg.addEventListener(
    "dblclick",
    (evenement) => {
      const point = versSvg(evenement.clientX, evenement.clientY);
      const l = vue.l / 2;
      const h = (l * base.h) / base.l;
      animerVers({ x: point.x - l / 2, y: point.y - h / 2, l, h });
    },
    { signal: arret },
  );

  // Glisser (vue agrandie) et pincement à deux doigts
  const pointeurs = new Map<number, { x: number; y: number }>();
  svg.addEventListener(
    "pointerdown",
    (evenement) => {
      if (evenement.pointerType === "mouse" && evenement.button !== 0) return;
      pointeurs.set(evenement.pointerId, { x: evenement.clientX, y: evenement.clientY });
      svg.setPointerCapture(evenement.pointerId);
      cancelAnimationFrame(animation);
    },
    { signal: arret },
  );
  svg.addEventListener(
    "pointermove",
    (evenement) => {
      const precedent = pointeurs.get(evenement.pointerId);
      if (!precedent) return;
      const avant = [...pointeurs.values()].map((p) => ({ ...p }));
      pointeurs.set(evenement.pointerId, { x: evenement.clientX, y: evenement.clientY });
      const matrice = svg.getScreenCTM();
      if (!matrice) return;
      if (pointeurs.size === 1) {
        if (echelle() <= 1.01) return;
        figure.classList.add("carte-situation--glisse");
        vue = contraindre({
          ...vue,
          x: vue.x - (evenement.clientX - precedent.x) / matrice.a,
          y: vue.y - (evenement.clientY - precedent.y) / matrice.d,
        });
        planifier();
      } else if (pointeurs.size === 2) {
        const [a, b] = [...pointeurs.values()];
        const [a0, b0] = avant;
        const ecart = Math.hypot(a.x - b.x, a.y - b.y);
        const ecart0 = Math.hypot(a0.x - b0.x, a0.y - b0.y);
        const milieu = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
        const milieu0 = { x: (a0.x + b0.x) / 2, y: (a0.y + b0.y) / 2 };
        vue = contraindre({
          ...vue,
          x: vue.x - (milieu.x - milieu0.x) / matrice.a,
          y: vue.y - (milieu.y - milieu0.y) / matrice.d,
        });
        if (ecart0 > 0) {
          const point = versSvg(milieu.x, milieu.y);
          zoomer(ecart / ecart0, point.x, point.y);
        } else {
          planifier();
        }
      }
    },
    { signal: arret },
  );
  const relacher = (evenement: PointerEvent) => {
    pointeurs.delete(evenement.pointerId);
    if (pointeurs.size === 0) figure.classList.remove("carte-situation--glisse");
  };
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"] as const) {
    svg.addEventListener(type, relacher, { signal: arret });
  }

  // ------------------------------------------------------------------ Fond de plan IGN

  let groupe: SVGGElement | null = null;
  const tuiles = new Map<string, { image: SVGImageElement; niveau: string; prete: boolean }>();

  /** Zone réellement visible (le cadre peut être plus large que la vue sur téléphone). */
  function zoneVisible(): { vue: Vue; pixelsParUnite: number } {
    const boite = svg!.getBoundingClientRect();
    const pixelsParUnite = Math.min(boite.width / vue.l, boite.height / vue.h) || 1;
    const l = boite.width / pixelsParUnite;
    const h = boite.height / pixelsParUnite;
    return {
      vue: { x: vue.x + vue.l / 2 - l / 2, y: vue.y + vue.h / 2 - h / 2, l, h },
      pixelsParUnite,
    };
  }

  function retirerObsoletes(niveau: string, forcer: boolean): void {
    const courantes = [...tuiles.values()].filter((t) => t.niveau === niveau);
    if (!forcer && courantes.some((t) => !t.prete)) return;
    for (const [cle, tuile] of tuiles) {
      if (tuile.niveau !== niveau) {
        tuile.image.remove();
        tuiles.delete(cle);
      }
    }
  }

  function majTuiles(): void {
    if (fond === "contours" || !projection) {
      groupe?.remove();
      groupe = null;
      tuiles.clear();
      figure.classList.remove("carte-situation--fond-erreur");
      return;
    }
    const [k, tx, ty] = projection;
    if (!groupe) {
      groupe = document.createElementNS(ESPACE_SVG, "g");
      groupe.setAttribute("class", "situation-tuiles");
      groupe.setAttribute("aria-hidden", "true");
      svg!.insertBefore(groupe, svg!.firstChild);
    }
    const { vue: visible, pixelsParUnite } = zoneVisible();
    const densite = Math.min(window.devicePixelRatio || 1, 2);
    const couche = COUCHES[fond];
    const z = borner(
      Math.round(Math.log2((k * 2 * Math.PI * pixelsParUnite * densite) / TAILLE_TUILE)),
      0,
      couche.zoomMax,
    );
    const n = 2 ** z;
    const taille = (k * 2 * Math.PI) / n;
    const colonne = (x: number) => Math.floor((((x - tx) / k + Math.PI) / (2 * Math.PI)) * n);
    const ligne = (y: number) => Math.floor(((Math.PI - (ty - y) / k) / (2 * Math.PI)) * n);
    const niveau = `${fond}/${z}`;
    const voulues = new Set<string>();
    for (let c = Math.max(0, colonne(visible.x)); c <= Math.min(n - 1, colonne(visible.x + visible.l)); c++) {
      for (let r = Math.max(0, ligne(visible.y)); r <= Math.min(n - 1, ligne(visible.y + visible.h)); r++) {
        const cle = `${niveau}/${c}/${r}`;
        voulues.add(cle);
        if (tuiles.has(cle)) continue;
        const image = document.createElementNS(ESPACE_SVG, "image");
        // Léger recouvrement : pas de liseré entre deux tuiles voisines
        image.setAttribute("x", String(tx + k * ((c * 2 * Math.PI) / n - Math.PI)));
        image.setAttribute("y", String(ty - k * (Math.PI - (r * 2 * Math.PI) / n)));
        image.setAttribute("width", String(taille * 1.003));
        image.setAttribute("height", String(taille * 1.003));
        image.setAttribute("preserveAspectRatio", "none");
        const tuile = { image, niveau, prete: false };
        const terminer = (erreur: boolean) => {
          tuile.prete = true;
          if (erreur) image.remove();
          const courantes = [...tuiles.values()].filter((t) => t.niveau === niveau);
          const echecs = courantes.filter((t) => t.prete && !t.image.isConnected).length;
          figure.classList.toggle(
            "carte-situation--fond-erreur",
            courantes.length > 0 && echecs === courantes.length,
          );
          retirerObsoletes(niveau, false);
        };
        image.addEventListener("load", () => terminer(false), { once: true });
        image.addEventListener("error", () => terminer(true), { once: true });
        image.setAttribute("href", urlTuile(fond, z, c, r));
        tuiles.set(cle, tuile);
        groupe.append(image);
      }
    }
    // Tuiles du niveau courant sorties du cadre : retirées tout de suite
    for (const [cle, tuile] of tuiles) {
      if (tuile.niveau === niveau && !voulues.has(cle)) {
        tuile.image.remove();
        tuiles.delete(cle);
      }
    }
    retirerObsoletes(niveau, tuiles.size > TUILES_MAX);
  }

  function choisirFond(nouveau: Fond, memoriser: boolean): void {
    fond = projection ? nouveau : "contours";
    figure.dataset.fond = fond;
    figure.classList.toggle("carte-situation--fond", fond !== "contours");
    for (const choix of figure.querySelectorAll<HTMLInputElement>("input[name='fond-carte']")) {
      choix.checked = choix.value === fond;
    }
    if (memoriser) ecrireFond(fond);
    planifier();
  }

  for (const choix of figure.querySelectorAll<HTMLInputElement>("input[name='fond-carte']")) {
    choix.addEventListener("change", () => choisirFond(choix.value as Fond, true), {
      signal: arret,
    });
  }

  const observateur = new ResizeObserver(() => planifier());
  observateur.observe(svg);
  arret.addEventListener("abort", () => {
    observateur.disconnect();
    cancelAnimationFrame(animation);
    cancelAnimationFrame(rendu);
  });

  figure.classList.add("carte-situation--interactive");
  choisirFond(fond, false);
}

// Relancé après chaque transition de page (View Transitions)
document.addEventListener("astro:page-load", () => {
  const arret = new AbortController();
  for (const figure of document.querySelectorAll<HTMLElement>("[data-carte-situation]")) {
    brancher(figure, arret.signal);
  }
  document.addEventListener("astro:before-swap", () => arret.abort(), { once: true });
});
