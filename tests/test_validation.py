"""Tests des règles de validation.

Ces tests ne nécessitent ni clé API ni document : ils portent sur la logique métier,
ce qui les rend rapides et déterministes. C'est exactement ce qu'on attend d'une
suite de tests sur un projet LLM — on teste ce qui est testable.

Ils encodent aussi une distinction chèrement acquise : un document *incomplet* n'est
pas un document *douteux*. Seuls un contrôle en échec ou un champ indispensable
absent déclenchent une relecture.
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

    def test_completude_non_faussee_par_des_null_textuels(self):
        # Cas réel : six champs renseignés, deux contenant la chaîne "null".
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
        assert valider(contrat).taux_completude == 0.75


class TestFacture:
    def test_facture_coherente_sans_controle_en_echec(self):
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
        assert rapport.controles_echoues == []
        assert rapport.taux_completude > 0.8
        assert not rapport.necessite_revision

    def test_incoherence_arithmetique_detectee(self):
        f = Facture(date_emission="2026-03-14", montant_ht=100.0, montant_tva=20.0, montant_ttc=150.0)
        rapport = valider(f)
        assert any("Incohérence arithmétique" in c for c in rapport.controles_echoues)
        assert rapport.necessite_revision
        assert "contrôle" in rapport.motif_revision

    def test_tolerance_arrondi_tva(self):
        # Un écart d'un centime est un arrondi, pas une erreur d'extraction.
        f = Facture(montant_ht=99.99, montant_tva=20.0, montant_ttc=119.98)
        assert not any("Incohérence arithmétique" in c for c in valider(f).controles_echoues)

    def test_ttc_inferieur_au_ht(self):
        f = Facture(montant_ht=200.0, montant_ttc=150.0)
        assert any("inférieur au montant HT" in c for c in valider(f).controles_echoues)

    def test_echeance_avant_emission(self):
        f = Facture(date_emission="2026-03-14", date_echeance="2026-02-01")
        assert any("précède la date d'émission" in c for c in valider(f).controles_echoues)

    def test_date_emission_future(self):
        assert any("futur" in c for c in valider(Facture(date_emission="2099-01-01")).controles_echoues)

    def test_devise_invalide(self):
        assert any("devise" in c.lower() for c in valider(Facture(devise="EURO")).controles_echoues)

    def test_champs_critiques_manquants(self):
        rapport = valider(Facture(nom_fournisseur="ACME"))
        assert "date_emission" in rapport.champs_critiques_manquants
        assert "montant_ttc" in rapport.champs_critiques_manquants
        assert rapport.necessite_revision

    def test_ht_et_tva_ne_sont_pas_critiques(self):
        # Une quittance de soins n'a ni HT ni TVA : ce n'est pas une extraction ratée.
        rapport = valider(
            Facture(
                numero_facture="000222780",
                date_emission="2026-09-22",
                nom_fournisseur="Centre d'imagerie",
                nom_client="Patient",
                montant_ttc=132.99,
                devise="EUR",
            )
        )
        assert rapport.champs_critiques_manquants == []
        assert rapport.controles_echoues == []
        assert not rapport.necessite_revision, "un document sans TVA ne doit pas être signalé"

    def test_absence_de_tva_produit_une_remarque(self):
        rapport = valider(Facture(date_emission="2026-09-22", montant_ttc=132.99))
        assert any("exonéré" in r or "quittance" in r for r in rapport.remarques)
        # Une remarque informe, elle ne déclenche pas de relecture.
        assert not rapport.controles_echoues

    def test_facture_vide_signalee_par_champs_critiques(self):
        rapport = valider(Facture())
        assert rapport.taux_completude < 0.3
        assert rapport.necessite_revision
        assert "date_emission" in rapport.motif_revision


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
        assert rapport.controles_echoues == []
        assert not rapport.necessite_revision

    def test_email_mal_forme(self):
        rapport = valider(CV(nom_complet="X", email="pas-un-email", competences=["Python"]))
        assert any("Email mal formé" in c for c in rapport.controles_echoues)

    def test_experience_improbable(self):
        rapport = valider(CV(nom_complet="X", annees_experience=150, competences=["Python"]))
        assert any("improbable" in c for c in rapport.controles_echoues)

    def test_absence_de_competences_est_une_remarque(self):
        rapport = valider(CV(nom_complet="X", email="x@y.fr"))
        assert any("Aucune compétence" in r for r in rapport.remarques)
        assert not rapport.necessite_revision


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
        assert any("précède la date de début" in c for c in rapport.controles_echoues)

    def test_partie_manquante(self):
        rapport = valider(Contrat(type_contrat="CDI", partie_a="A"))
        assert any("parties signataires" in c for c in rapport.controles_echoues)
        assert "partie_b" in rapport.champs_critiques_manquants

    def test_date_de_fin_absente_produit_une_remarque(self):
        # Le bail : durée d'un an, mais aucune date de fin écrite dans le document.
        rapport = valider(
            Contrat(
                type_contrat="Location meublée",
                partie_a="POUHA ESTELLE",
                partie_b="BAHYO DIAWARA",
                date_debut="2025-10-01",
                montant=540,
            )
        )
        assert any("Date de fin absente" in r for r in rapport.remarques)
        assert not rapport.necessite_revision


class TestMotifRevision:
    def test_vide_quand_rien_a_signaler(self):
        rapport = valider(
            Facture(numero_facture="A", date_emission="2026-01-01", montant_ttc=10.0)
        )
        assert rapport.motif_revision == ""

    def test_cumule_les_deux_causes(self):
        rapport = valider(Facture(montant_ht=200.0, montant_ttc=150.0))
        assert "contrôle" in rapport.motif_revision
        assert "date_emission" in rapport.motif_revision


class TestParsageDate:
    @pytest.mark.parametrize(
        "valeur", ["2026-03-14", "14/03/2026", "14-03-2026", "2026/03/14", "14.03.2026"]
    )
    def test_formats_acceptes(self, valeur):
        d = _parser_date(valeur)
        assert d is not None
        assert (d.year, d.month, d.day) == (2026, 3, 14)

    @pytest.mark.parametrize("valeur", [None, "", "quatorze mars", "32/13/2026"])
    def test_valeurs_illisibles(self, valeur):
        assert _parser_date(valeur) is None
