"""
==============================================================================
OpoCoach
Archivo: app.py
==============================================================================

Descripción:
    Punto de entrada de la aplicación OpoCoach.

Autor:
    Paco García / OpoCoach

==============================================================================
"""

import streamlit as st

# -----------------------------------------------------------------------------
# Configuración
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="OpoCoach",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------------------------------------------------------
# Cabecera
# -----------------------------------------------------------------------------

st.title("📚 OpoCoach")

st.caption("Preparación inteligente de oposiciones")

st.divider()

st.write("Bienvenido a OpoCoach.")