"""Orchestration : enchaîne extraction -> structuration -> validation.

C'est ici qu'on voit que le projet est un *pipeline* et non un agent : l'ordre des
étapes est fixé par le code, pas décidé par le modèle. Le LLM n'intervient qu'à
l'étape de structuration, comme un composant parmi d'autres.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Type

from pydantic import BaseModel

from .extraction import ResultatExtraction, extraire_texte, extraire_texte_depuis_octets
from .structuration import ErreurStructuration, structurer
from .validation import RapportValidation, valider

logger = logging.getLogger(__name__)


@dataclass
class DocumentTraite:
    """Tout ce que le pipeline sait d'un document après traitement."""

    nom_fichier: str
    succes: bool
    donnees: BaseModel | None = None
    rapport: RapportValidation | None = None
    methode_extraction: str | None = None
    nb_pages: int = 0
    duree_secondes: float = 0.0
    erreur: str | None = None

    def en_ligne(self) -> dict:
        """Aplatit le résultat en une ligne de tableau (une clé = une colonne)."""
        ligne: dict = {"fichier": self.nom_fichier, "succes": self.succes}
        if self.donnees is not None:
            for cle, valeur in self.donnees.model_dump().items():
                # Les listes et sous-objets sont sérialisés pour tenir dans une cellule.
                if isinstance(valeur, (list, dict)):
                    ligne[cle] = _aplatir_valeur(valeur)
                else:
                    ligne[cle] = valeur
        if self.rapport is not None:
            ligne["score_confiance"] = self.rapport.score_confiance
            ligne["necessite_revision"] = self.rapport.necessite_revision
            ligne["alertes"] = " | ".join(self.rapport.alertes)
            ligne["champs_manquants"] = ", ".join(self.rapport.champs_manquants)
        ligne["methode_extraction"] = self.methode_extraction
        ligne["nb_pages"] = self.nb_pages
        ligne["duree_s"] = round(self.duree_secondes, 2)
        if self.erreur:
            ligne["erreur"] = self.erreur
        return ligne


@dataclass
class ResultatLot:
    """Résultat du traitement d'un lot de documents."""

    documents: list[DocumentTraite] = field(default_factory=list)

    @property
    def nb_succes(self) -> int:
        return sum(1 for d in self.documents if d.succes)

    @property
    def nb_echecs(self) -> int:
        return len(self.documents) - self.nb_succes

    @property
    def nb_a_reviser(self) -> int:
        return sum(1 for d in self.documents if d.rapport and d.rapport.necessite_revision)

    def en_lignes(self) -> list[dict]:
        return [d.en_ligne() for d in self.documents]


def traiter_document(
    chemin: str | Path, schema: Type[BaseModel], modele: str | None = None
) -> DocumentTraite:
    """Traite un document du disque, de bout en bout."""
    chemin = Path(chemin)
    debut = time.perf_counter()
    try:
        extraction = extraire_texte(chemin)
        return _finaliser(chemin.name, extraction, schema, modele, debut)
    except Exception as exc:  # noqa: BLE001 - un document en échec ne doit pas stopper le lot
        logger.exception("Échec du traitement de %s", chemin.name)
        return DocumentTraite(
            nom_fichier=chemin.name,
            succes=False,
            erreur=f"{type(exc).__name__}: {exc}",
            duree_secondes=time.perf_counter() - debut,
        )


def traiter_octets(
    contenu: bytes, nom_fichier: str, schema: Type[BaseModel], modele: str | None = None
) -> DocumentTraite:
    """Traite un fichier uploadé (Streamlit), sans le stocker durablement."""
    debut = time.perf_counter()
    try:
        extraction = extraire_texte_depuis_octets(contenu, nom_fichier)
        return _finaliser(nom_fichier, extraction, schema, modele, debut)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Échec du traitement de %s", nom_fichier)
        return DocumentTraite(
            nom_fichier=nom_fichier,
            succes=False,
            erreur=f"{type(exc).__name__}: {exc}",
            duree_secondes=time.perf_counter() - debut,
        )


def traiter_lot(
    chemins: list[str | Path], schema: Type[BaseModel], modele: str | None = None
) -> ResultatLot:
    """Traite une liste de documents et agrège les résultats."""
    lot = ResultatLot()
    for chemin in chemins:
        lot.documents.append(traiter_document(chemin, schema, modele))
    return lot


def _finaliser(
    nom: str,
    extraction: ResultatExtraction,
    schema: Type[BaseModel],
    modele: str | None,
    debut: float,
) -> DocumentTraite:
    if extraction.est_vide:
        raise ErreurStructuration(
            f"Aucun texte exploitable extrait ({extraction.nb_caracteres} caractères). "
            "Document illisible, vide, ou OCR à régler."
        )

    donnees = structurer(extraction.texte, schema, modele=modele)
    rapport = valider(donnees)

    return DocumentTraite(
        nom_fichier=nom,
        succes=True,
        donnees=donnees,
        rapport=rapport,
        methode_extraction=extraction.methode,
        nb_pages=extraction.nb_pages,
        duree_secondes=time.perf_counter() - debut,
    )


def _aplatir_valeur(valeur) -> str:
    """Rend une liste ou un dict lisible dans une cellule de tableau."""
    if isinstance(valeur, list):
        if valeur and isinstance(valeur[0], dict):
            return " | ".join(
                ", ".join(f"{k}={v}" for k, v in element.items() if v) for element in valeur
            )
        return ", ".join(str(v) for v in valeur)
    if isinstance(valeur, dict):
        return ", ".join(f"{k}={v}" for k, v in valeur.items() if v)
    return str(valeur)
