"""Tests des règles de validation.

Ces tests ne nécessitent ni clé API ni document : ils portent sur la logique métier,
ce qui les rend rapides et déterministes. C'est exactement ce qu'on attend d'une
suite de tests sur un projet LLM — on teste ce qui est testable.
"""

import pytest

from src.schemas import CV, Contrat, Facture
from src.validation import _parser_date, est_vide, valider


class TestChampVide:
    """Une chaîne qui signale une absence ne doit pas compter comme un champ rempli."""

    @pytest.mark.parametrize("valeur", [None, "", "   ", [], {}, "null", "N/A", "-", "inconnu"])
    def test_valeurs_considerees_vides(self, valeur):
        assert est_vide(valeur)

    @pytest.mark.parametrize("valeur", ["POUHA ESTELLE", 540.0, 0, False, ["Python"]])
    def test_valeurs_considerees_remplies(self, valeur):
        assert not est_vide(valeur)

    def test_score_non_fausse_par_des_null_textuels(self):
        # Le cas réel : six champs renseignés, deux contenant la chaîne "null".
        contrat = Contrat(
            type_contrat="Location meublée",
            partie_a="POUHA ESTELLE",
            partie_b="BAHYO DIAWARA",
            date_signature="2025-09-27",
            date_debut="2025-10-01",
            date_fin="null",
            montant=540,
            duree_preavis="null",
        )
        assert valider(contrat).score_confiance == 0.75


class TestFacture:
    def test_facture_coherente_sans_alerte(self):
        f = Facture(
            numero_facture="FA-2026-001",
            date_emission="2026-03-14",
            nom_fournisseur="ACME SARL",
            nom_client="Client SA",
            montant_ht=100.0,
            montant_tva=20.0,
            montant_ttc=120.0,
            devise="EUR",
        )
        rapport = valider(f)
        assert rapport.alertes == []
        assert rapport.score_confiance > 0.8
        assert not rapport.necessite_revision

    def test_incoherence_arithmetique_detectee(self):
        f = Facture(montant_ht=100.0, montant_tva=20.0, montant_ttc=150.0)
        rapport = valider(f)
        assert any("Incohérence arithmétique" in a for a in rapport.alertes)
        assert rapport.necessite_revision

    def test_tolerance_arrondi_tva(self):
        # Un écart d'un centime est un arrondi, pas une erreur d'extraction.
        f = Facture(montant_ht=99.99, montant_tva=20.0, montant_ttc=119.98)
        rapport = valider(f)
        assert not any("Incohérence arithmétique" in a for a in rapport.alertes)

    def test_ttc_inferieur_au_ht(self):
        f = Facture(montant_ht=200.0, montant_ttc=150.0)
        rapport = valider(f)
        assert any("inférieur au montant HT" in a for a in rapport.alertes)

    def test_echeance_avant_emission(self):
        f = Facture(date_emission="2026-03-14", date_echeance="2026-02-01")
        rapport = valider(f)
        assert any("précède la date d'émission" in a for a in rapport.alertes)

    def test_date_emission_future(self):
        f = Facture(date_emission="2099-01-01")
        rapport = valider(f)
        assert any("futur" in a for a in rapport.alertes)

    def test_devise_invalide(self):
        f = Facture(devise="EURO")
        rapport = valider(f)
        assert any("devise" in a.lower() for a in rapport.alertes)

    def test_champs_critiques_manquants(self):
        f = Facture(nom_fournisseur="ACME")
        rapport = valider(f)
        assert "numero_facture" in rapport.champs_manquants
        assert "montant_ttc" in rapport.champs_manquants

    def test_facture_vide_score_bas(self):
        rapport = valider(Facture())
        assert rapport.score_confiance < 0.3
        assert rapport.necessite_revision


class TestCV:
    def test_cv_valide(self):
        c = CV(
            nom_complet="Hyo Diawara",
            email="contact@example.com",
            telephone="0600000000",
            ville="Paris",
            annees_experience=2,
            competences=["Python", "NLP", "PyTorch"],
        )
        rapport = valider(c)
        assert rapport.alertes == []

    def test_email_mal_forme(self):
        rapport = valider(CV(nom_complet="X", email="pas-un-email", competences=["Python"]))
        assert any("Email mal formé" in a for a in rapport.alertes)

    def test_experience_improbable(self):
        rapport = valider(CV(annees_experience=150, competences=["Python"]))
        assert any("improbable" in a for a in rapport.alertes)

    def test_aucune_competence_signalee(self):
        rapport = valider(CV(nom_complet="X", email="x@y.fr"))
        assert any("Aucune compétence" in a for a in rapport.alertes)


class TestContrat:
    def test_dates_inversees(self):
        rapport = valider(
            Contrat(
                type_contrat="CDD",
                partie_a="A",
                partie_b="B",
                date_debut="2026-06-01",
                date_fin="2026-01-01",
            )
        )
        assert any("précède la date de début" in a for a in rapport.alertes)

    def test_partie_manquante(self):
        rapport = valider(Contrat(type_contrat="CDI", partie_a="A"))
        assert any("parties signataires" in a for a in rapport.alertes)


class TestParsageDate:
    @pytest.mark.parametrize(
        "valeur",
        ["2026-03-14", "14/03/2026", "14-03-2026", "2026/03/14", "14.03.2026"],
    )
    def test_formats_acceptes(self, valeur):
        d = _parser_date(valeur)
        assert d is not None
        assert (d.year, d.month, d.day) == (2026, 3, 14)

    @pytest.mark.parametrize("valeur", [None, "", "quatorze mars", "32/13/2026"])
    def test_valeurs_illisibles(self, valeur):
        assert _parser_date(valeur) is None
