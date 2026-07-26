"""
==============================================================================
OpoCoach
Archivo: sesion.py
==============================================================================

Descripción:
    Gestión de la convocatoria activa en la sesión de Streamlit.

==============================================================================
"""

import streamlit as st


CLAVE_CONVOCATORIA_ID = "convocatoria_id"


def obtener_convocatoria_id() -> int | None:
    return st.session_state.get(CLAVE_CONVOCATORIA_ID)


def establecer_convocatoria_id(convocatoria_id: int) -> None:
    st.session_state[CLAVE_CONVOCATORIA_ID] = convocatoria_id


def borrar_convocatoria_id() -> None:
    st.session_state.pop(CLAVE_CONVOCATORIA_ID, None)


def hay_convocatoria_activa() -> bool:
    return obtener_convocatoria_id() is not None