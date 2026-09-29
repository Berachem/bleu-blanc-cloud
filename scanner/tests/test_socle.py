"""Tests du socle : version, configuration et CLI."""

from typer.testing import CliRunner

from bleublanccloud import __version__
from bleublanccloud.cli import app
from bleublanccloud.configuration import Parametres


def test_version_cli() -> None:
    resultat = CliRunner().invoke(app, ["version"])
    assert resultat.exit_code == 0
    assert __version__ in resultat.output


def test_parametres_par_defaut(monkeypatch) -> None:
    monkeypatch.delenv("CONCURRENCE_MAX", raising=False)
    parametres = Parametres(_env_file=None)
    assert parametres.concurrence_max == 20
    assert parametres.delai_expiration_s == 10
    assert parametres.user_agent.startswith("BleuBlancCloudBot/1.0")
    assert parametres.base_sqlite.is_absolute()
