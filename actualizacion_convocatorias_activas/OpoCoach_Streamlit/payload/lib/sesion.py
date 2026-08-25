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

from lib.repositorio import convocatoria_esta_activa


CLAVE_CONVOCATORIA_ID = "convocatoria_id"


def obtener_convocatoria_id() -> int | None:
    convocatoria_id = st.session_state.get(CLAVE_CONVOCATORIA_ID)
    if convocatoria_id is None:
        return None

    try:
        convocatoria_id = int(convocatoria_id)
    except (TypeError, ValueError):
        borrar_convocatoria_id()
        return None

    if not convocatoria_esta_activa(convocatoria_id):
        borrar_convocatoria_id()
        return None

    return convocatoria_id


def establecer_convocatoria_id(convocatoria_id: int) -> None:
    st.session_state[CLAVE_CONVOCATORIA_ID] = convocatoria_id


def borrar_convocatoria_id() -> None:
    st.session_state.pop(CLAVE_CONVOCATORIA_ID, None)


def hay_convocatoria_activa() -> bool:
    return obtener_convocatoria_id() is not None