"""
==============================================================================
OpoCoach
Archivo: pages/03_Chat.py
==============================================================================

Descripción:
    Chat especializado en la convocatoria activa.

==============================================================================
"""

import streamlit as st

from lib.chat_convocatoria import responder_chat
from lib.contexto import obtener_contexto
from lib.sesion import obtener_convocatoria_id


st.title("Chat de la convocatoria")

convocatoria_id = obtener_convocatoria_id()

if convocatoria_id is None:
    st.warning(
        "Debe seleccionar una convocatoria en la página Inicio."
    )
    st.stop()

contexto = obtener_contexto()

if contexto is None:
    st.error("La convocatoria seleccionada no existe.")
    st.stop()

st.caption(
    f'{contexto["codigo"]} — '
    f'{contexto["puesto"]}'
)

st.info(
    "El chat responde únicamente con el corpus asignado "
    "a la convocatoria activa."
)

clave_convocatoria_chat = "chat_convocatoria_id"
clave_mensajes = "chat_convocatoria_mensajes"

if (
    st.session_state.get(clave_convocatoria_chat)
    != convocatoria_id
):
    st.session_state[clave_convocatoria_chat] = convocatoria_id
    st.session_state[clave_mensajes] = []

mensajes = st.session_state.setdefault(
    clave_mensajes,
    [],
)

columna_limpiar, columna_espacio = st.columns(
    [1, 4]
)

with columna_limpiar:
    if st.button(
        "Limpiar conversación",
        use_container_width=True,
    ):
        st.session_state[clave_mensajes] = []
        st.rerun()

for mensaje in mensajes:
    rol = mensaje.get("role")

    if rol not in {"user", "assistant"}:
        continue

    with st.chat_message(rol):
        st.markdown(mensaje.get("content", ""))

pregunta = st.chat_input(
    "Escriba una duda sobre la convocatoria..."
)

if pregunta:
    pregunta_limpia = " ".join(pregunta.split())

    if pregunta_limpia:
        mensajes.append(
            {
                "role": "user",
                "content": pregunta_limpia,
            }
        )

        with st.chat_message("user"):
            st.markdown(pregunta_limpia)

        with st.chat_message("assistant"):
            with st.spinner(
                "Consultando el corpus de la convocatoria..."
            ):
                try:
                    resultado = responder_chat(
                        convocatoria_id=convocatoria_id,
                        pregunta=pregunta_limpia,
                        mensajes_previos=mensajes[:-1],
                    )

                    respuesta = resultado["respuesta"]
                    st.markdown(respuesta)

                except Exception as exc:
                    respuesta = (
                        "No se ha podido generar la respuesta. "
                        f"Error: {exc}"
                    )
                    st.error(respuesta)

        mensajes.append(
            {
                "role": "assistant",
                "content": respuesta,
            }
        )
