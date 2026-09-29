"""Tests des référentiels YAML."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bleublanccloud.configuration import DOSSIER_REFERENTIELS
from bleublanccloud.referentiels import ErreurReferentiel, Referentiels, charger_referentiels


def test_referentiels_du_paquet_valides(referentiels: Referentiels) -> None:
    assert len(referentiels.fournisseurs) >= 30


def test_chaque_fournisseur_a_une_source(referentiels: Referentiels) -> None:
    for fournisseur in referentiels.fournisseurs.values():
        assert fournisseur.sources, fournisseur.id


def test_les_faits_non_verifies_sont_signales(referentiels: Referentiels) -> None:
    # Tant qu'aucune relecture humaine n'a eu lieu, tout reste « a_verifier ».
    assert all(f.a_verifier for f in referentiels.fournisseurs.values())


def test_liste_initiale_du_cahier_des_charges(referentiels: Referentiels) -> None:
    attendus = {
        "ovhcloud", "scaleway", "outscale", "clever-cloud", "alwaysdata", "o2switch", "gandi",
        "ionos", "hetzner", "infomaniak", "brevo", "aws", "microsoft", "google", "cloudflare",
        "akamai", "fastly", "vercel", "netlify", "github", "wix", "squarespace", "automattic",
        "shopify", "mailchimp",
    }  # fmt: skip
    assert attendus <= set(referentiels.fournisseurs)


def test_motifs_regex_compilables(referentiels: Referentiels) -> None:
    import re

    for fournisseur in referentiels.fournisseurs.values():
        for motif in fournisseur.motifs_domaines + fournisseur.motifs_cdn:
            if motif.startswith("re:"):
                re.compile(motif[3:])
        for motif in fournisseur.en_tetes_origine.values():
            re.compile(motif)


def copier_referentiels(tmp_path: Path) -> Path:
    for nom in ("fournisseurs", "regles_detection", "alternatives", "retraits"):
        shutil.copy(DOSSIER_REFERENTIELS / f"{nom}.yaml", tmp_path / f"{nom}.yaml")
    return tmp_path


def test_doublon_detecte(tmp_path: Path) -> None:
    dossier = copier_referentiels(tmp_path)
    contenu = (dossier / "fournisseurs.yaml").read_text()
    debut = contenu.index("- id: ovhcloud")
    fin = contenu.index("- id: scaleway")
    (dossier / "fournisseurs.yaml").write_text(contenu + "\n" + contenu[debut:fin])
    with pytest.raises(ErreurReferentiel, match="double"):
        charger_referentiels(dossier)


def test_regle_avec_fournisseur_inconnu(tmp_path: Path) -> None:
    dossier = copier_referentiels(tmp_path)
    (dossier / "regles_detection.yaml").write_text(
        """
- id: regle-test
  nom: Test
  categorie: services_tiers
  type_service: test
  fournisseur_id: fournisseur-inexistant
  motifs: {domaines_scripts: ["exemple.org"]}
  exemples: [{type: script, valeur: "https://exemple.org/a.js"}]
"""
    )
    with pytest.raises(ErreurReferentiel, match="fournisseur inconnu"):
        charger_referentiels(dossier)


def test_regle_sans_fournisseur_exige_un_niveau(tmp_path: Path) -> None:
    dossier = copier_referentiels(tmp_path)
    (dossier / "regles_detection.yaml").write_text(
        """
- id: regle-test
  nom: Test
  categorie: services_tiers
  type_service: test
  motifs: {domaines_scripts: ["exemple.org"]}
  exemples: [{type: script, valeur: "https://exemple.org/a.js"}]
"""
    )
    with pytest.raises(ErreurReferentiel, match="niveau explicite"):
        charger_referentiels(dossier)


def test_fichier_qui_n_est_pas_une_liste(tmp_path: Path) -> None:
    dossier = copier_referentiels(tmp_path)
    (dossier / "retraits.yaml").write_text("cle: valeur\n")
    with pytest.raises(ErreurReferentiel, match="liste"):
        charger_referentiels(dossier)


def test_retraits_couvrent_les_sous_domaines(tmp_path: Path) -> None:
    dossier = copier_referentiels(tmp_path)
    (dossier / "retraits.yaml").write_text(
        '- domaine: Retire.fr\n  date_demande: "2026-01-01"\n  motif: test\n'
    )
    referentiels = charger_referentiels(dossier)
    assert referentiels.est_retire("retire.fr")
    assert referentiels.est_retire("www.retire.fr.")
    assert not referentiels.est_retire("pasretire.fr")
