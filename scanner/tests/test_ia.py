"""Tests des rapports IA : validation, rejet des alternatives inventées, cache, budget."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from bleublanccloud import configuration
from bleublanccloud.analyse.score import VERSION_METHODO, calculer_score
from bleublanccloud.cli import app
from bleublanccloud.ia.client_mistral import (
    ClientMistral,
    DemandeRapport,
    ErreurIA,
    GenerateurRapports,
    RapportInvalide,
    ReponseChat,
    compter_phrases,
    construire_messages,
    empreinte_constats,
    estimer,
    valider_rapport,
)
from bleublanccloud.ia.generation import appliquer_cache, generer_rapports, planifier
from bleublanccloud.ia.invites import (
    CONSIGNES_SYSTEME,
    VERSION_INVITE,
    construire_message,
    masquer_donnees_personnelles,
)
from bleublanccloud.modeles import Constat, Organisation, ResultatScan
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.stockage.base import Base


def rapport_json(alternative_id: str | None = "matomo-auto-heberge", phrases: int = 2) -> str:
    return json.dumps(
        {
            "resume_decideur": " ".join(["Phrase de synthèse."] * phrases),
            "points_forts": ["Hébergement européen."],
            "risques": [
                {
                    "titre": "Mesure d'audience",
                    "explication": "Données chez Google.",
                    "gravite": "moyenne",
                }
            ],
            "plan_migration": [
                {"ordre": 2, "action": "Étape deux.", "alternative_id": None, "effort": "moyen"},
                {
                    "ordre": 1,
                    "action": "Remplacer GA.",
                    "alternative_id": alternative_id,
                    "effort": "faible",
                },
            ],
        },
        ensure_ascii=False,
    )


class ClientFactice:
    """Client de chat qui renvoie des réponses préparées et enregistre les appels."""

    def __init__(self, reponses: list[str | Exception]) -> None:
        self.reponses = reponses
        self.appels: list[list[dict[str, str]]] = []

    async def completer(
        self, messages: list[dict[str, str]], modele: str, temperature: float
    ) -> ReponseChat:
        self.appels.append(messages)
        reponse = self.reponses.pop(0)
        if isinstance(reponse, Exception):
            raise reponse
        return ReponseChat(contenu=reponse, jetons_entree=1000, jetons_sortie=300)


def constats() -> list[Constat]:
    return [
        Constat(sonde="ip", categorie="hebergement", cle="hebergeur", valeur="51.91.0.1",
                fournisseur_id="ovhcloud", niveau="A"),
        Constat(sonde="http", categorie="mesure_audience", cle="cookie", valeur="Google Analytics",
                fournisseur_id="google", niveau="D",
                preuve={"regle": "google-analytics", "type_service": "analytique"}),
        Constat(sonde="dns", categorie="informatif", cle="dmarc",
                valeur="v=DMARC1; p=none; rua=mailto:jean.dupont@exempleville.fr"),
    ]  # fmt: skip


def demande(referentiels: Referentiels) -> DemandeRapport:
    liste = constats()
    return DemandeRapport(
        nom_organisation="Exempleville",
        type_organisation="commune",
        score=calculer_score(liste, ["dns", "http"]),
        constats=liste,
        alternatives=[referentiels.alternatives["matomo-auto-heberge"]],
    )


def generateur(referentiels: Referentiels, client: ClientFactice) -> GenerateurRapports:
    return GenerateurRapports(
        client, "mistral-small-latest", referentiels.fournisseurs, referentiels.alternatives
    )


# --------------------------------------------------------------------------- #
# Consignes et données envoyées
# --------------------------------------------------------------------------- #


def test_masquage_des_donnees_personnelles() -> None:
    texte = "rua=mailto:jean.dupont@exempleville.fr; tél. 05 56 00 00 00 ou +33 5 56 00 00 00"
    masque = masquer_donnees_personnelles(texte)
    assert "@" not in masque and "56 00" not in masque
    assert "[adresse masquée]" in masque and "[numéro masqué]" in masque


def test_message_sans_donnee_personnelle(referentiels: Referentiels) -> None:
    d = demande(referentiels)
    message = construire_message(
        d.nom_organisation, d.type_organisation, d.score, d.constats, referentiels.fournisseurs,
        d.alternatives,
    )  # fmt: skip
    assert "jean.dupont" not in message and "@" not in message
    donnees = json.loads(message.split("\n\n", 1)[1])
    assert donnees["alternatives_autorisees"][0]["id"] == "matomo-auto-heberge"
    assert donnees["score"]["note"] == d.score.note
    google = next(
        c for c in donnees["constats"] if c.get("fournisseur") == "Google (Google Cloud, Workspace)"
    )
    assert google["soumis_cloud_act"] is True


def test_consignes_imposent_les_regles() -> None:
    assert "JAMAIS" in CONSIGNES_SYSTEME and "alternative_id" in CONSIGNES_SYSTEME
    assert VERSION_INVITE == "1.0"


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def test_rapport_valide_et_trie(referentiels: Referentiels) -> None:
    rapport = valider_rapport(rapport_json(), referentiels.alternatives)
    assert [e.ordre for e in rapport.plan_migration] == [1, 2]


def test_bloc_markdown_accepte(referentiels: Referentiels) -> None:
    assert valider_rapport(f"```json\n{rapport_json()}\n```", referentiels.alternatives)


def test_alternative_inventee_rejetee(referentiels: Referentiels) -> None:
    with pytest.raises(RapportInvalide, match=r"alternative.*inconnue.*solution-imaginaire"):
        valider_rapport(rapport_json("solution-imaginaire"), referentiels.alternatives)


@pytest.mark.parametrize(
    "texte", ["pas du json", json.dumps({"resume_decideur": "x"}), rapport_json(phrases=7)]
)
def test_reponses_non_conformes(texte: str, referentiels: Referentiels) -> None:
    with pytest.raises(RapportInvalide):
        valider_rapport(texte, referentiels.alternatives)


def test_compter_phrases() -> None:
    assert compter_phrases("Une. Deux ! Trois ? Quatre…") == 4


# --------------------------------------------------------------------------- #
# Génération (une seule nouvelle tentative)
# --------------------------------------------------------------------------- #


async def test_generation_directe(referentiels: Referentiels) -> None:
    client = ClientFactice([rapport_json()])
    resultat = await generateur(referentiels, client).generer(demande(referentiels))
    assert resultat.rapport is not None and resultat.erreur is None
    assert resultat.appels == 1 and resultat.jetons_entree == 1000
    assert client.appels[0][0]["role"] == "system"


async def test_alternative_inventee_regeneree_une_fois(referentiels: Referentiels) -> None:
    client = ClientFactice([rapport_json("inventee"), rapport_json()])
    resultat = await generateur(referentiels, client).generer(demande(referentiels))
    assert resultat.rapport is not None
    assert resultat.appels == 2
    assert "inventee" in client.appels[1][-1]["content"]


async def test_deux_rejets_marquent_le_rapport_en_erreur(referentiels: Referentiels) -> None:
    client = ClientFactice(
        [rapport_json("inventee"), rapport_json("encore-inventee"), rapport_json()]
    )
    resultat = await generateur(referentiels, client).generer(demande(referentiels))
    assert resultat.rapport is None
    assert resultat.erreur is not None and "encore-inventee" in resultat.erreur
    assert resultat.appels == 2  # jamais plus d'une nouvelle tentative


async def test_erreur_api(referentiels: Referentiels) -> None:
    client = ClientFactice([ErreurIA("quota dépassé")])
    resultat = await generateur(referentiels, client).generer(demande(referentiels))
    assert resultat.rapport is None and resultat.erreur == "quota dépassé"


# --------------------------------------------------------------------------- #
# Adaptateur du SDK Mistral
# --------------------------------------------------------------------------- #


class SdkFactice:
    def __init__(self, reponse: Any = None, erreur: Exception | None = None) -> None:
        self.arguments: dict[str, Any] = {}

        async def complete_async(**arguments: Any) -> Any:
            self.arguments = arguments
            if erreur:
                raise erreur
            return reponse

        self.chat = SimpleNamespace(complete_async=complete_async)


def reponse_sdk(contenu: Any) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=contenu))],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=34),
    )


async def test_client_mistral() -> None:
    sdk = SdkFactice(reponse_sdk('{"a": 1}'))
    reponse = await ClientMistral("cle", sdk=sdk).completer(
        [{"role": "user", "content": "x"}], "m", 0.2
    )
    assert (reponse.contenu, reponse.jetons_entree, reponse.jetons_sortie) == ('{"a": 1}', 12, 34)
    assert sdk.arguments["temperature"] == 0.2
    assert sdk.arguments["response_format"] == {"type": "json_object"}


async def test_client_mistral_contenu_en_morceaux_et_erreurs() -> None:
    morceaux = [SimpleNamespace(text='{"a"'), SimpleNamespace(text=": 1}")]
    reponse = await ClientMistral("cle", sdk=SdkFactice(reponse_sdk(morceaux))).completer(
        [], "m", 0.2
    )
    assert reponse.contenu == '{"a": 1}'
    with pytest.raises(ErreurIA, match="Timeout"):
        await ClientMistral("cle", sdk=SdkFactice(erreur=TimeoutError("Timeout"))).completer(
            [], "m", 0.2
        )
    vide = SimpleNamespace(choices=[], usage=None)
    with pytest.raises(ErreurIA, match="vide"):
        await ClientMistral("cle", sdk=SdkFactice(vide)).completer([], "m", 0.2)


def test_client_mistral_reel_serveur_europeen() -> None:
    client = ClientMistral("cle-factice", serveur="eu")
    assert client._sdk.sdk_configuration.get_server_details()[0] == "https://api.eu.mistral.ai"


# --------------------------------------------------------------------------- #
# Cache, planification et budget
# --------------------------------------------------------------------------- #


def test_empreinte() -> None:
    a = empreinte_constats(constats(), "1.0", "m")
    assert a == empreinte_constats(constats(), "1.0", "m")
    assert a != empreinte_constats(constats(), "1.1", "m")
    assert a != empreinte_constats(constats(), "1.0", "autre-modele")
    assert a != empreinte_constats(constats()[:1], "1.0", "m")


def test_estimer() -> None:
    messages = [[{"role": "user", "content": "x" * 3500}]] * 2
    estimation = estimer(messages, prix_entree_par_m=0.1, prix_sortie_par_m=0.3)
    assert estimation.appels == 2
    assert estimation.jetons_entree == 2002
    assert estimation.cout == pytest.approx((2002 * 0.1 + 1800 * 0.3) / 1e6)
    assert "2 appel(s)" in estimation.en_texte()


def enregistrer(base: Base, slug: str, jour: int) -> int:
    org_id = base.enregistrer_organisation(
        Organisation(
            slug=slug, nom=slug.title(), type="commune", site_web=f"https://{slug}.fr", source="t"
        )
    )
    liste = constats()
    date = datetime(2026, 9, jour, tzinfo=UTC)
    resultat = ResultatScan(
        domaine=f"{slug}.fr", debut=date, fin=date, statut="termine",
        sondes_reussies=["dns", "http"], constats=liste,
    )  # fmt: skip
    return base.enregistrer_scan(org_id, resultat, calculer_score(liste), VERSION_METHODO)


async def test_cache_evite_tout_nouvel_appel(referentiels: Referentiels) -> None:
    modele = "mistral-small-latest"
    with Base(":memory:") as base:
        enregistrer(base, "exempleville", 1)
        plan = planifier(base, referentiels, modele)
        assert len(plan.a_generer) == 1
        client = ClientFactice([rapport_json()])
        bilan = await generer_rapports(base, plan.a_generer, generateur(referentiels, client))
        assert bilan.generes == 1 and bilan.appels == 1

        # Même scan : déjà à jour
        assert planifier(base, referentiels, modele).deja_a_jour == 1

        # Nouveau scan aux constats identiques : réutilisation du cache, aucun appel
        enregistrer(base, "exempleville", 8)
        plan = planifier(base, referentiels, modele)
        assert (len(plan.a_generer), len(plan.depuis_cache)) == (0, 1)
        assert appliquer_cache(base, plan, modele) == 1
        assert planifier(base, referentiels, modele).deja_a_jour == 1
        assert len(client.appels) == 1

        # Changement de modèle : nouvelle génération nécessaire
        assert len(planifier(base, referentiels, "mistral-large-latest").a_generer) == 1


async def test_rapport_en_erreur_enregistre(referentiels: Referentiels) -> None:
    with Base(":memory:") as base:
        scan_id = enregistrer(base, "exempleville", 1)
        plan = planifier(base, referentiels, "m")
        client = ClientFactice([rapport_json("x"), rapport_json("y")])
        bilan = await generer_rapports(base, plan.a_generer, generateur(referentiels, client))
        assert bilan.generes == 0 and len(bilan.en_erreur) == 1
        assert base.rapport_du_scan(scan_id) is None
        statut = base.connexion.execute("SELECT statut FROM rapports_ia").fetchone()[0]
        assert statut == "erreur"


def test_messages_construits(referentiels: Referentiels) -> None:
    messages = construire_messages(demande(referentiels), referentiels.fournisseurs)
    assert [m["role"] for m in messages] == ["system", "user"]


def test_cli_dry_run_estime_le_cout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chemin = tmp_path / "base.db"
    monkeypatch.setenv("CHEMIN_BASE_SQLITE", str(chemin))
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    configuration.obtenir_parametres.cache_clear()
    with Base(chemin) as base:
        enregistrer(base, "exempleville", 1)
    lanceur = CliRunner()
    resultat = lanceur.invoke(app, ["rapports", "generer", "--dry-run"])
    assert resultat.exit_code == 0, resultat.output
    assert "1 à générer" in resultat.output and "coût estimé" in resultat.output
    assert "aucun appel" in resultat.output
    sans_cle = lanceur.invoke(app, ["rapports", "generer", "--oui"])
    assert sans_cle.exit_code == 1
    configuration.obtenir_parametres.cache_clear()
