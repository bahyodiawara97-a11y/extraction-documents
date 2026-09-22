"""Schémas Pydantic décrivant les champs à extraire de chaque type de document.

Ces schémas jouent deux rôles :
  1. ils sont convertis en JSON Schema et passés au LLM comme définition d'outil,
     ce qui garantit une sortie structurée valide (pas de JSON à parser à la main) ;
  2. ils valident et typent le résultat côté Python.

Les descriptions des champs ne sont pas décoratives : elles sont envoyées au modèle
et guident directement la qualité de l'extraction. Les soigner = meilleur résultat.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Facture(BaseModel):
    """Champs clés d'une facture."""

    numero_facture: Optional[str] = Field(
        None, description="Numéro ou référence de la facture, tel qu'imprimé sur le document"
    )
    date_emission: Optional[str] = Field(
        None, description="Date d'émission de la facture au format ISO AAAA-MM-JJ"
    )
    date_echeance: Optional[str] = Field(
        None, description="Date d'échéance de paiement au format ISO AAAA-MM-JJ, si mentionnée"
    )
    nom_fournisseur: Optional[str] = Field(
        None, description="Raison sociale de l'émetteur de la facture"
    )
    nom_client: Optional[str] = Field(
        None, description="Raison sociale ou nom du destinataire de la facture"
    )
    montant_ht: Optional[float] = Field(
        None, description="Montant hors taxes, en nombre décimal sans symbole de devise"
    )
    montant_tva: Optional[float] = Field(
        None, description="Montant total de la TVA, en nombre décimal sans symbole de devise"
    )
    montant_ttc: Optional[float] = Field(
        None, description="Montant toutes taxes comprises (total à payer), en nombre décimal"
    )
    devise: Optional[str] = Field(
        None, description="Code ISO 4217 de la devise, par exemple EUR ou USD"
    )


class ExperienceCV(BaseModel):
    """Une ligne d'expérience professionnelle dans un CV."""

    intitule_poste: Optional[str] = Field(None, description="Intitulé du poste occupé")
    employeur: Optional[str] = Field(None, description="Nom de l'entreprise ou de l'organisme")
    date_debut: Optional[str] = Field(None, description="Date de début au format AAAA-MM si connue")
    date_fin: Optional[str] = Field(
        None, description="Date de fin au format AAAA-MM, ou 'en cours' si le poste est actuel"
    )


class CV(BaseModel):
    """Champs clés d'un CV."""

    nom_complet: Optional[str] = Field(None, description="Nom et prénom du candidat")
    email: Optional[str] = Field(None, description="Adresse email de contact")
    telephone: Optional[str] = Field(None, description="Numéro de téléphone de contact")
    ville: Optional[str] = Field(None, description="Ville ou zone géographique du candidat")
    annees_experience: Optional[float] = Field(
        None, description="Nombre total d'années d'expérience professionnelle, estimé si non indiqué"
    )
    competences: list[str] = Field(
        default_factory=list,
        description="Liste des compétences techniques citées (outils, langages, méthodes)",
    )
    experiences: list[ExperienceCV] = Field(
        default_factory=list, description="Liste des expériences professionnelles"
    )


class Contrat(BaseModel):
    """Champs clés d'un contrat."""

    type_contrat: Optional[str] = Field(
        None, description="Nature du contrat, par exemple CDI, CDD, prestation de service, bail"
    )
    partie_a: Optional[str] = Field(None, description="Première partie signataire")
    partie_b: Optional[str] = Field(None, description="Seconde partie signataire")
    date_signature: Optional[str] = Field(None, description="Date de signature au format AAAA-MM-JJ")
    date_debut: Optional[str] = Field(None, description="Date de prise d'effet au format AAAA-MM-JJ")
    date_fin: Optional[str] = Field(
        None, description="Date de fin au format AAAA-MM-JJ, si le contrat est à durée déterminée"
    )
    montant: Optional[float] = Field(
        None, description="Montant principal du contrat, en nombre décimal"
    )
    duree_preavis: Optional[str] = Field(
        None, description="Durée du préavis telle qu'indiquée dans le contrat"
    )


# Registre : permet de sélectionner un schéma par son nom depuis l'app ou le CLI.
SCHEMAS: dict[str, type[BaseModel]] = {
    "facture": Facture,
    "cv": CV,
    "contrat": Contrat,
}
