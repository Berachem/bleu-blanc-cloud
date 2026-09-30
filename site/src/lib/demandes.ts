// Liens « Analyser mon site » vers un nouveau ticket Codeberg.
import { DEMANDES, SITE } from "../config";

const NOUVEAU_TICKET = `${DEMANDES.forge}/${DEMANDES.depot}/issues/new`;

// Formulaire Forgejo (.forgejo/issue_template/analyse.yaml) : champ obligatoire, case
// obligatoire et étiquette « analyse » appliquée automatiquement.
export const URL_DEMANDE_FORMULAIRE = `${NOUVEAU_TICKET}?template=${encodeURIComponent(DEMANDES.modele)}`;

// Repli si le formulaire ne s'affiche pas : ticket pré-rempli, reconnu par son titre.
const CORPS_SIMPLE = [
  "Domaine à analyser : ",
  "",
  "- [ ] Je suis responsable de ce site, ou il s'agit du site d'un organisme public",
  "",
  "Indiquez le nom de domaine seul (ex. : mairie-exemple.fr) et cochez la case en remplaçant [ ] par [x].",
  "",
  "Rappel : analyse strictement passive (DNS et pages publiques, aucun test d'intrusion), résultat public (fiche publiée sur le site et réponse dans ce ticket), délai habituel inférieur à une heure.",
].join("\n");

export const URL_DEMANDE_SIMPLE = `${NOUVEAU_TICKET}?title=${encodeURIComponent("[Analyse] ")}&body=${encodeURIComponent(CORPS_SIMPLE)}`;

// Demande par e-mail (sans compte Codeberg) : traitée à la main avec
// « bbcloud demandes analyser <domaine> », qui applique les mêmes contrôles qu'un ticket.
const CORPS_EMAIL = [
  "Bonjour,",
  "",
  "Je souhaite faire analyser ce site :",
  "Domaine : ",
  "",
  "Je confirme qu'il s'agit de mon site ou du site d'un organisme public.",
  "",
  "Merci !",
].join("\n");

export const URL_DEMANDE_EMAIL = `mailto:${SITE.contact}?subject=${encodeURIComponent("Bleu Blanc Cloud — demande d'analyse")}&body=${encodeURIComponent(CORPS_EMAIL)}`;
