"""Tests de la sonde IP : plages publiées, base ASN locale, repli RIPEstat."""

from __future__ import annotations

import httpx
import pytest
import respx

from bleublanccloud.sondes.ip import (
    URL_RIPESTAT,
    PlageCloud,
    PlagesCloud,
    ResolveurAsn,
    _lire_mmdb,
)
from tests.conftest import LecteurMmdbFactice, plages_de_test


def test_plages_trouve_le_prefixe_le_plus_specifique() -> None:
    plages = PlagesCloud(
        [
            PlageCloud(prefixe="10.0.0.0/8", fournisseur_id="large"),
            PlageCloud(prefixe="10.1.0.0/16", fournisseur_id="precis"),
        ]
    )
    assert plages.chercher("10.1.2.3").fournisseur_id == "precis"  # type: ignore[union-attr]
    assert plages.chercher("10.9.2.3").fournisseur_id == "large"  # type: ignore[union-attr]
    assert plages.chercher("192.0.2.1") is None
    assert plages.chercher("pas-une-ip") is None


def test_plages_service_precis_prefere_au_service_generique() -> None:
    plages = plages_de_test()
    cloudfront = plages.chercher("13.32.10.1")
    assert cloudfront is not None
    assert (cloudfront.fournisseur_id, cloudfront.service) == ("aws", "CLOUDFRONT")
    ec2 = plages.chercher("52.95.1.1")
    assert ec2 is not None and ec2.service == "EC2"


def test_plages_ipv6() -> None:
    plages = plages_de_test()
    assert plages.chercher("2606:4700::1").fournisseur_id == "cloudflare"  # type: ignore[union-attr]
    assert plages.chercher("2600:9000::1").service == "CLOUDFRONT"  # type: ignore[union-attr]


def test_plages_ignore_les_prefixes_invalides() -> None:
    plages = PlagesCloud([PlageCloud(prefixe="n'importe quoi", fournisseur_id="x")])
    assert len(plages) == 0


def test_plages_depuis_fichier_absent(tmp_path) -> None:
    assert len(PlagesCloud.depuis_fichier(tmp_path / "absent.json")) == 0


@pytest.mark.parametrize(
    ("enregistrement", "attendu"),
    [
        ({"asn": "AS16276", "as_name": "OVH SAS", "country_code": "FR"}, (16276, "OVH SAS", "FR")),
        (
            {"autonomous_system_number": 13335, "autonomous_system_organization": "CLOUDFLARENET"},
            (13335, "CLOUDFLARENET", None),
        ),
        ({"asn": "inconnu"}, (None, None, None)),
    ],
)
def test_lire_mmdb_formats_ipinfo_et_geolite(enregistrement, attendu) -> None:
    assert _lire_mmdb(enregistrement) == attendu


async def test_resolveur_combine_plages_et_base_locale() -> None:
    resolveur = ResolveurAsn(
        plages_de_test(), lecteur_mmdb=LecteurMmdbFactice(), utiliser_ripestat=False
    )
    info = await resolveur.informer("104.16.1.1")
    assert info.plage_cloud == "cloudflare"
    assert info.asn == 13335
    assert info.source == "plages_publiees"
    info_ovh = await resolveur.informer("51.91.10.20")
    assert (info_ovh.asn, info_ovh.pays, info_ovh.source) == (16276, "FR", "base_locale")


@respx.mock
async def test_repli_ripestat_avec_cache() -> None:
    route_reseau = respx.get(f"{URL_RIPESTAT}/network-info/data.json").mock(
        return_value=httpx.Response(
            200, json={"data": {"asns": ["16276"], "prefix": "51.91.0.0/16"}}
        )
    )
    route_as = respx.get(f"{URL_RIPESTAT}/as-overview/data.json").mock(
        return_value=httpx.Response(200, json={"data": {"holder": "OVH, FR"}})
    )
    async with httpx.AsyncClient() as client:
        resolveur = ResolveurAsn(PlagesCloud([]), client_http=client)
        info = await resolveur.informer("51.91.0.1")
        await resolveur.informer("51.91.0.1")
    assert (info.asn, info.nom_as, info.pays, info.prefixe) == (
        16276,
        "OVH, FR",
        "FR",
        "51.91.0.0/16",
    )
    assert info.source == "ripestat"
    assert route_reseau.call_count == 1
    assert route_as.call_count == 1


@respx.mock
async def test_ripestat_en_erreur_ne_bloque_pas_le_scan() -> None:
    respx.get(f"{URL_RIPESTAT}/network-info/data.json").mock(return_value=httpx.Response(503))
    async with httpx.AsyncClient() as client:
        info = await ResolveurAsn(PlagesCloud([]), client_http=client).informer("192.0.2.1")
    assert info.asn is None


@respx.mock
async def test_ripestat_sans_asn() -> None:
    respx.get(f"{URL_RIPESTAT}/network-info/data.json").mock(
        return_value=httpx.Response(200, json={"data": {"asns": []}})
    )
    async with httpx.AsyncClient() as client:
        info = await ResolveurAsn(PlagesCloud([]), client_http=client).informer("192.0.2.2")
    assert info.asn is None
