"""Schémas JSON du contrat de données, générés depuis les modèles pydantic.

Le site en dérive ses types TypeScript (site/scripts/generer-types.mjs).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from bleublanccloud.modeles import (
    AlternativeExport,
    DepartementExport,
    EntreeIndex,
    MetaExport,
    OrganisationExport,
)


def schema_donnees_site() -> dict[str, Any]:
    """Schéma unique décrivant tous les fichiers exportés."""
    modeles: list[type[BaseModel]] = [
        MetaExport,
        EntreeIndex,
        OrganisationExport,
        DepartementExport,
        AlternativeExport,
    ]
    entrees: list[tuple[type[BaseModel], Literal["serialization"]]] = [
        (m, "serialization") for m in modeles
    ]
    _, schema = models_json_schema(entrees, ref_template="#/$defs/{model}")
    definitions = schema.get("$defs", {})
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "DonneesSite",
        "description": "Contrat de données entre le scanner Bleu Blanc Cloud et le site.",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "meta": {"$ref": "#/$defs/MetaExport"},
            "index": {"type": "array", "items": {"$ref": "#/$defs/EntreeIndex"}},
            "organisation": {"$ref": "#/$defs/OrganisationExport"},
            "departements": {"type": "array", "items": {"$ref": "#/$defs/DepartementExport"}},
            "alternatives": {"type": "array", "items": {"$ref": "#/$defs/AlternativeExport"}},
        },
        "required": ["meta", "index", "organisation", "departements", "alternatives"],
        "$defs": definitions,
    }


def ecrire_schema(dossier: Path) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / "donnees.schema.json"
    chemin.write_text(
        json.dumps(schema_donnees_site(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return chemin
