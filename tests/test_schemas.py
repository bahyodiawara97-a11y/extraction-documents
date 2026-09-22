"""Tests sur la génération du JSON Schema transmis au LLM.

Si ces tests cassent, c'est que le schéma envoyé au modèle n'est plus celui qu'on croit
— ce qui se traduirait par des extractions silencieusement dégradées.
"""

from src.schemas import SCHEMAS, CV, Facture
from src.structuration import _json_schema_compatible


def test_tous_les_schemas_sont_convertibles():
    for nom, schema in SCHEMAS.items():
        js = _json_schema_compatible(schema)
        assert js["type"] == "object", nom
        assert "properties" in js, nom


def test_optional_est_aplati():
    js = _json_schema_compatible(Facture)
    montant = js["properties"]["montant_ttc"]
    # Après aplatissement il ne doit plus rester d'union anyOf.
    assert "anyOf" not in montant
    assert montant["type"] == "number"


def test_descriptions_conservees():
    # Les descriptions guident le modèle : elles doivent survivre à la conversion.
    js = _json_schema_compatible(Facture)
    assert js["properties"]["numero_facture"]["description"]
    assert "ISO" in js["properties"]["date_emission"]["description"]


def test_objets_imbriques_resolus():
    # CV contient une liste d'ExperienceCV : les $ref doivent être résolus.
    js = _json_schema_compatible(CV)
    experiences = js["properties"]["experiences"]
    assert experiences["type"] == "array"
    assert "$ref" not in experiences["items"]
    assert "intitule_poste" in experiences["items"]["properties"]
