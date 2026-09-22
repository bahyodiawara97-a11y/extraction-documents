"""Mesure de la justesse de l'extraction, champ par champ.

Le reste du pipeline ne peut pas savoir s'il a raison : la validation vérifie des
règles de cohérence, pas la vérité. Ce module comble ce trou en comparant les
extractions à des valeurs annotées à la main.

Quatre issues sont distinguées pour chaque champ, parce que les confondre reviendrait
à refaire l'erreur du score de confiance — un chiffre unique qui mélange des
phénomènes de natures différentes :

  - correct       : une valeur était attendue, elle a été extraite à l'identique.
  - incorrect     : une valeur était attendue, une autre a été extraite.
  - omission      : une valeur était attendue, le champ est resté vide.
  - hallucination : aucune valeur n'était attendue, le champ a pourtant été rempli.

La distinction entre omission et hallucination est celle qui compte le plus en
pratique. Une omission se rattrape — le champ est vide, un humain le voit. Une
hallucination est invisible : elle produit une valeur plausible que personne ne
remettra en question. Un pipeline qui omet vaut mieux qu'un pipeline qui invente,
et aucune mesure d'exactitude globale ne fait apparaître cette différence.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .validation import _parser_date, est_vide

# Écart relatif toléré entre deux montants, pour absorber les arrondis.
TOLERANCE_RELATIVE = 0.005


@dataclass
class ScoreChamp:
    """Décompte des issues pour un champ, sur l'ensemble des documents évalués."""

    champ: str
    corrects: int = 0
    incorrects: int = 0
    omissions: int = 0
    hallucinations: int = 0
    vides_corrects: int = 0
    exemples_erreurs: list[str] = field(default_factory=list)

    @property
    def attendus(self) -> int:
        """Nombre de documents où une valeur était attendue pour ce champ."""
        return self.corrects + self.incorrects + self.omissions

    @property
    def extraits(self) -> int:
        """Nombre de documents où le champ a été rempli."""
        return self.corrects + self.incorrects + self.hallucinations

    @property
    def precision(self) -> float | None:
        """Parmi les valeurs produites, quelle proportion est juste.

        Répond à « quand le pipeline remplit ce champ, puis-je le croire ».
        """
        return self.corrects / self.extraits if self.extraits else None

    @property
    def rappel(self) -> float | None:
        """Parmi les valeurs présentes dans les documents, quelle proportion est trouvée.

        Répond à « le pipeline rate-t-il des informations ».
        """
        return self.corrects / self.attendus if self.attendus else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.rappel
        if p is None or r is None or p + r == 0:
            return None
        return 2 * p * r / (p + r)

    @property
    def taux_hallucination(self) -> float | None:
        """Parmi les champs qui devaient rester vides, quelle proportion a été inventée."""
        total_vides = self.hallucinations + self.vides_corrects
        return self.hallucinations / total_vides if total_vides else None


@dataclass
class ResultatEvaluation:
    """Résultat complet d'une campagne d'évaluation."""

    par_champ: dict[str, ScoreChamp] = field(default_factory=dict)
    documents_evalues: int = 0
    documents_en_echec: list[str] = field(default_factory=list)

    @property
    def precision_globale(self) -> float | None:
        corrects = sum(s.corrects for s in self.par_champ.values())
        extraits = sum(s.extraits for s in self.par_champ.values())
        return corrects / extraits if extraits else None

    @property
    def rappel_global(self) -> float | None:
        corrects = sum(s.corrects for s in self.par_champ.values())
        attendus = sum(s.attendus for s in self.par_champ.values())
        return corrects / attendus if attendus else None

    @property
    def hallucinations_totales(self) -> int:
        return sum(s.hallucinations for s in self.par_champ.values())

    def lignes_tableau(self) -> list[dict]:
        """Résultats sous forme de lignes, pour affichage ou export."""
        lignes = []
        for score in sorted(self.par_champ.values(), key=lambda s: s.champ):
            lignes.append(
                {
                    "champ": score.champ,
                    "attendus": score.attendus,
                    "corrects": score.corrects,
                    "incorrects": score.incorrects,
                    "omissions": score.omissions,
                    "hallucinations": score.hallucinations,
                    "precision": _arrondir(score.precision),
                    "rappel": _arrondir(score.rappel),
                    "f1": _arrondir(score.f1),
                }
            )
        return lignes


def _arrondir(valeur: float | None) -> float | None:
    return None if valeur is None else round(valeur, 3)


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def normaliser(valeur: Any) -> Any:
    """Ramène une valeur à une forme comparable.

    On compare des extractions à des annotations écrites par un humain : exiger une
    égalité stricte ferait échouer « ACME SARL » contre « Acme Sarl » et signalerait
    une erreur là où il n'y en a pas. On neutralise donc casse, accents, espaces
    multiples et ponctuation de fin — mais rien de plus, pour ne pas masquer de
    vraies divergences.
    """
    if est_vide(valeur):
        return None
    if isinstance(valeur, bool):
        return valeur
    if isinstance(valeur, (int, float)):
        return float(valeur)
    if isinstance(valeur, (list, tuple)):
        return sorted(n for n in (normaliser(v) for v in valeur) if n is not None)

    texte = str(valeur).strip()

    # Un nombre écrit en toutes lettres de format français : 1 234,56 -> 1234.56
    candidat = texte.replace(" ", "").replace(" ", "").replace("€", "").replace(",", ".")
    try:
        return float(candidat)
    except ValueError:
        pass

    return " ".join(_sans_accents(texte).lower().split()).rstrip(".,;:")


def equivalent(attendu: Any, obtenu: Any, champ: str = "") -> bool:
    """Vrai si les deux valeurs désignent la même information."""
    a, o = normaliser(attendu), normaliser(obtenu)

    if a is None and o is None:
        return True
    if a is None or o is None:
        return False

    if isinstance(a, float) and isinstance(o, float):
        if a == o:
            return True
        reference = max(abs(a), abs(o))
        return reference > 0 and abs(a - o) / reference <= TOLERANCE_RELATIVE

    # Les dates s'écrivent de plusieurs façons : on compare les dates, pas les chaînes.
    if "date" in champ.lower():
        da, do = _parser_date(str(attendu)), _parser_date(str(obtenu))
        if isinstance(da, date) and isinstance(do, date):
            return da == do

    if isinstance(a, list) and isinstance(o, list):
        return a == o

    return a == o


def comparer(attendu: dict, obtenu: dict, champs: list[str]) -> dict[str, str]:
    """Classe chaque champ d'un document en correct / incorrect / omission / hallucination."""
    issues: dict[str, str] = {}
    for champ in champs:
        valeur_attendue = attendu.get(champ)
        valeur_obtenue = obtenu.get(champ)
        attendu_vide = est_vide(valeur_attendue)
        obtenu_vide = est_vide(valeur_obtenue)

        if attendu_vide and obtenu_vide:
            issues[champ] = "vide_correct"
        elif attendu_vide and not obtenu_vide:
            issues[champ] = "hallucination"
        elif not attendu_vide and obtenu_vide:
            issues[champ] = "omission"
        elif equivalent(valeur_attendue, valeur_obtenue, champ):
            issues[champ] = "correct"
        else:
            issues[champ] = "incorrect"
    return issues


def agreger(
    comparaisons: list[tuple[str, dict, dict, dict[str, str]]], champs: list[str]
) -> ResultatEvaluation:
    """Agrège les comparaisons document par document en scores par champ.

    Args:
        comparaisons: liste de (nom_fichier, attendu, obtenu, issues).
        champs: champs du schéma évalué.
    """
    compteur = {
        "correct": "corrects",
        "incorrect": "incorrects",
        "omission": "omissions",
        "hallucination": "hallucinations",
        "vide_correct": "vides_corrects",
    }

    resultat = ResultatEvaluation()
    resultat.par_champ = {c: ScoreChamp(champ=c) for c in champs}

    for nom, attendu, obtenu, issues in comparaisons:
        resultat.documents_evalues += 1
        for champ, issue in issues.items():
            score = resultat.par_champ[champ]
            attribut = compteur[issue]
            setattr(score, attribut, getattr(score, attribut) + 1)

            if issue in ("incorrect", "hallucination") and len(score.exemples_erreurs) < 5:
                score.exemples_erreurs.append(
                    f"{nom} : attendu {attendu.get(champ)!r}, obtenu {obtenu.get(champ)!r}"
                )

    return resultat
