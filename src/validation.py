"""Étape 3 du pipeline : vérifier la cohérence de l'extraction et scorer la confiance.

C'est la partie qui distingue un prototype d'un outil utilisable. Un LLM qui extrait
un mauvais montant le fait avec le même aplomb qu'un bon : sans garde-fous, l'erreur
passe inaperçue. On applique donc des règles métier vérifiables et on remonte un score
qui permet de router les documents douteux vers une relecture humaine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from pydantic import BaseModel

from .schemas import CV, Contrat, Facture

# Tolérance sur les arrondis de TVA (en unités de devise).
TOLERANCE_MONTANT = 0.02


@dataclass
class RapportValidation:
    """Résultat des contrôles de cohérence sur un document extrait."""

    score_confiance: float  # entre 0.0 et 1.0
    alertes: list[str] = field(default_factory=list)
    champs_manquants: list[str] = field(default_factory=list)

    @property
    def necessite_revision(self) -> bool:
        """Vrai si le document doit être relu par un humain."""
        return self.score_confiance < 0.7 or bool(self.alertes)


def valider(donnees: BaseModel) -> RapportValidation:
    """Applique les contrôles adaptés au type de document."""
    if isinstance(donnees, Facture):
        return _valider_facture(donnees)
    if isinstance(donnees, CV):
        return _valider_cv(donnees)
    if isinstance(donnees, Contrat):
        return _valider_contrat(donnees)
    return RapportValidation(score_confiance=_taux_remplissage(donnees))


def _valider_facture(f: Facture) -> RapportValidation:
    alertes: list[str] = []

    # Contrôle arithmétique : HT + TVA doit retomber sur le TTC.
    if f.montant_ht is not None and f.montant_tva is not None and f.montant_ttc is not None:
        ecart = abs((f.montant_ht + f.montant_tva) - f.montant_ttc)
        if ecart > TOLERANCE_MONTANT:
            alertes.append(
                f"Incohérence arithmétique : HT ({f.montant_ht}) + TVA ({f.montant_tva}) "
                f"= {f.montant_ht + f.montant_tva}, mais TTC extrait = {f.montant_ttc} "
                f"(écart de {ecart:.2f})"
            )

    # Un TTC inférieur au HT est nécessairement une erreur d'extraction.
    if f.montant_ht is not None and f.montant_ttc is not None and f.montant_ttc < f.montant_ht:
        alertes.append("Le montant TTC est inférieur au montant HT")

    # Montants négatifs ou nuls : possible sur un avoir, mais mérite un signalement.
    for nom, valeur in (("HT", f.montant_ht), ("TVA", f.montant_tva), ("TTC", f.montant_ttc)):
        if valeur is not None and valeur < 0:
            alertes.append(f"Montant {nom} négatif ({valeur}) : avoir ou erreur d'extraction ?")

    # Cohérence des dates.
    d_emission = _parser_date(f.date_emission)
    d_echeance = _parser_date(f.date_echeance)
    if f.date_emission and d_emission is None:
        alertes.append(f"Date d'émission non exploitable : {f.date_emission!r}")
    if d_emission and d_echeance and d_echeance < d_emission:
        alertes.append("La date d'échéance précède la date d'émission")
    if d_emission and d_emission > date.today():
        alertes.append(f"Date d'émission dans le futur : {f.date_emission}")

    # Devise plausible.
    if f.devise and (len(f.devise) != 3 or not f.devise.isalpha()):
        alertes.append(f"Code devise inattendu : {f.devise!r} (attendu : code ISO à 3 lettres)")

    manquants = _champs_vides(f, critiques=["numero_facture", "date_emission", "montant_ttc"])
    return _construire_rapport(f, alertes, manquants)


def _valider_cv(c: CV) -> RapportValidation:
    alertes: list[str] = []

    if c.email and "@" not in c.email:
        alertes.append(f"Email mal formé : {c.email!r}")
    if c.annees_experience is not None and not (0 <= c.annees_experience <= 60):
        alertes.append(f"Nombre d'années d'expérience improbable : {c.annees_experience}")
    if not c.competences:
        alertes.append("Aucune compétence extraite : vérifier la qualité du texte source")

    manquants = _champs_vides(c, critiques=["nom_complet", "email"])
    return _construire_rapport(c, alertes, manquants)


def _valider_contrat(c: Contrat) -> RapportValidation:
    alertes: list[str] = []

    d_debut = _parser_date(c.date_debut)
    d_fin = _parser_date(c.date_fin)
    if d_debut and d_fin and d_fin < d_debut:
        alertes.append("La date de fin précède la date de début")
    if c.montant is not None and c.montant < 0:
        alertes.append(f"Montant négatif : {c.montant}")
    if not c.partie_a or not c.partie_b:
        alertes.append("Une des deux parties signataires n'a pas été identifiée")

    manquants = _champs_vides(c, critiques=["type_contrat", "partie_a", "partie_b"])
    return _construire_rapport(c, alertes, manquants)


def _construire_rapport(
    donnees: BaseModel, alertes: list[str], manquants: list[str]
) -> RapportValidation:
    """Combine taux de remplissage et alertes en un score unique.

    Le score part du taux de champs remplis, puis on retire 0.15 par alerte.
    Simple et explicable — ce qui vaut mieux qu'un score opaque quand il faut
    justifier une décision auprès d'un utilisateur métier.
    """
    score = _taux_remplissage(donnees) - 0.15 * len(alertes)
    return RapportValidation(
        score_confiance=round(max(0.0, min(1.0, score)), 2),
        alertes=alertes,
        champs_manquants=manquants,
    )


def _taux_remplissage(donnees: BaseModel) -> float:
    valeurs = donnees.model_dump()
    if not valeurs:
        return 0.0
    remplis = sum(1 for v in valeurs.values() if v not in (None, "", [], {}))
    return remplis / len(valeurs)


def _champs_vides(donnees: BaseModel, critiques: list[str]) -> list[str]:
    valeurs = donnees.model_dump()
    return [c for c in critiques if valeurs.get(c) in (None, "", [], {})]


def _parser_date(valeur: str | None) -> date | None:
    """Tente de lire une date dans les formats courants. Retourne None si illisible."""
    if not valeur:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(valeur.strip(), fmt).date()
        except ValueError:
            continue
    return None
