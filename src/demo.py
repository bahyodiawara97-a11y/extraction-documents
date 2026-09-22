"""Mode démonstration : rejoue des résultats figés, sans aucun appel API.

Raison d'être. Ce pipeline appelle une API payante. Une démonstration publique pose
donc un dilemme : déployée avec une clé, elle laisse n'importe quel visiteur dépenser
le crédit de son auteur ; déployée sans, elle accueille le visiteur par une demande
de clé qu'il n'a pas.

D'où ce troisième terme : les résultats de l'exécution sur le jeu d'évaluation sont
figés dans un fichier, et l'interface les rejoue. Le visiteur voit le tableau extrait,
les contrôles de cohérence et les remarques, exactement comme s'il avait lancé le
traitement — pour zéro appel et zéro euro. Le traitement réel reste disponible à côté,
pour qui apporte sa propre clé.

Le fichier est produit par `evaluation/generer_demo.py`, qui exécute le vrai pipeline.
Rien n'est écrit à la main : ce que la démonstration montre a réellement été produit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Type

from pydantic import BaseModel

from .pipeline import DocumentTraite, ResultatLot
from .validation import RapportValidation

CHEMIN_DEFAUT = Path("evaluation/demo.json")


def _rapport_depuis_dict(donnees: dict) -> RapportValidation:
    return RapportValidation(
        taux_completude=donnees.get("taux_completude", 0.0),
        controles_echoues=donnees.get("controles_echoues", []),
        champs_critiques_manquants=donnees.get("champs_critiques_manquants", []),
        remarques=donnees.get("remarques", []),
    )


def charger(
    schemas: dict[str, Type[BaseModel]], chemin: Path | str = CHEMIN_DEFAUT
) -> tuple[ResultatLot, dict]:
    """Reconstruit un lot traité à partir du fichier de démonstration.

    Les objets rendus sont ceux du pipeline réel : l'interface n'a donc aucun code
    d'affichage spécifique à la démonstration, et ce que le visiteur voit ne peut pas
    diverger de ce que produit le traitement.

    Returns:
        (lot reconstruit, métadonnées : date de génération, modèle, scores).
    """
    chemin = Path(chemin)
    contenu = json.loads(chemin.read_text(encoding="utf-8"))

    lot = ResultatLot()
    for entree in contenu["documents"]:
        schema = schemas[entree["type"]]
        lot.documents.append(
            DocumentTraite(
                nom_fichier=entree["fichier"],
                succes=entree.get("succes", True),
                donnees=schema.model_validate(entree["donnees"]) if entree.get("donnees") else None,
                rapport=_rapport_depuis_dict(entree["rapport"]) if entree.get("rapport") else None,
                methode_extraction=entree.get("methode_extraction"),
                nb_pages=entree.get("nb_pages", 0),
                duree_secondes=entree.get("duree_s", 0.0),
                erreur=entree.get("erreur"),
            )
        )

    meta = {k: v for k, v in contenu.items() if k != "documents"}
    return lot, meta


def commentaires(chemin: Path | str = CHEMIN_DEFAUT) -> dict[str, str]:
    """Commentaire explicatif par document : la difficulté que chacun illustre."""
    contenu = json.loads(Path(chemin).read_text(encoding="utf-8"))
    return {
        e["fichier"]: e.get("commentaire", "")
        for e in contenu["documents"]
        if e.get("commentaire")
    }
