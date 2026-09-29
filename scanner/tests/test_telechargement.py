"""Tests de la mise à jour des référentiels téléchargés (réponses enregistrées, respx)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx

from bleublanccloud.modeles import Fournisseur
from bleublanccloud.referentiels import telechargement as t
from bleublanccloud.sondes.ip import FICHIER_PLAGES, PlagesCloud
from tests.conftest import DOSSIER_FIXTURES

PLAGES = DOSSIER_FIXTURES / "plages"


def lire(nom: str) -> str:
    return (PLAGES / nom).read_text()


def test_analyser_aws() -> None:
    plages = t.analyser_aws(json.loads(lire("aws_ip-ranges.json")))
    assert len(plages) == 6
    assert plages[-1].prefixe == "2600:9000::/28"


def test_analyser_google_oracle_fastly_github() -> None:
    assert len(t.analyser_google(json.loads(lire("google_cloud.json")), "Google Cloud")) == 2
    assert t.analyser_oracle(json.loads(lire("oracle.json")))[0].service == "eu-paris-1"
    assert len(t.analyser_fastly(json.loads(lire("fastly.json")))) == 2
    assert t.analyser_github(json.loads(lire("github_meta.json")))[0].service == "pages"


def test_analyser_azure_garde_azurecloud_et_front_door() -> None:
    plages = t.analyser_azure(json.loads(lire("azure_servicetags.json")))
    assert {(p.prefixe, p.service) for p in plages} == {
        ("20.38.64.0/19", "AzureCloud"),
        ("13.107.246.0/24", "AzureCloud"),
        ("13.107.246.0/24", "AzureFrontDoor.Frontend"),
    }
    # À préfixe identique, le service précis (Front Door) l'emporte.
    index = PlagesCloud(plages)
    assert index.chercher("13.107.246.1").service == "AzureFrontDoor.Frontend"  # type: ignore[union-attr]


def test_extraire_url_azure() -> None:
    url = t.extraire_url_azure(lire("azure_page.html"))
    assert url is not None and url.endswith("ServiceTags_Public_20260922.json")
    assert t.extraire_url_azure("<html></html>") is None


def test_analyser_liste_texte_ignore_commentaires() -> None:
    plages = t.analyser_liste_texte("# commentaire\n1.2.3.0/24\n\n", "x")
    assert [p.prefixe for p in plages] == ["1.2.3.0/24"]


def simuler_sources(echec_cloudflare: bool = False) -> None:
    respx.get(t.URL_AWS).mock(return_value=httpx.Response(200, text=lire("aws_ip-ranges.json")))
    respx.get(t.URL_GOOGLE_CLOUD).mock(
        return_value=httpx.Response(200, text=lire("google_cloud.json"))
    )
    respx.get(t.URL_GOOGLE).mock(return_value=httpx.Response(200, json={"prefixes": []}))
    if echec_cloudflare:
        respx.get(t.URL_CLOUDFLARE_V4).mock(return_value=httpx.Response(500))
    else:
        respx.get(t.URL_CLOUDFLARE_V4).mock(
            return_value=httpx.Response(200, text=lire("cloudflare_ips-v4.txt"))
        )
    respx.get(t.URL_CLOUDFLARE_V6).mock(
        return_value=httpx.Response(200, text=lire("cloudflare_ips-v6.txt"))
    )
    respx.get(t.URL_ORACLE).mock(return_value=httpx.Response(200, text=lire("oracle.json")))
    respx.get(t.URL_AZURE_PAGE).mock(return_value=httpx.Response(200, text=lire("azure_page.html")))
    respx.get(url__regex=r"https://download\.microsoft\.com/.*").mock(
        return_value=httpx.Response(200, text=lire("azure_servicetags.json"))
    )
    respx.get(t.URL_FASTLY).mock(return_value=httpx.Response(200, text=lire("fastly.json")))
    respx.get(t.URL_GITHUB).mock(return_value=httpx.Response(200, text=lire("github_meta.json")))


@respx.mock
async def test_telecharger_plages_cloud(tmp_path: Path) -> None:
    simuler_sources()
    rapport = t.RapportMiseAJour()
    async with httpx.AsyncClient() as client:
        chemin = await t.telecharger_plages_cloud(client, tmp_path, rapport)
    assert rapport.erreurs == []
    assert rapport.plages_par_source["cloudflare"] == 22
    index = PlagesCloud.depuis_fichier(chemin)
    assert index.chercher("104.16.1.1").fournisseur_id == "cloudflare"  # type: ignore[union-attr]
    assert index.chercher("132.145.1.1").fournisseur_id == "oracle"  # type: ignore[union-attr]


@respx.mock
async def test_echec_partiel_conserve_les_anciennes_plages(tmp_path: Path) -> None:
    (tmp_path / FICHIER_PLAGES).write_text(
        json.dumps({"plages": [{"prefixe": "104.16.0.0/13", "fournisseur_id": "cloudflare"}]})
    )
    simuler_sources(echec_cloudflare=True)
    rapport = t.RapportMiseAJour()
    async with httpx.AsyncClient() as client:
        chemin = await t.telecharger_plages_cloud(client, tmp_path, rapport)
    assert any("cloudflare" in e for e in rapport.erreurs)
    index = PlagesCloud.depuis_fichier(chemin)
    assert index.chercher("104.16.1.1").fournisseur_id == "cloudflare"  # type: ignore[union-attr]


async def test_base_asn_sans_jeton(tmp_path: Path) -> None:
    rapport = t.RapportMiseAJour()
    async with httpx.AsyncClient() as client:
        await t.telecharger_base_asn(client, None, tmp_path / "asn.mmdb", rapport)
    assert rapport.base_asn is None
    assert "IPINFO_TOKEN" in rapport.erreurs[0]


@respx.mock
async def test_base_asn_avec_jeton(tmp_path: Path) -> None:
    respx.get(t.URL_IPINFO_LITE).mock(return_value=httpx.Response(200, content=b"MMDB"))
    rapport = t.RapportMiseAJour()
    async with httpx.AsyncClient() as client:
        await t.telecharger_base_asn(client, "jeton", tmp_path / "asn.mmdb", rapport)
    assert (tmp_path / "asn.mmdb").read_bytes() == b"MMDB"


@respx.mock
async def test_bootstrap_rdap(tmp_path: Path) -> None:
    respx.get(t.URL_BOOTSTRAP_RDAP).mock(
        return_value=httpx.Response(200, json={"services": [[["fr"], ["https://rdap.nic.fr/"]]]})
    )
    rapport = t.RapportMiseAJour()
    async with httpx.AsyncClient() as client:
        await t.telecharger_bootstrap_rdap(client, tmp_path, rapport)
    assert rapport.bootstrap_rdap
    assert (tmp_path / "rdap_dns.json").exists()


def test_comparer_secnumcloud() -> None:
    fournisseurs = [
        Fournisseur(
            id="ovhcloud", nom="OVHcloud", pays_siege="FR", soumis_cloud_act=False,
            propose_offre_secnumcloud=True, sources=["https://exemple.org/"],
        ),
        Fournisseur(
            id="scaleway", nom="Scaleway", pays_siege="FR", soumis_cloud_act=False,
            sources=["https://exemple.org/"],
        ),
    ]  # fmt: skip
    remarques = t.comparer_secnumcloud(
        "<p>Offres qualifiées : Scaleway, Outscale</p>", fournisseurs
    )
    assert any("Scaleway apparaît" in r for r in remarques)
    assert any("OVHcloud est marqué" in r for r in remarques)
