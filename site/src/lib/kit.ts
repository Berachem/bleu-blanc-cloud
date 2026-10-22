// Kit « 5 questions à poser à votre prestataire » : partagé par le dossier et sa page
// imprimable (dont le PDF est généré par scripts/generer-kit-pdf.mjs).
export const QUESTIONS_KIT: { titre: string; texte: string }[] = [
  {
    titre: "Où sont nos données, et chez qui ?",
    texte: "Quel hébergeur, dans quel pays, et quelle est sa maison mère ? Est-elle soumise à une loi extraterritoriale (Cloud Act) ?",
  },
  {
    titre: "Sous quel délai appliquez-vous les correctifs critiques ?",
    texte: "Avez-vous appliqué ceux d'octobre 2026 pour PHP ? Qui nous prévient, et sous quel délai, en cas d'incident ?",
  },
  {
    titre: "Nos logiciels sont-ils encore maintenus ?",
    texte: "Version de PHP, du CMS et des extensions : y a-t-il des composants en fin de vie ?",
  },
  {
    titre: "Que se passe-t-il si votre service tombe ?",
    texte: "Où sont les sauvegardes, quand ont-elles été testées pour la dernière fois, et quel est le délai de reprise ?",
  },
  {
    titre: "Pouvons-nous partir facilement ?",
    texte: "Comment récupérer nos données et nos noms de domaine, dans quel format, à quel coût ?",
  },
];
export const BONUS_KIT =
  "Avez-vous des sites anciens ou oubliés (anciens événements, anciens mandats) ? Ils sont souvent les moins mis à jour.";
export const CHEMIN_PDF_KIT = "/dossiers/kit-5-questions-prestataire.pdf";
