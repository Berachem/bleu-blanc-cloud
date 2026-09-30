"""Isolation des tests vis-à-vis de la configuration de la machine (.env du serveur)."""

from __future__ import annotations

import pytest

from bleublanccloud import configuration


def test_le_fichier_env_est_ignore_pendant_les_tests() -> None:
    assert configuration.Parametres.model_config["env_file"] is None
    parametres = configuration.obtenir_parametres()
    assert parametres.mistral_api_key is None
    assert parametres.codeberg_jeton is None


def test_une_variable_fixee_par_un_test_reste_prise_en_compte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMANDES_LIMITE_JOUR", "3")
    assert configuration.Parametres().demandes_limite_jour == 3
