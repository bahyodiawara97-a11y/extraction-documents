"""Tests de la comparaison entre valeurs extraites et valeurs annotées.

La comparaison elle-même est un endroit où l'on peut se tromper silencieusement :
trop stricte, elle invente des erreurs (« ACME SARL » contre « Acme Sarl ») ; trop
permissive, elle en masque. Ces tests fixent où se situe la frontière.
"""

import pytest

from src.evaluation import ScoreChamp, agreger, comparer, equivalent, normaliser


class TestNormalisation:
    def test_casse_et_espaces_neutralises(self):
        assert normaliser("  ACME   SARL ") == normaliser("acme sarl")

    def test_accents_neutralises(self):
        assert normaliser("Société Générale") == normaliser("societe generale")

    def test_nombre_format_francais(self):
        assert normaliser("1 764,00") == 1764.0
        assert normaliser("1 764,00 €") == 1764.0

    def test_entier_et_flottant_equivalents(self):
        assert normaliser(540) == normaliser("540.0")

    def test_marqueurs_absence_deviennent_none(self):
        assert normaliser("null") is None
        assert normaliser("") is None
        assert normaliser(None) is None

    def test_liste_triee(self):
        assert normaliser(["NLP", "Python"]) == normaliser(["python", "nlp"])


class TestEquivalence:
    def test_montants_identiques(self):
        assert equivalent(1764.0, "1 764,00 €")

    def test_ecart_de_centime_tolere(self):
        assert equivalent(405.36, 405.35)

    def test_ecart_significatif_refuse(self):
        assert not equivalent(1764.0, 1674.0)

    @pytest.mark.parametrize("ecrit", ["2026-03-12", "12/03/2026", "12.03.2026"])
    def test_formats_de_date_equivalents(self, ecrit):
        assert equivalent("2026-03-12", ecrit, champ="date_emission")

    def test_dates_differentes_refusees(self):
        assert not equivalent("2026-03-12", "2026-03-13", champ="date_emission")

    def test_deux_valeurs_absentes_sont_equivalentes(self):
        assert equivalent(None, "null")

    def test_absence_contre_valeur_refusee(self):
        assert not equivalent(None, "1 an")
        assert not equivalent("1 an", None)


class TestComparaison:
    CHAMPS = ["numero_facture", "montant_ttc", "date_emission", "devise"]

    def test_tout_correct(self):
        attendu = {
            "numero_facture": "FA-001",
            "montant_ttc": 120.0,
            "date_emission": "2026-01-01",
            "devise": "EUR",
        }
        issues = comparer(attendu, dict(attendu), self.CHAMPS)
        assert set(issues.values()) == {"correct"}

    def test_omission_detectee(self):
        attendu = {"numero_facture": "FA-001"}
        issues = comparer(attendu, {"numero_facture": None}, self.CHAMPS)
        assert issues["numero_facture"] == "omission"

    def test_hallucination_detectee(self):
        # Rien n'était attendu, le pipeline a pourtant produit une valeur.
        issues = comparer({"devise": None}, {"devise": "EUR"}, self.CHAMPS)
        assert issues["devise"] == "hallucination"

    def test_valeur_fausse_detectee(self):
        issues = comparer({"montant_ttc": 120.0}, {"montant_ttc": 999.0}, self.CHAMPS)
        assert issues["montant_ttc"] == "incorrect"

    def test_vide_des_deux_cotes_est_correct(self):
        issues = comparer({"devise": None}, {"devise": None}, self.CHAMPS)
        assert issues["devise"] == "vide_correct"

    def test_omission_et_hallucination_ne_sont_pas_confondues(self):
        issues = comparer(
            {"numero_facture": "FA-001", "devise": None},
            {"numero_facture": None, "devise": "EUR"},
            self.CHAMPS,
        )
        assert issues["numero_facture"] == "omission"
        assert issues["devise"] == "hallucination"


class TestScores:
    def test_precision_et_rappel(self):
        s = ScoreChamp(champ="montant_ttc", corrects=8, incorrects=1, omissions=1, hallucinations=0)
        assert s.attendus == 10
        assert s.extraits == 9
        assert s.precision == pytest.approx(8 / 9)
        assert s.rappel == pytest.approx(0.8)

    def test_precision_penalisee_par_les_hallucinations(self):
        propre = ScoreChamp(champ="x", corrects=9, omissions=1)
        inventif = ScoreChamp(champ="x", corrects=9, omissions=1, hallucinations=5)
        assert propre.rappel == inventif.rappel, "le rappel ne voit pas les hallucinations"
        assert inventif.precision < propre.precision, "la précision doit les voir"

    def test_taux_hallucination(self):
        s = ScoreChamp(champ="x", hallucinations=2, vides_corrects=8)
        assert s.taux_hallucination == pytest.approx(0.2)

    def test_scores_indefinis_sans_donnees(self):
        s = ScoreChamp(champ="x")
        assert s.precision is None
        assert s.rappel is None
        assert s.f1 is None


class TestAgregation:
    def test_comptage_sur_plusieurs_documents(self):
        champs = ["numero_facture", "montant_ttc"]
        comparaisons = [
            (
                "a.pdf",
                {"numero_facture": "A", "montant_ttc": 10.0},
                {"numero_facture": "A", "montant_ttc": 10.0},
                {"numero_facture": "correct", "montant_ttc": "correct"},
            ),
            (
                "b.pdf",
                {"numero_facture": "B", "montant_ttc": 20.0},
                {"numero_facture": None, "montant_ttc": 99.0},
                {"numero_facture": "omission", "montant_ttc": "incorrect"},
            ),
        ]
        resultat = agreger(comparaisons, champs)
        assert resultat.documents_evalues == 2
        assert resultat.par_champ["numero_facture"].corrects == 1
        assert resultat.par_champ["numero_facture"].omissions == 1
        assert resultat.par_champ["montant_ttc"].incorrects == 1
        # Trois valeurs produites (deux justes, une fausse), l'omission n'en est pas une.
        assert resultat.precision_globale == pytest.approx(2 / 3)
        # Quatre valeurs attendues, deux retrouvées.
        assert resultat.rappel_global == pytest.approx(2 / 4)

    def test_exemples_d_erreurs_conserves(self):
        comparaisons = [
            (
                "b.pdf",
                {"montant_ttc": 20.0},
                {"montant_ttc": 99.0},
                {"montant_ttc": "incorrect"},
            )
        ]
        resultat = agreger(comparaisons, ["montant_ttc"])
        exemples = resultat.par_champ["montant_ttc"].exemples_erreurs
        assert len(exemples) == 1
        assert "b.pdf" in exemples[0] and "99.0" in exemples[0]
