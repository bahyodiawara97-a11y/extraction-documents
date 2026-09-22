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

# Taille maximale d'un bloc envoyé au modèle. Au-delà, le document est découpé
# plutôt que tronqué : une troncature perd silencieusement la fin du document, et
# c'est souvent là que se trouvent les signatures, les dates et les totaux.
MAX_CARACTERES = 20_000

# Recouvrement entre deux blocs consécutifs, pour qu'une information à cheval sur
# une coupure reste entière dans au moins un des deux.
RECOUVREMENT = 1_500

# Garde-fou : chaque bloc coûte un appel API. Au-delà, on s'arrête et on le dit,
# plutôt que de lancer cinquante appels à l'insu de l'utilisateur.
MAX_BLOCS = 12

PROMPT_SYSTEME = """Tu es un système d'extraction d'informations depuis des documents d'entreprise.

Règles impératives :
- N'extrais que ce qui est explicitement présent dans le document.
- Si une information est absente ou illisible, OMETS entièrement le champ de ta réponse.
  N'écris jamais la chaîne "null", "N/A", "non spécifié" ou un tiret : un champ absent
  s'omet, il ne se remplit pas avec un mot signalant son absence.
- N'invente jamais de valeur, et ne déduis pas une information d'une autre : si la durée
  est donnée mais pas la date de fin, la date de fin reste absente.
- Le texte provient parfois d'un OCR imparfait : corrige les erreurs de reconnaissance évidentes
  (O/0, l/1, espaces parasites dans les nombres) mais ne comble pas les trous par déduction.
- Les montants doivent être des nombres décimaux, sans symbole de devise ni séparateur de milliers.
- Les dates doivent être normalisées au format ISO AAAA-MM-JJ."""

# Chaînes qu'un modèle écrit parfois pour signaler une absence, au lieu d'omettre le champ.
# Les laisser passer fausse tout ce qui compte les champs remplis — et l'export les
# transforme en cases vides à l'affichage, ce qui rend l'erreur invisible.
MARQUEURS_ABSENCE = {
    "null",
    "none",
    "nil",
    "n/a",
    "na",
    "-",
    "--",
    "vide",
    "inconnu",
    "non spécifié",
    "non specifie",
    "non précisé",
    "non precise",
    "non renseigné",
    "non renseigne",
    "non applicable",
    "non mentionné",
    "non mentionne",
    "absent",
}


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


def decouper(texte: str, taille: int = MAX_CARACTERES, recouvrement: int = RECOUVREMENT) -> list[str]:
    """Découpe un texte long en blocs qui se chevauchent, en coupant aux sauts de ligne.

    Couper au milieu d'une ligne sépare un intitulé de sa valeur — exactement ce
    qu'on cherche à éviter. On repart donc du dernier saut de ligne avant la limite,
    et chaque bloc reprend la fin du précédent pour qu'une information à cheval sur
    une coupure reste entière quelque part.
    """
    if len(texte) <= taille:
        return [texte]

    if recouvrement >= taille:
        raise ValueError("Le recouvrement doit être inférieur à la taille des blocs.")

    blocs: list[str] = []
    debut = 0
    while debut < len(texte):
        fin = min(debut + taille, len(texte))

        # Reculer jusqu'au dernier saut de ligne, sauf si on est au bout du texte
        # ou si ce saut est trop en arrière (texte sans retours à la ligne).
        if fin < len(texte):
            coupure = texte.rfind("\n", debut + taille // 2, fin)
            if coupure != -1:
                fin = coupure

        blocs.append(texte[debut:fin])

        if fin >= len(texte):
            break
        debut = max(fin - recouvrement, debut + 1)

    return blocs


def structurer(texte: str, schema: Type[T], modele: str | None = None) -> T:
    """Extrait les champs définis par `schema` depuis `texte`.

    Les documents plus longs que MAX_CARACTERES sont découpés en blocs, extraits
    séparément, puis fusionnés — plutôt que tronqués, ce qui perdrait la fin du
    document sans le signaler autrement que par un avertissement.

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
    blocs = decouper(texte)

    if len(blocs) > MAX_BLOCS:
        raise ErreurStructuration(
            f"Document trop long : {len(texte)} caractères donneraient {len(blocs)} blocs "
            f"(maximum {MAX_BLOCS}, soit autant d'appels API). Découper le document en amont."
        )

    if len(blocs) > 1:
        logger.info(
            "Document de %d caractères découpé en %d blocs (%d appels API)",
            len(texte),
            len(blocs),
            len(blocs),
        )

    resultats = [
        _extraire_bloc(bloc, schema, modele, i + 1, len(blocs)) for i, bloc in enumerate(blocs)
    ]
    return _fusionner(resultats, schema)


def _extraire_bloc(texte: str, schema: Type[T], modele: str, index: int, total: int) -> T:
    """Un appel au modèle pour un bloc de texte."""
    nom_outil = f"extraire_{schema.__name__.lower()}"
    outil = {
        "name": nom_outil,
        "description": f"Enregistre les champs extraits d'un document de type {schema.__name__}.",
        "input_schema": _json_schema_compatible(schema),
    }

    situation = (
        ""
        if total == 1
        else (
            f"\n\nCe texte est l'extrait {index} sur {total} d'un document plus long. "
            "Extrais uniquement ce que contient cet extrait, et omets les champs dont "
            "l'information ne s'y trouve pas."
        )
    )

    reponse = _client().messages.create(
        model=modele,
        max_tokens=2048,
        system=PROMPT_SYSTEME,
        tools=[outil],
        tool_choice={"type": "tool", "name": nom_outil},  # force l'usage de l'outil
        messages=[
            {
                "role": "user",
                "content": f"Voici le texte du document :\n\n<document>\n{texte}\n</document>{situation}",
            }
        ],
    )

    bloc = next((b for b in reponse.content if b.type == "tool_use"), None)
    if bloc is None:
        raise ErreurStructuration("Le modèle n'a pas appelé l'outil d'extraction.")

    try:
        return schema.model_validate(nettoyer_marqueurs(bloc.input))
    except ValidationError as exc:
        raise ErreurStructuration(
            f"Sortie du modèle non conforme au schéma : {exc}\nReçu : {json.dumps(bloc.input, ensure_ascii=False)}"
        ) from exc


def nettoyer_marqueurs(valeur):
    """Remplace par None les chaînes qui signalent une absence au lieu de l'exprimer.

    Un modèle qui écrit "null" ou "non spécifié" dans un champ texte produit une valeur
    syntaxiquement valide et sémantiquement vide. Sans ce nettoyage, tout ce qui compte
    les champs remplis est faussé — et l'export en tableur transforme ces chaînes en
    cases vides à l'affichage, ce qui masque l'erreur au lieu de la révéler.

    On corrige ici plutôt que de compter sur le prompt : une consigne dans un prompt est
    une requête, pas une garantie.
    """
    if isinstance(valeur, str):
        return None if valeur.strip().lower() in MARQUEURS_ABSENCE else valeur
    if isinstance(valeur, dict):
        return {c: nettoyer_marqueurs(v) for c, v in valeur.items()}
    if isinstance(valeur, list):
        nettoyes = [nettoyer_marqueurs(v) for v in valeur]
        return [v for v in nettoyes if v is not None]
    return valeur


def _fusionner(resultats: list[T], schema: Type[T]) -> T:
    """Combine les extractions de plusieurs blocs en un seul résultat.

    Règle pour un champ simple : la première valeur non vide rencontrée l'emporte.
    Les blocs suivent l'ordre du document, et une information y apparaît en général
    à sa place logique — le numéro en tête, les totaux à la fin.

    Règle pour une liste : concaténation avec déduplication, car les listes
    (compétences, expériences) se répartissent naturellement entre les blocs.
    """
    if len(resultats) == 1:
        return resultats[0]

    fusion: dict = {}
    for champ in schema.model_fields:
        valeurs = [getattr(r, champ) for r in resultats]

        if any(isinstance(v, list) for v in valeurs):
            elements: list = []
            vus: set = set()
            for valeur in valeurs:
                for element in valeur or []:
                    cle = _cle_deduplication(element)
                    if cle not in vus:
                        vus.add(cle)
                        elements.append(element)
            fusion[champ] = elements
        else:
            fusion[champ] = next((v for v in valeurs if v not in (None, "")), None)

    return schema.model_validate(fusion)


def _cle_deduplication(element) -> str:
    """Clé stable pour dédupliquer les éléments d'une liste, objets compris."""
    if isinstance(element, BaseModel):
        return json.dumps(element.model_dump(), sort_keys=True, default=str)
    return str(element).strip().lower()


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
