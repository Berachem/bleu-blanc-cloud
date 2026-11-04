// Données des badges au build, à partir de l'index exporté.
import type { EntreeIndex } from "../types/donnees";
import type { DonneesBadge } from "./badge";

export const donneesBadge = (entree: EntreeIndex): DonneesBadge => ({
  nom: entree.nom,
  note: entree.note,
  score: entree.score,
  dateScan: entree.date_scan,
  provisoire: entree.note_provisoire,
  domaine: entree.domaine,
});

/** Le badge n'est proposé qu'aux organisations qui se distinguent : note A non provisoire. */
export const badgePropose = (entree: Pick<EntreeIndex, "note" | "note_provisoire">): boolean =>
  entree.note === "A" && !entree.note_provisoire;
