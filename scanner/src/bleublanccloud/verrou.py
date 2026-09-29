"""Verrou exclusif (flock) partagé avec les scripts de déploiement.

Même fichier et même mécanisme que `flock` dans deploy/*.sh : la campagne hebdomadaire, la
mise à jour automatique et le traitement des demandes ne tournent jamais en même temps.
"""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def verrou_exclusif(chemin: Path) -> Iterator[bool]:
    """Tente de prendre le verrou sans attendre ; produit False s'il est déjà pris."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("a") as fichier:
        try:
            fcntl.flock(fichier.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fichier.fileno(), fcntl.LOCK_UN)
