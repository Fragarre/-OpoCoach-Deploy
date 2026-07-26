"""
==============================================================================
OpoCoach
Archivo: 01_Inicio.py
==============================================================================

Descripción:
    Selección y visualización de la convocatoria activa.

==============================================================================
"""

from typing import cast

import streamlit as st

from lib.contexto import obtener_contexto
from lib.repositorio import obtener_convocatorias
from lib.formato import entero
from lib.repositorio import (
    obtener_resumen_convocatoria,
)
from lib.sesion import (
    borrar_convocatoria_id,
    establecer_convocatoria_id,
    obtener_convocatoria_id,
)


st.title("Inicio")

convocatorias = obtener_convocatorias()

if not convocatorias:
    st.error("No existen convocatorias en la base de datos.")
    st.stop()

convocatoria_actual_id = obtener_convocatoria_id()

opciones = {
    fila["id"]: (
        f'{fila["codigo"]} — '
        f'{fila["puesto"]} — '
        f'{fila["numero"]}'
    )
    for fila in convocatorias
}

ids = list(opciones.keys())

indice_inicial = 0

if convocatoria_actual_id in ids:
    indice_inicial = ids.index(convocatoria_actual_id)

convocatoria_seleccionada_id = cast(
    int,
    st.selectbox(
        "Convocatoria",
        options=ids,
        index=indice_inicial,
        format_func=lambda convocatoria_id: opciones[convocatoria_id],
    ),
)

columna_seleccionar, columna_cerrar = st.columns(2)

with columna_seleccionar:
    if st.button("Seleccionar", type="primary"):
        establecer_convocatoria_id(convocatoria_seleccionada_id)
        st.rerun()

with columna_cerrar:
    if convocatoria_actual_id is not None:
        if st.button("Cerrar convocatoria"):
            borrar_convocatoria_id()
            st.rerun()

if convocatoria_actual_id is None:
    st.warning("No hay una convocatoria activa.")
    st.stop()

resumen = obtener_contexto()

if resumen is None:
    borrar_convocatoria_id()
    st.error("La convocatoria activa no existe.")
    st.stop()

st.success(
    f'Convocatoria activa: '
    f'{resumen["codigo"]} — '
    f'{resumen["puesto"]}'
)

st.write(f'**Temario:** {resumen["temario_nombre"]}')

columna_temas, columna_banco, columna_examen = st.columns(3)

with columna_temas:
    st.metric(
        "Temas",
        entero(resumen["total_temas"]),
    )

with columna_banco:
    st.metric(
        "Preguntas disponibles",
        entero(resumen["total_banco"]),
    )

with columna_examen:
    st.metric(
        "Preguntas del examen",
        entero(resumen["numero_preguntas"]),
    )