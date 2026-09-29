"""Configuration du scanner, lue depuis les variables d'environnement et le fichier `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _trouver_racine_projet() -> Path:
    """Retourne la racine du dépôt (dossier qui contient `scanner/`), sinon le dossier courant."""
    candidat = Path(__file__).resolve().parents[3]
    if (candidat / "scanner").is_dir():
        return candidat
    return Path.cwd()


RACINE_PROJET = _trouver_racine_projet()
DOSSIER_REFERENTIELS = Path(__file__).resolve().parent / "referentiels"
DOSSIER_TELECHARGEMENTS = DOSSIER_REFERENTIELS / "telechargements"

USER_AGENT_PAR_DEFAUT = "BleuBlancCloudBot/1.0 (+https://bleublanccloud.berachem.dev/methodologie)"


class Parametres(BaseSettings):
    """Paramètres du projet. Les chemins relatifs sont résolus depuis la racine du dépôt."""

    model_config = SettingsConfigDict(
        env_file=(RACINE_PROJET / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # « CODEBERG_JETON= » (valeur vide, comme dans .env.example) vaut « non renseigné »
        env_ignore_empty=True,
    )

    mistral_api_key: SecretStr | None = None
    mistral_modele: str = "mistral-small-latest"
    mistral_serveur: str = "eu"
    mistral_prix_entree_par_m: float = 0.1
    mistral_prix_sortie_par_m: float = 0.3

    chemin_base_asn: Path = Path("scanner/src/bleublanccloud/referentiels/telechargements/asn.mmdb")
    ipinfo_token: SecretStr | None = None
    chemin_base_sqlite: Path = Path("donnees/bleublanccloud.db")

    concurrence_max: int = Field(default=20, ge=1, le=200)
    delai_expiration_s: float = Field(default=10.0, gt=0, le=60)
    user_agent: str = USER_AGENT_PAR_DEFAUT
    # Politesse : pages HTML maximum par site et intervalle minimal entre deux requêtes
    pages_max_par_site: int = Field(default=5, ge=1, le=5)
    intervalle_par_domaine_s: float = Field(default=1.0, ge=1.0)
    relances_max: int = Field(default=2, ge=0, le=2)

    depot_pages: str | None = None
    domaine_site: str = "bleublanccloud.berachem.dev"
    # Verrou partagé par la campagne, la mise à jour automatique et les demandes (flock)
    chemin_verrou: Path = Path("donnees/bbcloud.verrou")

    # Analyses sur demande (tickets Codeberg). Jeton aux droits minimaux : « write:issue »
    # limité au seul dépôt des demandes. Jamais écrit dans les journaux.
    codeberg_jeton: SecretStr | None = None
    codeberg_api: str = "https://codeberg.org/api/v1"
    depot_demandes: str = "berachem/bleublanccloud-pages"
    demandes_limite_jour: int = Field(default=10, ge=0, le=1000)
    demandes_limite_compte: int = Field(default=1, ge=0, le=100)

    def chemin_absolu(self, chemin: Path) -> Path:
        """Résout un chemin relatif depuis la racine du dépôt."""
        return chemin if chemin.is_absolute() else RACINE_PROJET / chemin

    @property
    def base_asn(self) -> Path:
        return self.chemin_absolu(self.chemin_base_asn)

    @property
    def base_sqlite(self) -> Path:
        return self.chemin_absolu(self.chemin_base_sqlite)

    @property
    def verrou(self) -> Path:
        return self.chemin_absolu(self.chemin_verrou)

    @property
    def url_site(self) -> str:
        return f"https://{self.domaine_site}"


@lru_cache(maxsize=1)
def obtenir_parametres() -> Parametres:
    """Retourne les paramètres (mis en cache pour la durée du processus)."""
    return Parametres()
