"""Étape 3 du pipeline : vérifier la cohérence de l'extraction.

Un LLM qui extrait un mauvais montant le fait avec le même aplomb qu'un bon : sans
garde-fous, l'erreur passe inaperçue. On applique donc des règles métier vérifiables.

Une leçon apprise en chemin, qui explique la structure de ce module. Ce rapport
exposait autrefois un `score_confiance`, calculé comme la proportion de champs
remplis. Les deux notions coïncidaient tant que les documents avaient la forme
attendue. Une quittance de soins — sans TVA, parce que les actes médicaux n'y sont
pas soumis — a révélé la divergence : extraction parfaite, score de 0,67, document
signalé à tort. Le calcul était honnête, c'est son nom qui promettait autre chose.

D'où trois notions désormais distinctes, chacune nommée d'après ce qu'elle mesure :

  - `taux_completude` : combien de champs sont renseignés. Un fait, pas un jugement.
  - `controles_echoues` : les règles métier violées (HT + TVA ≠ TTC, dates inversées).
    C'est la seule chose qui indique réellement une erreur.
  - `remarques` : ce qui est inhabituel sans être faux, comme une facture sans TVA.

Et `necessite_revision` ne dépend plus d'un seuil sur la complétude : un document
est signalé quand un contrôle échoue ou qu'un champ réellement critique manque.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from pydantic import BaseModel

from .schemas import CV, Contrat, Facture
from .structuration import MARQUEURS_ABSENCE

# Tolérance sur les arrondis de TVA (en unités de devise).
TOLERANCE_MONTANT = 0.02


@dataclass
class RapportValidation:
    """Résultat des contrôles de cohérence sur un document extrait.

    Les trois indicateurs sont volontairement séparés : ils répondent à des questions
    différentes et les confondre produit des signalements trompeurs.
    """

    taux_completude: float  # proportion de champs renseignés, entre 0.0 et 1.0
    controles_echoues: list[str] = field(default_factory=list)
    champs_critiques_manquants: list[str] = field(default_factory=list)
    remarques: list[str] = field(default_factory=list)

    @property
    def necessite_revision(self) -> bool:
        """Vrai si un contrôle a échoué ou si un champ indispensable manque.

        Volontairement indépendant du taux de complétude : un document peut être
        incomplet parce qu'il ne contient pas l'information, ce qui n'est pas une
        erreur d'extraction et ne justifie pas une relecture.
        """
        return bool(self.controles_echoues) or bool(self.champs_critiques_manquants)

    @property
    def motif_revision(self) -> str:
        """Explication lisible de la raison du signalement, ou chaîne vide."""
        motifs = []
        if self.controles_echoues:
            motifs.append(f"{len(self.controles_echoues)} contrôle(s) en échec")
        if self.champs_critiques_manquants:
            motifs.append(
                "champs indispensables absents : "
                + ", ".join(self.champs_critiques_manquants)
            )
        return " ; ".join(motifs)


def valider(donnees: BaseModel) -> RapportValidation:
    """Applique les contrôles adaptés au type de document."""
    if isinstance(donnees, Facture):
        return _valider_facture(donnees)
    if isinstance(donnees, CV):
        return _valider_cv(donnees)
    if isinstance(donnees, Contrat):
        return _valider_contrat(donnees)
    return RapportValidation(taux_completude=_taux_remplissage(donnees))


def _valider_facture(f: Facture) -> RapportValidation:
    alertes: list[str] = []
    remarques: list[str] = []

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

    # Un document sans HT ni TVA n'est pas forcément mal extrait : les actes médicaux,
    # les opérations exonérées et les quittances n'en comportent pas. On l'observe
    # sans le traiter comme une anomalie — c'est le cas qui a motivé la refonte.
    if f.montant_ttc is not None and est_vide(f.montant_ht) and est_vide(f.montant_tva):
        remarques.append(
            "Ni HT ni TVA : document possiblement exonéré (santé, export) ou quittance "
            "plutôt que facture commerciale. Vérifier que le schéma Facture est adapté."
        )

    # Ne sont critiques que les champs sans lesquels la ligne est inexploitable.
    # Le montant TTC en fait partie ; le HT et la TVA non, justement parce qu'ils
    # peuvent légitimement manquer.
    manquants = _champs_vides(f, critiques=["date_emission", "montant_ttc"])
    return _construire_rapport(f, alertes, manquants, remarques)


def _valider_cv(c: CV) -> RapportValidation:
    alertes: list[str] = []

    if c.email and "@" not in c.email:
        alertes.append(f"Email mal formé : {c.email!r}")
    if c.annees_experience is not None and not (0 <= c.annees_experience <= 60):
        alertes.append(f"Nombre d'années d'expérience improbable : {c.annees_experience}")
    remarques: list[str] = []
    if not c.competences:
        remarques.append("Aucune compétence extraite : vérifier la qualité du texte source")

    manquants = _champs_vides(c, critiques=["nom_complet"])
    return _construire_rapport(c, alertes, manquants, remarques)


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

    remarques: list[str] = []
    if c.date_debut and est_vide(c.date_fin):
        remarques.append(
            "Date de fin absente : contrat à durée indéterminée, ou durée exprimée "
            "sans date de fin explicite. Ne pas la calculer, elle n'est pas écrite."
        )

    manquants = _champs_vides(c, critiques=["type_contrat", "partie_a", "partie_b"])
    return _construire_rapport(c, alertes, manquants, remarques)


def _construire_rapport(
    donnees: BaseModel,
    controles_echoues: list[str],
    manquants: list[str],
    remarques: list[str] | None = None,
) -> RapportValidation:
    """Assemble le rapport sans mélanger les trois notions.

    Aucune combinaison en un chiffre unique : le taux de complétude reste un fait
    brut, et les contrôles échoués restent une liste de constats vérifiables. Un
    score composite serait plus compact, mais impossible à justifier auprès d'un
    utilisateur métier qui demande « pourquoi ce document est-il signalé ».
    """
    return RapportValidation(
        taux_completude=round(_taux_remplissage(donnees), 2),
        controles_echoues=controles_echoues,
        champs_critiques_manquants=manquants,
        remarques=remarques or [],
    )


def est_vide(valeur) -> bool:
    """Un champ est vide s'il est nul, s'il est une collection vide, ou s'il contient
    une chaîne qui *signale* une absence ("null", "non spécifié", "-").

    Ce dernier cas est traité en amont par src.structuration, mais on le revérifie ici :
    compter un "null" textuel comme un champ rempli fausse tous les indicateurs, et
    l'erreur est indétectable à l'œil puisque les tableurs affichent ces chaînes comme
    des cases vides.
    """
    if valeur is None:
        return True
    if isinstance(valeur, str):
        return valeur.strip().lower() in MARQUEURS_ABSENCE or not valeur.strip()
    if isinstance(valeur, (list, dict, set, tuple)):
        return len(valeur) == 0
    return False


def _taux_remplissage(donnees: BaseModel) -> float:
    valeurs = donnees.model_dump()
    if not valeurs:
        return 0.0
    return sum(1 for v in valeurs.values() if not est_vide(v)) / len(valeurs)


def _champs_vides(donnees: BaseModel, critiques: list[str]) -> list[str]:
    valeurs = donnees.model_dump()
    return [c for c in critiques if est_vide(valeurs.get(c))]


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
