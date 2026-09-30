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


def test_domaine_et_user_agent_par_defaut() -> None:
    parametres = configuration.Parametres()
    assert parametres.domaine_site == "bleublanccloud.fr"
    assert parametres.url_site == "https://bleublanccloud.fr"
    assert parametres.user_agent == (
        "BleuBlancCloudBot/1.0 (+https://bleublanccloud.fr/methodologie)"
    )


def test_le_user_agent_suit_le_domaine_du_site(monkeypatch: pytest.MonkeyPatch) -> None:
    # Transition : le serveur garde l'ancien domaine tant que son .env n'est pas modifié
    monkeypatch.setenv("DOMAINE_SITE", " Bleublanccloud.Berachem.Dev. ")
    parametres = configuration.Parametres()
    assert parametres.domaine_site == "bleublanccloud.berachem.dev"
    assert parametres.user_agent.endswith("(+https://bleublanccloud.berachem.dev/methodologie)")


def test_un_user_agent_explicite_est_conserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USER_AGENT", "BleuBlancCloudBot/1.0 (+https://exemple.org/robot)")
    assert configuration.Parametres().user_agent == (
        "BleuBlancCloudBot/1.0 (+https://exemple.org/robot)"
    )


@pytest.mark.parametrize(
    "valeur", ["https://bleublanccloud.fr", "bleublanccloud.fr/chemin", "localhost", ""]
)
def test_domaine_site_invalide_refuse(monkeypatch: pytest.MonkeyPatch, valeur: str) -> None:
    monkeypatch.setenv("DOMAINE_SITE", valeur)
    if not valeur:
        # Valeur vide : ignorée (env_ignore_empty), le domaine par défaut s'applique
        assert configuration.Parametres().domaine_site == "bleublanccloud.fr"
        return
    with pytest.raises(ValueError, match="DOMAINE_SITE invalide"):
        configuration.Parametres()
