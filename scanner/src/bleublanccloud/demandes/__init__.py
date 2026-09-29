"""Analyses sur demande : tickets « Analyser mon site » ouverts sur Codeberg.

Le serveur n'expose aucun port : il lit les tickets via l'API Codeberg, analyse le domaine
demandé (après validation stricte), publie la fiche et répond dans le ticket. Le contenu des
tickets est une donnée non fiable : seul le domaine validé est utilisé, jamais exécuté ni
interpolé dans une commande.
"""
