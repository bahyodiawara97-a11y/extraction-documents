"""Étape 2 du pipeline : transformer du texte brut en données structurées via un LLM.

Point technique important : on n'envoie pas un prompt du type « renvoie-moi du JSON »
en espérant que le modèle obéisse. On déclare le schéma Pydantic comme un *outil* et on
force son appel avec `tool_choice`. Le modèle est alors contraint de produire une sortie
conforme au JSON Schema, ce qui supprime toute une classe d'erreurs de parsing.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MODELE_PAR_DEFAUT = "claude-sonnet-5"

# Tronquer évite d'envoyer 80 pages au modèle pour extraire 8 champs.
# Pour des documents longs (contrats), voir la piste "chunking" dans le README.
MAX_CARACTERES = 20_000

PROMPT_SYSTEME = """Tu es un système d'extraction d'informations depuis des documents d'entreprise.

Règles impératives :
- N'extrais que ce qui est explicitement présent dans le document.
- Si une information est absente ou illisible, laisse le champ à null. N'invente jamais de valeur.
- Le texte provient parfois d'un OCR imparfait : corrige les erreurs de reconnaissance évidentes
  (O/0, l/1, espaces parasites dans les nombres) mais ne comble pas les trous par déduction.
- Les montants doivent être des nombres décimaux, sans symbole de devise ni séparateur de milliers.
- Les dates doivent être normalisées au format ISO AAAA-MM-JJ."""


class ErreurStructuration(RuntimeError):
    """Levée quand le LLM n'a pas pu produire une sortie exploitable."""


def _client():
    from anthropic import Anthropic

    cle = os.getenv("ANTHROPIC_API_KEY")
    if not cle:
        raise ErreurStructuration(
            "ANTHROPIC_API_KEY absente. Copier .env.example en .env et y mettre la clé."
        )
    return Anthropic(api_key=cle)


def structurer(texte: str, schema: Type[T], modele: str | None = None) -> T:
    """Extrait les champs définis par `schema` depuis `texte`.

    Args:
        texte: texte brut du document (issu de src.extraction).
        schema: classe Pydantic décrivant les champs attendus (voir src.schemas).
        modele: identifiant du modèle ; par défaut ANTHROPIC_MODEL ou la constante du module.

    Returns:
        Une instance validée de `schema`.
    """
    if not texte or not texte.strip():
        raise ErreurStructuration("Texte vide : rien à structurer.")

    modele = modele or os.getenv("ANTHROPIC_MODEL", MODELE_PAR_DEFAUT)
    texte_tronque = texte[:MAX_CARACTERES]
    if len(texte) > MAX_CARACTERES:
        logger.warning("Texte tronqué de %d à %d caractères", len(texte), MAX_CARACTERES)

    nom_outil = f"extraire_{schema.__name__.lower()}"
    outil = {
        "name": nom_outil,
        "description": f"Enregistre les champs extraits d'un document de type {schema.__name__}.",
        "input_schema": _json_schema_compatible(schema),
    }

    reponse = _client().messages.create(
        model=modele,
        max_tokens=2048,
        system=PROMPT_SYSTEME,
        tools=[outil],
        tool_choice={"type": "tool", "name": nom_outil},  # force l'usage de l'outil
        messages=[
            {
                "role": "user",
                "content": f"Voici le texte du document :\n\n<document>\n{texte_tronque}\n</document>",
            }
        ],
    )

    bloc = next((b for b in reponse.content if b.type == "tool_use"), None)
    if bloc is None:
        raise ErreurStructuration("Le modèle n'a pas appelé l'outil d'extraction.")

    try:
        return schema.model_validate(bloc.input)
    except ValidationError as exc:
        raise ErreurStructuration(
            f"Sortie du modèle non conforme au schéma : {exc}\nReçu : {json.dumps(bloc.input, ensure_ascii=False)}"
        ) from exc


def _json_schema_compatible(schema: Type[BaseModel]) -> dict:
    """Produit un JSON Schema accepté comme input_schema d'outil.

    Pydantic génère des unions `anyOf: [type, null]` pour les champs Optional, ce que
    l'API accepte, mais on aplatit pour garder un schéma lisible et robuste.
    """
    brut = schema.model_json_schema()
    definitions = brut.get("$defs", {})

    def aplatir(noeud: dict) -> dict:
        if "anyOf" in noeud:
            non_null = [v for v in noeud["anyOf"] if v.get("type") != "null"]
            if len(non_null) == 1:
                fusion = {**non_null[0]}
                if "description" in noeud:
                    fusion["description"] = noeud["description"]
                return aplatir(fusion)
        if "$ref" in noeud:
            nom = noeud["$ref"].split("/")[-1]
            return aplatir({**definitions.get(nom, {}), **{k: v for k, v in noeud.items() if k != "$ref"}})
        if noeud.get("type") == "object" and "properties" in noeud:
            noeud = {**noeud, "properties": {k: aplatir(v) for k, v in noeud["properties"].items()}}
        if noeud.get("type") == "array" and "items" in noeud:
            noeud = {**noeud, "items": aplatir(noeud["items"])}
        return {k: v for k, v in noeud.items() if k not in {"$defs", "title", "default"}}

    aplati = aplatir(brut)
    aplati["type"] = "object"
    return aplati
