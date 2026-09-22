"""Interface Streamlit : dépôt de documents, extraction, contrôle, export.

Lancer avec :  streamlit run app.py
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src.export import vers_dataframe
from src.pipeline import ResultatLot, traiter_octets
from src.schemas import SCHEMAS

load_dotenv()

st.set_page_config(page_title="Extraction de documents", page_icon="📄", layout="wide")

st.title("📄 Extraction automatique d'informations")
st.caption(
    "Dépose des factures, CV ou contrats (PDF ou image) : le pipeline en extrait "
    "les champs clés et signale les documents à relire."
)

# --- Barre latérale : configuration ---
with st.sidebar:
    st.header("Configuration")

    type_document = st.selectbox(
        "Type de document",
        options=list(SCHEMAS.keys()),
        format_func=str.capitalize,
        help="Détermine les champs qui seront extraits.",
    )

    cle_presente = bool(os.getenv("ANTHROPIC_API_KEY"))
    if cle_presente:
        st.success("Clé API détectée")
    else:
        st.warning("Aucune clé API dans l'environnement")
        cle_saisie = st.text_input("Clé API Anthropic", type="password")
        if cle_saisie:
            os.environ["ANTHROPIC_API_KEY"] = cle_saisie
            cle_presente = True

    st.caption(
        "Un document est signalé à relire quand un contrôle métier échoue ou qu'un "
        "champ indispensable manque — jamais sur un simple seuil de complétude, "
        "qu'un document peut faire baisser sans la moindre erreur d'extraction."
    )

    with st.expander("Champs extraits pour ce type"):
        for nom, champ in SCHEMAS[type_document].model_fields.items():
            st.markdown(f"**{nom}** — {champ.description or '—'}")

# --- Zone principale : upload ---
fichiers = st.file_uploader(
    "Documents à traiter",
    type=["pdf", "png", "jpg", "jpeg", "tiff", "txt"],
    accept_multiple_files=True,
)

if fichiers and st.button("Lancer l'extraction", type="primary", disabled=not cle_presente):
    schema = SCHEMAS[type_document]
    lot = ResultatLot()
    barre = st.progress(0.0, text="Traitement en cours…")

    for i, fichier in enumerate(fichiers):
        barre.progress((i + 1) / len(fichiers), text=f"Traitement de {fichier.name}…")
        lot.documents.append(traiter_octets(fichier.getvalue(), fichier.name, schema))

    barre.empty()
    st.session_state["lot"] = lot

# --- Résultats ---
lot: ResultatLot | None = st.session_state.get("lot")

if lot and lot.documents:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Documents", len(lot.documents))
    c2.metric("Extraits", lot.nb_succes)
    c3.metric("Échecs", lot.nb_echecs)
    c4.metric("À relire", lot.nb_a_reviser)

    df = vers_dataframe(lot)

    st.subheader("Données extraites")
    st.dataframe(
        df.style.apply(
            lambda ligne: [
                "background-color: rgba(255, 193, 7, 0.15)"
                if ligne.get("necessite_revision")
                else ""
                for _ in ligne
            ],
            axis=1,
        ),
        use_container_width=True,
    )

    # Détail par document, en distinguant ce qui est une erreur de ce qui est
    # seulement inhabituel — la confusion entre les deux était le défaut à corriger.
    with st.expander("Détail par document"):
        for doc in lot.documents:
            if not doc.succes:
                st.error(f"**{doc.nom_fichier}** — {doc.erreur}")
                continue
            if doc.rapport is None:
                continue

            if doc.rapport.controles_echoues:
                st.warning(
                    f"**{doc.nom_fichier}** — contrôles en échec\n\n"
                    + "\n".join(f"- {c}" for c in doc.rapport.controles_echoues)
                )
            if doc.rapport.champs_critiques_manquants:
                st.warning(
                    f"**{doc.nom_fichier}** — champs indispensables absents : "
                    + ", ".join(doc.rapport.champs_critiques_manquants)
                )
            if doc.rapport.remarques:
                st.info(
                    f"**{doc.nom_fichier}** — remarques (pas des erreurs)\n\n"
                    + "\n".join(f"- {r}" for r in doc.rapport.remarques)
                )

    st.subheader("Export")
    col_csv, col_xlsx = st.columns(2)

    col_csv.download_button(
        "Télécharger en CSV",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{type_document}s_extraits.csv",
        mime="text/csv",
    )

    import io

    tampon = io.BytesIO()
    with pd.ExcelWriter(tampon, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Donnees", index=False)
    col_xlsx.download_button(
        "Télécharger en Excel",
        data=tampon.getvalue(),
        file_name=f"{type_document}s_extraits.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

elif not fichiers:
    st.info("Dépose un ou plusieurs documents pour commencer.")
