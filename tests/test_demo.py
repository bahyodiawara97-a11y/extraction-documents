"""Tests du mode démonstration.

Ce qui importe ici : la démonstration doit reconstruire les *mêmes objets* que le
pipeline réel. Si elle produisait des structures approchantes, l'interface finirait
par afficher autre chose que ce que le traitement produit — c'est-à-dire mentir au
visiteur, discrètement.
"""

import json

import pytest

from src.demo import charger, commentaires
from src.schemas import SCHEMAS


@pytest.fixture
def fichier_demo(tmp_path):
    contenu = {
        "genere_le": "2026-09-22",
        "modele": "claude-sonnet-5",
        "scores": {
            "documents": 2,
            "precision_globale": 1.0,
            "rappel_global": 1.0,
            "hallucinations": 0,
            "par_champ": [{"champ": "montant_ttc", "precision": 1.0, "rappel": 1.0}],
        },
        "documents": [
            {
                "fichier": "facture_a.pdf",
                "type": "facture",
                "commentaire": "PDF natif ordinaire",
                "succes": True,
                "methode_extraction": "pdf_natif",
                "nb_pages": 1,
                "duree_s": 3.2,
                "donnees": {
                    "numero_facture": "FA-001",
                    "date_emission": "2026-03-12",
                    "nom_fournisseur": "ACME",
                    "montant_ht": 100.0,
                    "montant_tva": 20.0,
                    "montant_ttc": 120.0,
                    "devise": "EUR",
                },
                "rapport": {
                    "taux_completude": 0.78,
                    "controles_echoues": [],
                    "champs_critiques_manquants": [],
                    "remarques": [],
                },
            },
            {
                "fichier": "recu_b.pdf",
                "type": "facture",
                "commentaire": "Reçu sans TVA",
                "succes": True,
                "methode_extraction": "pdf_natif",
                "nb_pages": 1,
                "duree_s": 2.1,
                "donnees": {
                    "date_emission": "2026-02-11",
                    "nom_fournisseur": "LIBRAIRIE",
                    "montant_ttc": 73.5,
                    "devise": "EUR",
                },
                "rapport": {
                    "taux_completude": 0.44,
                    "controles_echoues": [],
                    "champs_critiques_manquants": [],
                    "remarques": ["Ni HT ni TVA : document possiblement exonéré"],
                },
            },
        ],
    }
    chemin = tmp_path / "demo.json"
    chemin.write_text(json.dumps(contenu, ensure_ascii=False), encoding="utf-8")
    return chemin


class TestChargement:
    def test_nombre_de_documents(self, fichier_demo):
        lot, _ = charger(SCHEMAS, fichier_demo)
        assert len(lot.documents) == 2

    def test_donnees_typees_comme_le_pipeline(self, fichier_demo):
        # Pas un dictionnaire : une vraie instance du schéma, comme en traitement réel.
        lot, _ = charger(SCHEMAS, fichier_demo)
        doc = lot.documents[0]
        assert isinstance(doc.donnees, SCHEMAS["facture"])
        assert doc.donnees.montant_ttc == 120.0
        assert doc.donnees.numero_facture == "FA-001"

    def test_champs_absents_restent_vides(self, fichier_demo):
        lot, _ = charger(SCHEMAS, fichier_demo)
        recu = lot.documents[1]
        assert recu.donnees.montant_ht is None
        assert recu.donnees.numero_facture is None

    def test_rapport_reconstruit(self, fichier_demo):
        lot, _ = charger(SCHEMAS, fichier_demo)
        rapport = lot.documents[1].rapport
        assert rapport.taux_completude == 0.44
        assert rapport.remarques and "exonéré" in rapport.remarques[0]
        # Une remarque n'est pas une erreur : elle ne déclenche pas de relecture.
        assert not rapport.necessite_revision

    def test_metadonnees(self, fichier_demo):
        _, meta = charger(SCHEMAS, fichier_demo)
        assert meta["modele"] == "claude-sonnet-5"
        assert meta["scores"]["hallucinations"] == 0

    def test_lot_exploitable_comme_un_lot_reel(self, fichier_demo):
        # Les propriétés agrégées doivent fonctionner sans code spécifique.
        lot, _ = charger(SCHEMAS, fichier_demo)
        assert lot.nb_succes == 2
        assert lot.nb_echecs == 0
        assert lot.nb_a_reviser == 0
        lignes = lot.en_lignes()
        assert len(lignes) == 2
        assert lignes[0]["montant_ttc"] == 120.0

    def test_commentaires(self, fichier_demo):
        c = commentaires(fichier_demo)
        assert c["facture_a.pdf"] == "PDF natif ordinaire"
        assert c["recu_b.pdf"] == "Reçu sans TVA"


class TestDocumentEnEchec:
    def test_echec_conserve(self, tmp_path):
        chemin = tmp_path / "demo.json"
        chemin.write_text(
            json.dumps(
                {
                    "documents": [
                        {
                            "fichier": "casse.pdf",
                            "type": "facture",
                            "succes": False,
                            "erreur": "ErreurStructuration: texte vide",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        lot, _ = charger(SCHEMAS, chemin)
        assert lot.nb_echecs == 1
        assert "texte vide" in lot.documents[0].erreur
