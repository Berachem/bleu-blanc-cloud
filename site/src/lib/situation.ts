// Cartes de situation des fiches, calculées au build avec d3-geo : chaque page contient un
// petit SVG (aucune bibliothèque côté visiteur). Projection de Mercator (celle des tuiles
// web) : le fond de plan IGN, chargé seulement à la demande du visiteur, se superpose
// exactement aux tracés (voir lib/carte-situation.ts et ADR-0005).
//
// - commune : contour du département en neutre, commune remplie avec la couleur de sa note ;
// - département : sa silhouette dans sa région ;
// - région : sa silhouette dans la France (encart pour l'outre-mer).
//
// Contours : communes (geo.api.gouv.fr / IGN), départements et régions (IGN Admin Express
// via france-geojson), Licence Ouverte Etalab 2.0.
import {
  geoArea,
  geoBounds,
  geoCentroid,
  geoMercator,
  geoPath,
  type GeoPermissibleObjects,
  type GeoProjection,
  type GeoStream,
} from "d3-geo";
import type { Feature, FeatureCollection, Geometry, MultiPolygon, Polygon } from "geojson";
import { feature, merge, mesh } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import topologie from "../donnees-carte/situation.topo.json";
import { compacter } from "./traces";
import type { OrganisationExport } from "./types";

type ProprietesDepartement = { code: string; nom: string; region: string };
type ProprietesRegion = { code: string; nom: string };
type Objets = {
  departements: GeometryCollection<ProprietesDepartement>;
  regions: GeometryCollection<ProprietesRegion>;
};
type Entite<P> = Feature<Polygon | MultiPolygon, P>;

export const LARGEUR = 320;
export const HAUTEUR = 240;
const MARGE = 14;
/** Distance minimale (en pixels) entre deux points conservés d'un tracé : plus fine pour
 * une commune, plus large pour les vues étendues (région, France) très riches en détails. */
const SEUIL_PIXELS = 0.75;
const SEUIL_VUE_ETENDUE = 1.4;
/** Contour de la commune : conservé finement (au centième d'unité) pour rester net et
 * aligné sur le fond de plan quand le visiteur zoome. */
const SEUIL_DETAIL = 0.02;
const DECIMALES_DETAIL = 2;
/** Agrandissement maximal proposé au visiteur. */
export const ZOOM_MAX = 64;
const REGIONS_OUTRE_MER = new Set(["01", "02", "03", "04", "06"]);

/** d3-geo attend des anneaux extérieurs dans le sens horaire : un polygone décrit dans
 * l'autre sens couvrirait tout le globe sauf lui-même. */
function orienter<G extends Polygon | MultiPolygon>(geometrie: G): G {
  const polygones = geometrie.type === "Polygon" ? [geometrie.coordinates] : geometrie.coordinates;
  const corriges = polygones.map((anneaux) =>
    geoArea({ type: "Polygon", coordinates: anneaux }) > 2 * Math.PI
      ? anneaux.map((anneau) => [...anneau].reverse())
      : anneaux,
  );
  return (
    geometrie.type === "Polygon"
      ? { type: "Polygon", coordinates: corriges[0] }
      : { type: "MultiPolygon", coordinates: corriges }
  ) as G;
}

const topo = topologie as unknown as Topology<Objets>;
function entites<P extends { code: string }>(
  objet: GeometryCollection<P>,
): Map<string, Entite<P>> {
  const collection = feature(topo, objet) as unknown as FeatureCollection<Geometry, P>;
  return new Map(
    collection.features.map((f) => {
      const entite = { ...f, geometry: orienter(f.geometry as Polygon | MultiPolygon) };
      return [f.properties.code, entite];
    }),
  );
}
// Calculés une seule fois pour tout le build
const DEPARTEMENTS = entites(topo.objects.departements);
const REGIONS = entites(topo.objects.regions);
// France métropolitaine d'un seul tenant (fusion des régions : chaque côte tracée une fois)
const REGIONS_METROPOLE: Feature<MultiPolygon, null> = {
  type: "Feature",
  properties: null,
  geometry: orienter(
    merge(
      topo,
      topo.objects.regions.geometries.filter(
        (r) => !REGIONS_OUTRE_MER.has((r.properties as ProprietesRegion).code),
      ) as Parameters<typeof merge>[1],
    ),
  ),
};
const FRONTIERES_REGIONS = mesh(
  topo,
  topo.objects.regions,
  (a, b) => a !== b && !REGIONS_OUTRE_MER.has((a.properties as ProprietesRegion).code),
);

/** Projection de Mercator, commune aux tracés et aux tuiles du fond de plan (Web Mercator). */
function projectionPour(): GeoProjection {
  return geoMercator();
}

/** Générateur de tracés qui ignore les points distants de moins de `seuil` pixels : le
 * poids du SVG suit la taille affichée, pas la finesse des contours d'origine. */
function traceur(
  projection: GeoProjection,
  seuil = SEUIL_PIXELS,
  decimales = 1,
): (objet: GeoPermissibleObjects) => string {
  const allege = {
    stream(sortie: GeoStream): GeoStream {
      let tampon: [number, number][] = [];
      let dernier: [number, number] | null = null;
      let dansLigne = false;
      let dansPolygone = false;
      return projection.stream({
        point(x, y) {
          if (!dansLigne) return sortie.point(x, y);
          dernier = [x, y];
          const precedent = tampon[tampon.length - 1];
          if (!precedent || Math.hypot(x - precedent[0], y - precedent[1]) >= seuil) {
            tampon.push([x, y]);
          }
        },
        lineStart() {
          dansLigne = true;
          tampon = [];
          dernier = null;
        },
        lineEnd() {
          dansLigne = false;
          // Extrémité conservée : les frontières restent jointives
          if (dernier && tampon[tampon.length - 1] !== dernier) tampon.push(dernier);
          if (tampon.length < (dansPolygone ? 3 : 2)) return;
          sortie.lineStart();
          for (const [x, y] of tampon) sortie.point(x, y);
          sortie.lineEnd();
        },
        polygonStart() {
          dansPolygone = true;
          sortie.polygonStart();
        },
        polygonEnd() {
          dansPolygone = false;
          sortie.polygonEnd();
        },
        sphere() {
          sortie.sphere?.();
        },
      });
    },
  };
  const chemin = geoPath(allege).digits(decimales);
  return (objet) => compacter(chemin(objet) ?? "", decimales);
}

function cadrer(projection: GeoProjection, objet: GeoPermissibleObjects, zone: number[][]) {
  return projection.fitExtent(zone as [[number, number], [number, number]], objet);
}
const ZONE_PLEINE = [
  [MARGE, MARGE],
  [LARGEUR - MARGE, HAUTEUR - MARGE],
];

export interface Encart {
  x: number;
  y: number;
  largeur: number;
  hauteur: number;
}

export interface Situation {
  /** Surfaces neutres (département, région ou France). */
  fond: string;
  /** Frontières intérieures (départements d'une région, régions de France). */
  limites: string;
  /** Territoire de l'organisation, rempli avec la couleur de sa note. */
  cible: string;
  encart: Encart | null;
  /** Cercle de repérage autour d'un territoire trop petit pour être vu d'un coup d'œil. */
  repere: { cx: number; cy: number; r: number } | null;
  /** Texte alternatif, ex. « Localisation de Grenoble, Isère ». */
  libelle: string;
  /** Mention des sources des contours. */
  source: "communes" | "ign";
  /** Paramètres de la projection de Mercator (x = tx + k·λ, y = ty − k·ln tan(π/4 + φ/2)),
   * pour placer les tuiles du fond de plan ; null si la carte combine plusieurs projections
   * (encart d'outre-mer). */
  projection: { k: number; tx: number; ty: number } | null;
  /** Cadre (unités du SVG) qui montre le territoire de l'organisation en grand. */
  cadreCible: Encart;
  /** Centre et niveau de zoom pour ouvrir le territoire dans une carte en ligne. */
  lien: { lon: number; lat: number; zoom: number };
}

const arrondir = (valeur: number, decimales = 1) => {
  const facteur = 10 ** decimales;
  return Math.round(valeur * facteur) / facteur;
};

function parametres(projection: GeoProjection): Situation["projection"] {
  const [tx, ty] = projection.translate();
  return { k: arrondir(projection.scale(), 3), tx: arrondir(tx, 3), ty: arrondir(ty, 3) };
}

/** Cadre du territoire projeté, avec une marge, au format du SVG (4:3), sans dépasser
 * l'agrandissement maximal. */
function cadrerCible(projection: GeoProjection, objet: GeoPermissibleObjects): Encart {
  const [[x0, y0], [x1, y1]] = geoPath(projection).bounds(objet);
  const largeurMin = LARGEUR / ZOOM_MAX;
  let largeur = Math.max((x1 - x0) * 1.35, ((y1 - y0) * 1.35 * LARGEUR) / HAUTEUR, largeurMin);
  largeur = Math.min(largeur, LARGEUR);
  const hauteur = (largeur * HAUTEUR) / LARGEUR;
  return {
    x: arrondir((x0 + x1) / 2 - largeur / 2, 2),
    y: arrondir((y0 + y1) / 2 - hauteur / 2, 2),
    largeur: arrondir(largeur, 2),
    hauteur: arrondir(hauteur, 2),
  };
}

/** Centre géographique et niveau de zoom adapté à l'étendue du territoire. */
function lienCarte(objet: GeoPermissibleObjects): Situation["lien"] {
  const [lon, lat] = geoCentroid(objet);
  const [[ouest], [est]] = geoBounds(objet);
  const etendue = Math.max(est - ouest, 0.01);
  const zoom = Math.min(16, Math.max(5, Math.floor(Math.log2(360 / (etendue * 1.6)))));
  return { lon: arrondir(lon, 5), lat: arrondir(lat, 5), zoom };
}

/** Taille (en pixels) en dessous de laquelle un cercle de repérage entoure la commune. */
const TAILLE_REPERE = 14;

function reperer(projection: GeoProjection, objet: GeoPermissibleObjects): Situation["repere"] {
  const [[x0, y0], [x1, y1]] = geoPath(projection).bounds(objet);
  const taille = Math.max(x1 - x0, y1 - y0);
  if (!Number.isFinite(taille) || taille >= TAILLE_REPERE) return null;
  const arrondi = (v: number) => Math.round(v * 10) / 10;
  return { cx: arrondi((x0 + x1) / 2), cy: arrondi((y0 + y1) / 2), r: arrondi(taille / 2 + 7) };
}

function situationCommune(org: OrganisationExport): Situation | null {
  const departement = DEPARTEMENTS.get(org.departement ?? "");
  if (!departement || !org.contour?.length) return null;
  const commune: Entite<null> = {
    type: "Feature",
    properties: null,
    geometry: orienter({ type: "MultiPolygon", coordinates: org.contour }),
  };
  const projection = cadrer(projectionPour(), departement, ZONE_PLEINE);
  const tracer = traceur(projection);
  return {
    fond: tracer(departement),
    limites: "",
    cible: traceur(projection, SEUIL_DETAIL, DECIMALES_DETAIL)(commune),
    encart: null,
    repere: reperer(projection, commune),
    libelle: `Localisation de ${org.nom}, ${org.departement_nom ?? departement.properties.nom}`,
    source: "communes",
    projection: parametres(projection),
    cadreCible: cadrerCible(projection, commune),
    lien: lienCarte(commune),
  };
}

function situationDepartement(org: OrganisationExport): Situation | null {
  const departement = DEPARTEMENTS.get(org.departement ?? "");
  const region = departement ? REGIONS.get(departement.properties.region) : undefined;
  if (!departement || !region) return null;
  const outreMer = REGIONS_OUTRE_MER.has(region.properties.code);
  const projection = cadrer(projectionPour(), region, ZONE_PLEINE);
  const tracer = traceur(projection, SEUIL_VUE_ETENDUE);
  const code = region.properties.code;
  const limites = mesh(
    topo,
    topo.objects.departements,
    (a, b) =>
      a !== b &&
      (a.properties as ProprietesDepartement).region === code &&
      (b.properties as ProprietesDepartement).region === code,
  );
  return {
    fond: tracer(region),
    limites: tracer(limites),
    cible: tracer(departement),
    encart: null,
    repere: null,
    libelle: outreMer
      ? `Localisation du département ${departement.properties.nom}, région d'outre-mer`
      : `Localisation du département ${departement.properties.nom} dans la région ${region.properties.nom}`,
    source: "ign",
    projection: parametres(projection),
    cadreCible: cadrerCible(projection, departement),
    lien: lienCarte(departement),
  };
}

function situationRegion(org: OrganisationExport): Situation | null {
  const region = REGIONS.get(org.region ?? "");
  if (!region) return null;
  const libelle = `Localisation de la région ${region.properties.nom} en France`;
  if (!REGIONS_OUTRE_MER.has(region.properties.code)) {
    const projection = cadrer(projectionPour(), REGIONS_METROPOLE, ZONE_PLEINE);
    const tracer = traceur(projection, SEUIL_VUE_ETENDUE);
    return {
      fond: tracer(REGIONS_METROPOLE),
      limites: tracer(FRONTIERES_REGIONS),
      cible: tracer(region),
      encart: null,
      repere: null,
      libelle,
      source: "ign",
      projection: parametres(projection),
      cadreCible: cadrerCible(projection, region),
      lien: lienCarte(region),
    };
  }
  // Outre-mer : la France métropolitaine à droite, la région dans un encart à gauche
  const encart: Encart = { x: 8, y: HAUTEUR - 8 - 84, largeur: 96, hauteur: 84 };
  const metropole = traceur(
    cadrer(projectionPour(), REGIONS_METROPOLE, [
      [encart.x + encart.largeur + 8, MARGE],
      [LARGEUR - MARGE, HAUTEUR - MARGE],
    ]),
    SEUIL_VUE_ETENDUE,
  );
  const zoneEncart = [
    [encart.x + 8, encart.y + 8],
    [encart.x + encart.largeur - 8, encart.y + encart.hauteur - 8],
  ];
  return {
    fond: metropole(REGIONS_METROPOLE),
    limites: metropole(FRONTIERES_REGIONS),
    cible: traceur(cadrer(projectionPour(), region, zoneEncart))(region),
    encart,
    repere: null,
    libelle,
    source: "ign",
    projection: null,
    cadreCible: { x: encart.x, y: encart.y, largeur: encart.largeur, hauteur: encart.hauteur },
    lien: lienCarte(region),
  };
}

/** Carte de situation d'une organisation, ou null (fiche sur demande, contour manquant). */
export function carteSituation(org: OrganisationExport): Situation | null {
  switch (org.type) {
    case "commune":
      return situationCommune(org);
    case "departement":
      return situationDepartement(org);
    case "region":
      return situationRegion(org);
    case "autre":
      return org.departement ? situationDepartement(org) : situationRegion(org);
    default:
      return null;
  }
}
