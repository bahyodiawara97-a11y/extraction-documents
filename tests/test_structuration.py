"""Tests du découpage des documents longs et de la fusion des extractions.

Ces tests n'appellent jamais l'API : ils portent sur la logique de découpage et de
fusion, qui est déterministe. C'est la partie qu'on peut vraiment tester dans un
pipeline LLM, et donc celle qu'il faut tester.
"""

import pytest

from src.schemas import CV, Contrat, ExperienceCV, Facture
from src.structuration import _cle_deduplication, _fusionner, decouper, nettoyer_marqueurs


class TestDecoupage:
    def test_texte_court_reste_entier(self):
        assert decouper("court", taille=100) == ["court"]

    def test_texte_long_est_decoupe(self):
        texte = "\n".join(f"ligne {i}" for i in range(500))
        blocs = decouper(texte, taille=500, recouvrement=100)
        assert len(blocs) > 1

    def test_aucun_caractere_perdu(self):
        # La propriété essentielle : la concaténation des blocs, recouvrements
        # déduits, doit couvrir tout le texte d'origine.
        texte = "\n".join(f"ligne numero {i} avec du contenu" for i in range(400))
        blocs = decouper(texte, taille=1000, recouvrement=200)
        reconstitue = blocs[0]
        for bloc in blocs[1:]:
            # Chaque bloc suivant commence dans la zone de recouvrement du précédent.
            position = reconstitue.find(bloc[:50])
            assert position != -1, "un bloc ne chevauche pas le précédent"
            reconstitue = reconstitue[:position] + bloc
        assert reconstitue == texte

    def test_coupure_aux_sauts_de_ligne(self):
        texte = "\n".join("x" * 50 for _ in range(100))
        for bloc in decouper(texte, taille=600, recouvrement=100)[:-1]:
            # Un bloc ne doit pas se terminer au milieu d'une ligne de 50 'x'.
            assert not bloc.endswith("x" * 50 + "x")

    def test_recouvrement_effectif(self):
        texte = "\n".join(f"L{i}" for i in range(1000))
        blocs = decouper(texte, taille=1000, recouvrement=300)
        assert blocs[1][:100] in blocs[0] or blocs[0][-300:] in blocs[1]

    def test_recouvrement_trop_grand_refuse(self):
        with pytest.raises(ValueError, match="recouvrement"):
            decouper("x" * 1000, taille=100, recouvrement=100)

    def test_texte_sans_saut_de_ligne(self):
        texte = "a" * 2500
        blocs = decouper(texte, taille=1000, recouvrement=100)
        assert len(blocs) >= 3
        assert "".join(b[:900] for b in blocs).startswith("a")


class TestFusion:
    def test_un_seul_resultat_inchange(self):
        f = Facture(numero_facture="A1", montant_ttc=10.0)
        assert _fusionner([f], Facture) is f

    def test_premiere_valeur_non_vide_gagne(self):
        debut = Facture(numero_facture="FA-001", nom_fournisseur="ACME")
        fin = Facture(montant_ttc=1200.0, date_echeance="2026-05-01")
        fusion = _fusionner([debut, fin], Facture)
        assert fusion.numero_facture == "FA-001"
        assert fusion.nom_fournisseur == "ACME"
        assert fusion.montant_ttc == 1200.0
        assert fusion.date_echeance == "2026-05-01"

    def test_valeur_du_premier_bloc_prioritaire(self):
        a = Facture(numero_facture="PREMIER")
        b = Facture(numero_facture="SECOND")
        assert _fusionner([a, b], Facture).numero_facture == "PREMIER"

    def test_bloc_vide_ignore(self):
        fusion = _fusionner([Facture(), Facture(montant_ttc=99.0)], Facture)
        assert fusion.montant_ttc == 99.0

    def test_listes_concatenees_et_dedupliquees(self):
        a = CV(nom_complet="Hyo", competences=["Python", "NLP"])
        b = CV(competences=["NLP", "PyTorch"])
        fusion = _fusionner([a, b], CV)
        assert fusion.nom_complet == "Hyo"
        assert fusion.competences == ["Python", "NLP", "PyTorch"]

    def test_deduplication_objets_imbriques(self):
        exp = ExperienceCV(intitule_poste="Stagiaire NLP", employeur="Labo")
        a = CV(experiences=[exp])
        b = CV(experiences=[ExperienceCV(intitule_poste="Stagiaire NLP", employeur="Labo")])
        assert len(_fusionner([a, b], CV).experiences) == 1

    def test_experiences_differentes_conservees(self):
        a = CV(experiences=[ExperienceCV(intitule_poste="A", employeur="X")])
        b = CV(experiences=[ExperienceCV(intitule_poste="B", employeur="Y")])
        assert len(_fusionner([a, b], CV).experiences) == 2


class TestNettoyageMarqueursAbsence:
    """Un modèle écrit parfois « null » dans un champ texte au lieu de l'omettre.

    Cas observé en conditions réelles sur un bail : `date_fin` et `duree_preavis`
    contenaient la chaîne "null". Le taux de remplissage les comptait comme remplis
    (score de 1,0 au lieu de 0,75) et l'export Excel les affichait comme des cases
    vides, rendant l'erreur invisible des deux côtés.
    """

    @pytest.mark.parametrize(
        "marqueur",
        ["null", "NULL", " null ", "None", "n/a", "N/A", "-", "non spécifié", "inconnu", "absent"],
    )
    def test_marqueurs_deviennent_none(self, marqueur):
        assert nettoyer_marqueurs(marqueur) is None

    @pytest.mark.parametrize("valeur", ["POUHA ESTELLE", "540", "Location meublée", "0"])
    def test_valeurs_reelles_preservees(self, valeur):
        assert nettoyer_marqueurs(valeur) == valeur

    def test_nombres_et_booleens_intacts(self):
        assert nettoyer_marqueurs(540.0) == 540.0
        assert nettoyer_marqueurs(0) == 0
        assert nettoyer_marqueurs(False) is False

    def test_nettoyage_dans_un_dictionnaire(self):
        brut = {"partie_a": "POUHA ESTELLE", "date_fin": "null", "montant": 540}
        assert nettoyer_marqueurs(brut) == {
            "partie_a": "POUHA ESTELLE",
            "date_fin": None,
            "montant": 540,
        }

    def test_marqueurs_retires_des_listes(self):
        assert nettoyer_marqueurs(["Python", "null", "NLP", "N/A"]) == ["Python", "NLP"]

    def test_nettoyage_recursif(self):
        brut = {"experiences": [{"intitule_poste": "Dev", "employeur": "null"}]}
        assert nettoyer_marqueurs(brut) == {
            "experiences": [{"intitule_poste": "Dev", "employeur": None}]
        }

    def test_cas_reel_du_bail(self):
        brut = {
            "type_contrat": "Location meublée",
            "partie_a": "POUHA ESTELLE",
            "partie_b": "BAHYO DIAWARA",
            "date_signature": "2025-09-27",
            "date_debut": "2025-10-01",
            "date_fin": "null",
            "montant": 540,
            "duree_preavis": "null",
        }
        contrat = Contrat.model_validate(nettoyer_marqueurs(brut))
        assert contrat.date_fin is None
        assert contrat.duree_preavis is None
        assert contrat.montant == 540


class TestCleDeduplication:
    def test_casse_et_espaces_ignores(self):
        assert _cle_deduplication("  Python  ") == _cle_deduplication("python")

    def test_objets_equivalents_meme_cle(self):
        a = ExperienceCV(intitule_poste="Dev", employeur="ACME")
        b = ExperienceCV(intitule_poste="Dev", employeur="ACME")
        assert _cle_deduplication(a) == _cle_deduplication(b)
